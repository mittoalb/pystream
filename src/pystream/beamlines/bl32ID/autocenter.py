"""
Auto-Center Plugin for bl32ID

Automatically centers optical elements (pinhole, condenser, zone plate)
by detecting their position in the camera image and moving X/Y motors.
"""

import subprocess
import logging
import math
from typing import Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore

try:
    from scipy.ndimage import gaussian_filter, label as ndimage_label
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


class AutoCenterDialog(QtWidgets.QDialog):
    """Dialog for auto-centering optical elements."""

    BUTTON_TEXT = "AutoCenter"
    HANDLER_TYPE = 'singleton'

    ELEMENTS = ["Pinhole", "Condenser", "Zone Plate"]

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger or logging.getLogger(__name__)
        self.setWindowTitle("Auto Center - bl32ID")
        self.resize(520, 700)

        self.is_centering = False
        self.iteration = 0
        self.overlay_items = []
        self.last_detection = None  # (cx, cy) in data coords

        # Per-element config: motor PVs and calibration
        self.element_configs = {
            "Pinhole":    {"x_pv": "32idb:m17", "y_pv": "32idb:m18",
                           "um_px_x": 0.065, "um_px_y": 0.065},
            "Condenser":  {"x_pv": "32idb:m19", "y_pv": "32idb:m20",
                           "um_px_x": 0.065, "um_px_y": 0.065},
            "Zone Plate": {"x_pv": "32idb:m25", "y_pv": "32idb:m26",
                           "um_px_x": 0.065, "um_px_y": 0.065},
        }

        self._init_ui()

    # ── UI ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("Auto Center Optics")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_control_tab(), "Control")
        tabs.addTab(self._build_settings_tab(), "Settings")
        layout.addWidget(tabs)

        # Log
        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(180)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Close
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_control_tab(self):
        w = QtWidgets.QWidget()
        vl = QtWidgets.QVBoxLayout(w)

        # Element selector
        sel_row = QtWidgets.QHBoxLayout()
        sel_row.addWidget(QtWidgets.QLabel("Element:"))
        self.element_combo = QtWidgets.QComboBox()
        self.element_combo.addItems(self.ELEMENTS)
        self.element_combo.currentTextChanged.connect(self._on_element_changed)
        sel_row.addWidget(self.element_combo, 1)
        vl.addLayout(sel_row)

        # Status
        status_group = QtWidgets.QGroupBox("Detection Status")
        sl = QtWidgets.QFormLayout()
        self.lbl_detected = QtWidgets.QLabel("—")
        self.lbl_target = QtWidgets.QLabel("—")
        self.lbl_offset_px = QtWidgets.QLabel("—")
        self.lbl_offset_um = QtWidgets.QLabel("—")
        sl.addRow("Detected center:", self.lbl_detected)
        sl.addRow("Target:", self.lbl_target)
        sl.addRow("Offset (px):", self.lbl_offset_px)
        sl.addRow("Offset (µm):", self.lbl_offset_um)
        status_group.setLayout(sl)
        vl.addWidget(status_group)

        # Action buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_detect = QtWidgets.QPushButton("Detect")
        self.btn_detect.clicked.connect(self._on_detect)
        btn_row.addWidget(self.btn_detect)

        self.btn_center = QtWidgets.QPushButton("Center")
        self.btn_center.clicked.connect(self._on_center)
        btn_row.addWidget(self.btn_center)

        self.btn_auto = QtWidgets.QPushButton("Auto Center")
        self.btn_auto.clicked.connect(self._on_auto_center)
        btn_row.addWidget(self.btn_auto)

        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_stop)

        vl.addLayout(btn_row)
        vl.addStretch()
        return w

    def _build_settings_tab(self):
        w = QtWidgets.QWidget()
        vl = QtWidgets.QVBoxLayout(w)

        # Motor PVs
        motor_group = QtWidgets.QGroupBox("Motor PVs (per element)")
        ml = QtWidgets.QFormLayout()
        self.pv_x_input = QtWidgets.QLineEdit()
        self.pv_y_input = QtWidgets.QLineEdit()
        ml.addRow("X Motor PV:", self.pv_x_input)
        ml.addRow("Y Motor PV:", self.pv_y_input)
        self.pv_x_input.editingFinished.connect(self._save_current_config)
        self.pv_y_input.editingFinished.connect(self._save_current_config)
        motor_group.setLayout(ml)
        vl.addWidget(motor_group)

        # Calibration
        cal_group = QtWidgets.QGroupBox("Calibration")
        cl = QtWidgets.QFormLayout()
        self.cal_x_spin = QtWidgets.QDoubleSpinBox()
        self.cal_x_spin.setRange(-1000, 1000)
        self.cal_x_spin.setDecimals(4)
        self.cal_x_spin.setSuffix(" µm/px")
        self.cal_x_spin.valueChanged.connect(self._save_current_config)
        cl.addRow("X calibration:", self.cal_x_spin)

        self.cal_y_spin = QtWidgets.QDoubleSpinBox()
        self.cal_y_spin.setRange(-1000, 1000)
        self.cal_y_spin.setDecimals(4)
        self.cal_y_spin.setSuffix(" µm/px")
        self.cal_y_spin.valueChanged.connect(self._save_current_config)
        cl.addRow("Y calibration:", self.cal_y_spin)
        cal_group.setLayout(cl)
        vl.addWidget(cal_group)

        # Detection settings
        det_group = QtWidgets.QGroupBox("Detection")
        dl = QtWidgets.QFormLayout()
        self.thresh_mode = QtWidgets.QComboBox()
        self.thresh_mode.addItems(["Auto (Otsu)", "Manual"])
        self.thresh_mode.currentIndexChanged.connect(
            lambda i: self.thresh_spin.setEnabled(i == 1))
        dl.addRow("Threshold:", self.thresh_mode)

        self.thresh_spin = QtWidgets.QDoubleSpinBox()
        self.thresh_spin.setRange(0, 100)
        self.thresh_spin.setValue(30)
        self.thresh_spin.setSuffix(" %")
        self.thresh_spin.setEnabled(False)
        dl.addRow("Manual threshold:", self.thresh_spin)

        self.target_x_spin = QtWidgets.QSpinBox()
        self.target_x_spin.setRange(0, 99999)
        self.target_x_spin.setSpecialValueText("image center")
        dl.addRow("Target X:", self.target_x_spin)

        self.target_y_spin = QtWidgets.QSpinBox()
        self.target_y_spin.setRange(0, 99999)
        self.target_y_spin.setSpecialValueText("image center")
        dl.addRow("Target Y:", self.target_y_spin)
        det_group.setLayout(dl)
        vl.addWidget(det_group)

        # Iteration settings
        iter_group = QtWidgets.QGroupBox("Auto Center")
        il = QtWidgets.QFormLayout()
        self.tol_spin = QtWidgets.QDoubleSpinBox()
        self.tol_spin.setRange(0.1, 100)
        self.tol_spin.setValue(2.0)
        self.tol_spin.setSuffix(" px")
        il.addRow("Tolerance:", self.tol_spin)

        self.max_iter_spin = QtWidgets.QSpinBox()
        self.max_iter_spin.setRange(1, 50)
        self.max_iter_spin.setValue(10)
        il.addRow("Max iterations:", self.max_iter_spin)

        self.settle_spin = QtWidgets.QDoubleSpinBox()
        self.settle_spin.setRange(0.1, 30)
        self.settle_spin.setValue(1.0)
        self.settle_spin.setSuffix(" s")
        il.addRow("Settle time:", self.settle_spin)
        iter_group.setLayout(il)
        vl.addWidget(iter_group)

        vl.addStretch()

        # Load first element's settings
        self._on_element_changed(self.ELEMENTS[0])
        return w

    # ── Config management ────────────────────────────────────────────────

    def _on_element_changed(self, name):
        cfg = self.element_configs.get(name, {})
        self.pv_x_input.setText(cfg.get("x_pv", ""))
        self.pv_y_input.setText(cfg.get("y_pv", ""))
        self.cal_x_spin.setValue(cfg.get("um_px_x", 1.0))
        self.cal_y_spin.setValue(cfg.get("um_px_y", 1.0))

    def _save_current_config(self):
        name = self.element_combo.currentText()
        self.element_configs[name] = {
            "x_pv": self.pv_x_input.text(),
            "y_pv": self.pv_y_input.text(),
            "um_px_x": self.cal_x_spin.value(),
            "um_px_y": self.cal_y_spin.value(),
        }

    def _current_config(self):
        name = self.element_combo.currentText()
        return self.element_configs.get(name, {})

    # ── PV helpers ────────────────────────────────────────────────────────

    def _get_pv(self, pv: str) -> Optional[float]:
        try:
            r = subprocess.run(['caget', '-t', pv],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return float(r.stdout.strip())
        except Exception as e:
            self._log(f"caget {pv} failed: {e}")
        return None

    def _set_pv(self, pv: str, val) -> bool:
        try:
            r = subprocess.run(['caput', '-c', pv, str(val)],
                               capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except Exception as e:
            self._log(f"caput {pv} failed: {e}")
            return False

    def _move_relative(self, pv: str, delta_um: float) -> bool:
        cur = self._get_pv(f"{pv}.RBV")
        if cur is None:
            self._log(f"Cannot read {pv}.RBV")
            return False
        new = cur + delta_um
        self._log(f"Move {pv}: {cur:.4f} → {new:.4f} (Δ{delta_um:+.4f} µm)")
        return self._set_pv(pv, new)

    # ── Image access ─────────────────────────────────────────────────────

    def _get_image(self) -> Optional[np.ndarray]:
        p = self.parent()
        if p and hasattr(p, 'image_view'):
            item = p.image_view.getImageItem()
            if item is not None and item.image is not None:
                return item.image.astype(np.float64)
        return None

    def _image_center(self, img: np.ndarray) -> Tuple[float, float]:
        """Return (cx, cy) = center of image in data coords.
        col-major: shape[0] = x extent, shape[1] = y extent."""
        return img.shape[0] / 2.0, img.shape[1] / 2.0

    # ── Threshold helpers ────────────────────────────────────────────────

    def _get_threshold(self, img: np.ndarray) -> float:
        if self.thresh_mode.currentIndex() == 1:
            # Manual: percentage of (max - min)
            vmin, vmax = float(img.min()), float(img.max())
            return vmin + (vmax - vmin) * self.thresh_spin.value() / 100.0
        return self._otsu(img)

    @staticmethod
    def _otsu(img: np.ndarray) -> float:
        """Otsu's threshold (numpy-only)."""
        flat = img.ravel()
        nbins = 256
        lo, hi = float(flat.min()), float(flat.max())
        if hi - lo < 1e-9:
            return lo
        counts, edges = np.histogram(flat, bins=nbins, range=(lo, hi))
        centres = (edges[:-1] + edges[1:]) / 2.0
        total = counts.sum()
        if total == 0:
            return lo
        sum_all = (counts * centres).sum()
        w0, sum0, best_t, best_var = 0.0, 0.0, lo, 0.0
        for i in range(nbins):
            w0 += counts[i]
            if w0 == 0:
                continue
            w1 = total - w0
            if w1 == 0:
                break
            sum0 += counts[i] * centres[i]
            m0 = sum0 / w0
            m1 = (sum_all - sum0) / w1
            var = w0 * w1 * (m0 - m1) ** 2
            if var > best_var:
                best_var = var
                best_t = centres[i]
        return best_t

    # ── Detection algorithms ─────────────────────────────────────────────

    def _detect(self, img: np.ndarray) -> Optional[Tuple[float, float]]:
        element = self.element_combo.currentText()
        if element == "Pinhole":
            return self._detect_pinhole(img)
        elif element == "Condenser":
            return self._detect_condenser(img)
        elif element == "Zone Plate":
            return self._detect_zone_plate(img)
        return None

    def _detect_pinhole(self, img: np.ndarray) -> Optional[Tuple[float, float]]:
        """Small bright spot — threshold + center of mass."""
        thresh = self._get_threshold(img)
        mask = img > thresh
        pts = np.where(mask)
        if len(pts[0]) < 5:
            self._log("Pinhole: not enough bright pixels")
            return None
        cx = float(np.mean(pts[0]))
        cy = float(np.mean(pts[1]))
        self._log(f"Pinhole detected: ({cx:.1f}, {cy:.1f})  "
                  f"[{len(pts[0])} px above threshold {thresh:.0f}]")
        return cx, cy

    def _detect_condenser(self, img: np.ndarray) -> Optional[Tuple[float, float]]:
        """Large bright circle — threshold + largest blob center of mass."""
        thresh = self._get_threshold(img)
        mask = img > thresh

        if HAS_SCIPY:
            labeled, n = ndimage_label(mask)
            if n == 0:
                self._log("Condenser: no regions found")
                return None
            # Find largest component
            best_label, best_size = 1, 0
            for lbl in range(1, n + 1):
                sz = int(np.sum(labeled == lbl))
                if sz > best_size:
                    best_size = sz
                    best_label = lbl
            pts = np.where(labeled == best_label)
        else:
            pts = np.where(mask)

        if len(pts[0]) < 20:
            self._log("Condenser: not enough bright pixels")
            return None
        cx = float(np.mean(pts[0]))
        cy = float(np.mean(pts[1]))
        self._log(f"Condenser detected: ({cx:.1f}, {cy:.1f})  "
                  f"[{len(pts[0])} px]")
        return cx, cy

    def _detect_zone_plate(self, img: np.ndarray) -> Optional[Tuple[float, float]]:
        """Circular diffraction ring — edge detection + circle fit.
        Ignores the bright square inside by fitting a circle to edge pixels."""
        # Smooth to reduce noise
        if HAS_SCIPY:
            smooth = gaussian_filter(img, sigma=3)
        else:
            k = 7
            kernel = np.ones(k) / k
            smooth = img.copy()
            for ax in range(2):
                smooth = np.apply_along_axis(
                    lambda row: np.convolve(row, kernel, mode='same'),
                    ax, smooth)

        # Edge detection via gradient magnitude
        gy = np.diff(smooth, axis=0, prepend=smooth[:1, :])
        gx = np.diff(smooth, axis=1, prepend=smooth[:, :1])
        grad = np.sqrt(gx ** 2 + gy ** 2)

        # Threshold edges
        edge_thresh = self._otsu(grad)
        edge_mask = grad > edge_thresh

        pts_x, pts_y = np.where(edge_mask)
        if len(pts_x) < 50:
            self._log("Zone plate: not enough edge pixels")
            return None

        # Algebraic circle fit (Kasa method)
        # Minimize: (x - cx)^2 + (y - cy)^2 = r^2
        # Linearize: 2*cx*x + 2*cy*y + (r^2 - cx^2 - cy^2) = x^2 + y^2
        cx, cy, r = self._fit_circle(pts_x.astype(float), pts_y.astype(float))
        if r is None:
            self._log("Zone plate: circle fit failed")
            return None

        # Reject outliers and refit for robustness
        dist = np.sqrt((pts_x - cx) ** 2 + (pts_y - cy) ** 2)
        inliers = np.abs(dist - r) < 0.3 * r  # within 30% of radius
        if np.sum(inliers) < 30:
            self._log("Zone plate: too few inliers after filtering")
            return None

        cx, cy, r = self._fit_circle(pts_x[inliers].astype(float),
                                      pts_y[inliers].astype(float))
        if r is None:
            return None

        self._log(f"Zone plate detected: ({cx:.1f}, {cy:.1f})  "
                  f"radius={r:.1f} px  [{np.sum(inliers)} edge px]")
        return cx, cy

    @staticmethod
    def _fit_circle(x: np.ndarray, y: np.ndarray
                    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Kasa algebraic circle fit.  Returns (cx, cy, r) or (None,None,None)."""
        n = len(x)
        if n < 3:
            return None, None, None
        A = np.column_stack([x, y, np.ones(n)])
        b = x ** 2 + y ** 2
        try:
            result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            return None, None, None
        cx = result[0] / 2.0
        cy = result[1] / 2.0
        r_sq = result[2] + cx ** 2 + cy ** 2
        if r_sq <= 0:
            return None, None, None
        return cx, cy, math.sqrt(r_sq)

    # ── Target and offset computation ────────────────────────────────────

    def _get_target(self, img: np.ndarray) -> Tuple[float, float]:
        tx = self.target_x_spin.value()
        ty = self.target_y_spin.value()
        if tx == 0 and ty == 0:
            return self._image_center(img)
        return float(tx), float(ty)

    def _compute_offset(self, detected, target):
        dx = target[0] - detected[0]
        dy = target[1] - detected[1]
        return dx, dy

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_detect(self):
        img = self._get_image()
        if img is None:
            self._log("No image available")
            return
        detected = self._detect(img)
        if detected is None:
            self.last_detection = None
            self.lbl_detected.setText("not found")
            self.lbl_offset_px.setText("—")
            self.lbl_offset_um.setText("—")
            return
        self.last_detection = detected
        target = self._get_target(img)
        dx, dy = self._compute_offset(detected, target)
        cfg = self._current_config()
        dx_um = dx * cfg.get("um_px_x", 1.0)
        dy_um = dy * cfg.get("um_px_y", 1.0)

        self.lbl_detected.setText(f"({detected[0]:.1f}, {detected[1]:.1f})")
        self.lbl_target.setText(f"({target[0]:.1f}, {target[1]:.1f})")
        self.lbl_offset_px.setText(f"Δx={dx:.1f}  Δy={dy:.1f}  "
                                   f"dist={math.hypot(dx, dy):.1f}")
        self.lbl_offset_um.setText(f"Δx={dx_um:.2f}  Δy={dy_um:.2f} µm")
        self._draw_overlay(detected, target)

    def _on_center(self):
        img = self._get_image()
        if img is None:
            self._log("No image available")
            return

        # Detect if needed
        if self.last_detection is None:
            self._on_detect()
        if self.last_detection is None:
            self._log("Cannot center: detection failed")
            return

        target = self._get_target(img)
        dx, dy = self._compute_offset(self.last_detection, target)
        cfg = self._current_config()
        dx_um = dx * cfg.get("um_px_x", 1.0)
        dy_um = dy * cfg.get("um_px_y", 1.0)

        x_pv = cfg.get("x_pv", "")
        y_pv = cfg.get("y_pv", "")
        if not x_pv or not y_pv:
            self._log("Motor PVs not configured")
            return

        self._log(f"Moving: Δx={dx_um:+.3f} µm  Δy={dy_um:+.3f} µm")
        ok_x = self._move_relative(x_pv, dx_um)
        ok_y = self._move_relative(y_pv, dy_um)
        if ok_x and ok_y:
            self._log("Move complete")
        else:
            self._log("Move failed — check PVs")
        self.last_detection = None  # Force re-detect next time

    def _on_auto_center(self):
        self.is_centering = True
        self.iteration = 0
        self.btn_auto.setEnabled(False)
        self.btn_detect.setEnabled(False)
        self.btn_center.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._log("Auto centering started")
        self._auto_step()

    def _auto_step(self):
        if not self.is_centering:
            return

        self.iteration += 1
        max_iter = self.max_iter_spin.value()
        tol = self.tol_spin.value()

        self._log(f"--- Iteration {self.iteration}/{max_iter} ---")

        img = self._get_image()
        if img is None:
            self._log("No image — stopping")
            self._on_stop()
            return

        detected = self._detect(img)
        if detected is None:
            self._log("Detection failed — stopping")
            self._on_stop()
            return

        self.last_detection = detected
        target = self._get_target(img)
        dx, dy = self._compute_offset(detected, target)
        dist = math.hypot(dx, dy)

        self._log(f"Offset: {dist:.1f} px  (tol={tol:.1f})")

        if dist <= tol:
            self._log(f"Centered within tolerance ({dist:.1f} ≤ {tol:.1f} px)")
            self._on_detect()  # Update display
            self._on_stop()
            return

        if self.iteration >= max_iter:
            self._log(f"Max iterations reached (offset={dist:.1f} px)")
            self._on_detect()
            self._on_stop()
            return

        # Move
        cfg = self._current_config()
        dx_um = dx * cfg.get("um_px_x", 1.0)
        dy_um = dy * cfg.get("um_px_y", 1.0)
        x_pv = cfg.get("x_pv", "")
        y_pv = cfg.get("y_pv", "")

        if not x_pv or not y_pv:
            self._log("Motor PVs not configured — stopping")
            self._on_stop()
            return

        self._move_relative(x_pv, dx_um)
        self._move_relative(y_pv, dy_um)

        # Wait for settle then repeat
        settle_ms = int(self.settle_spin.value() * 1000)
        QtCore.QTimer.singleShot(settle_ms, self._auto_step)

    def _on_stop(self):
        self.is_centering = False
        self.btn_auto.setEnabled(True)
        self.btn_detect.setEnabled(True)
        self.btn_center.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._log("Stopped")

    # ── Overlay ──────────────────────────────────────────────────────────

    def _draw_overlay(self, detected, target):
        self._clear_overlay()
        p = self.parent()
        if not p or not hasattr(p, 'image_view'):
            return
        iv = p.image_view

        # Detected center — red cross
        det_scatter = pg.ScatterPlotItem(
            [detected[0]], [detected[1]],
            pen=pg.mkPen('r', width=2), brush=None, size=15, symbol='+')
        iv.addItem(det_scatter)
        self.overlay_items.append(det_scatter)

        # Target — green circle
        tgt_scatter = pg.ScatterPlotItem(
            [target[0]], [target[1]],
            pen=pg.mkPen('g', width=2), brush=None, size=15, symbol='o')
        iv.addItem(tgt_scatter)
        self.overlay_items.append(tgt_scatter)

        # Crosshair at detected position
        vline = pg.InfiniteLine(pos=detected[0], angle=90,
                                pen=pg.mkPen('r', width=1, style=QtCore.Qt.DashLine))
        hline = pg.InfiniteLine(pos=detected[1], angle=0,
                                pen=pg.mkPen('r', width=1, style=QtCore.Qt.DashLine))
        iv.addItem(vline)
        iv.addItem(hline)
        self.overlay_items.extend([vline, hline])

    def _clear_overlay(self):
        p = self.parent()
        if p and hasattr(p, 'image_view'):
            iv = p.image_view
            for item in self.overlay_items:
                try:
                    iv.removeItem(item)
                except Exception:
                    pass
        self.overlay_items.clear()

    # ── Logging ──────────────────────────────────────────────────────────

    def _log(self, msg: str):
        import time
        ts = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        if self.logger:
            self.logger.info(f"AutoCenter: {msg}")

    # ── Cleanup ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self.is_centering = False
        self._clear_overlay()
        event.accept()
