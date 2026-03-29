"""
Detector Control Plugin for bl32ID

Controls detector binning and ROI by:
- Setting BinX/BinY which automatically updates SizeX/SizeY
- Drawing an ROI on the image that sets CropLeft/Right/Top/Bottom and applies via Crop PV
"""

import subprocess
import logging
from typing import Optional
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore


class DetectorControlDialog(QtWidgets.QDialog):
    """Dialog for controlling detector binning and ROI."""

    BUTTON_TEXT = "Detector"
    HANDLER_TYPE = 'singleton'  # Keep one instance, show/hide it

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Detector Control - bl32ID")
        self.resize(500, 600)

        self.roi = None
        self.roi_enabled = False
        self._last_image = None
        self._max_sizex = None
        self._max_sizey = None

        self._init_ui()
        self._load_current_values()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Title
        title = QtWidgets.QLabel("Detector Control")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        desc = QtWidgets.QLabel(
            "Control detector binning and ROI for 32idbSP1:cam1"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # PV Prefix setting
        prefix_group = QtWidgets.QGroupBox("PV Configuration")
        prefix_layout = QtWidgets.QFormLayout()

        self.pv_prefix_input = QtWidgets.QLineEdit("32idbSP1:cam1")
        prefix_layout.addRow("Camera PV Prefix:", self.pv_prefix_input)

        self.crop_prefix_input = QtWidgets.QLineEdit("32id:TXMOptics")
        prefix_layout.addRow("Crop PV Prefix:", self.crop_prefix_input)

        self.vertical_flip_check = QtWidgets.QCheckBox("Vertical Flip (swap top/bottom)")
        prefix_layout.addRow("Image Orientation:", self.vertical_flip_check)

        prefix_group.setLayout(prefix_layout)
        layout.addWidget(prefix_group)

        # Binning section
        binning_group = QtWidgets.QGroupBox("Binning Control")
        binning_layout = QtWidgets.QFormLayout()

        self.binx_spin = QtWidgets.QSpinBox()
        self.binx_spin.setRange(1, 16)
        self.binx_spin.setValue(1)
        binning_layout.addRow("BinX:", self.binx_spin)

        self.biny_spin = QtWidgets.QSpinBox()
        self.biny_spin.setRange(1, 16)
        self.biny_spin.setValue(1)
        binning_layout.addRow("BinY:", self.biny_spin)

        self.sizex_spin = QtWidgets.QSpinBox()
        self.sizex_spin.setRange(1, 8192)
        self.sizex_spin.setValue(2048)
        self.sizex_spin.setReadOnly(True)
        binning_layout.addRow("SizeX (computed):", self.sizex_spin)

        self.sizey_spin = QtWidgets.QSpinBox()
        self.sizey_spin.setRange(1, 8192)
        self.sizey_spin.setValue(2048)
        self.sizey_spin.setReadOnly(True)
        binning_layout.addRow("SizeY (computed):", self.sizey_spin)

        bin_button_layout = QtWidgets.QHBoxLayout()
        self.binx_spin.valueChanged.connect(self._refresh_computed_sizes)
        self.biny_spin.valueChanged.connect(self._refresh_computed_sizes)

        self.apply_binning_btn = QtWidgets.QPushButton("Apply Binning")
        self.apply_binning_btn.clicked.connect(self._apply_binning)
        bin_button_layout.addWidget(self.apply_binning_btn)

        self.read_binning_btn = QtWidgets.QPushButton("Read Current")
        self.read_binning_btn.clicked.connect(self._read_binning)
        bin_button_layout.addWidget(self.read_binning_btn)

        binning_layout.addRow(bin_button_layout)

        binning_group.setLayout(binning_layout)
        layout.addWidget(binning_group)

        # ROI section
        roi_group = QtWidgets.QGroupBox("ROI Control")
        roi_layout = QtWidgets.QVBoxLayout()

        roi_desc = QtWidgets.QLabel(
            "Draw an ROI on the image to set detector region.\n"
            "ROI sets CropLeft, CropRight, CropTop, CropBottom and applies via Crop PV."
        )
        roi_desc.setWordWrap(True)
        roi_layout.addWidget(roi_desc)

        # ROI toggle and buttons
        roi_button_layout = QtWidgets.QHBoxLayout()

        self.roi_toggle_btn = QtWidgets.QPushButton("Enable ROI Drawing")
        self.roi_toggle_btn.setCheckable(True)
        self.roi_toggle_btn.clicked.connect(self._toggle_roi)
        roi_button_layout.addWidget(self.roi_toggle_btn)

        self.roi_reset_btn = QtWidgets.QPushButton("Reset ROI")
        self.roi_reset_btn.clicked.connect(self._reset_roi)
        self.roi_reset_btn.setEnabled(False)
        roi_button_layout.addWidget(self.roi_reset_btn)

        roi_layout.addLayout(roi_button_layout)

        # ROI apply button
        roi_apply_layout = QtWidgets.QHBoxLayout()

        self.apply_roi_btn = QtWidgets.QPushButton("Apply ROI to Detector")
        self.apply_roi_btn.clicked.connect(self._apply_roi)
        self.apply_roi_btn.setEnabled(False)
        roi_apply_layout.addWidget(self.apply_roi_btn)

        self.remove_roi_btn = QtWidgets.QPushButton("Remove ROI (Full Frame)")
        self.remove_roi_btn.clicked.connect(self._remove_roi)
        roi_apply_layout.addWidget(self.remove_roi_btn)

        self.read_roi_btn = QtWidgets.QPushButton("Read Current ROI")
        self.read_roi_btn.clicked.connect(self._read_roi)
        roi_apply_layout.addWidget(self.read_roi_btn)

        roi_layout.addLayout(roi_apply_layout)

        # Current ROI display
        self.roi_info_label = QtWidgets.QLabel("Current ROI: Not set")
        self.roi_info_label.setStyleSheet("padding: 5px; background: #f0f0f0;")
        roi_layout.addWidget(self.roi_info_label)

        roi_group.setLayout(roi_layout)
        layout.addWidget(roi_group)

        # Status/Log section
        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Bottom buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def _log_message(self, message: str):
        """Add a message to the log with timestamp."""
        import time
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def _get_pv_value(self, pv_name: str) -> Optional[str]:
        """Get PV value using caget."""
        try:
            result = subprocess.run(
                ['caget', '-t', pv_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                self._log_message(f"Failed to get PV {pv_name}: {result.stderr}")
                return None
        except Exception as e:
            self._log_message(f"Error getting PV {pv_name}: {e}")
            return None

    def _set_pv_value(self, pv_name: str, value) -> bool:
        """Set PV value using caput with -c flag to wait for callback.

        Args:
            pv_name: PV name to set
            value: Value to set
        """
        try:
            # Use caput -c to wait for callback completion
            # This ensures the value is processed before returning
            result = subprocess.run(
                ['caput', '-c', pv_name, str(value)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True
            else:
                self._log_message(f"Failed to set PV {pv_name}: {result.stderr}")
                return False
        except Exception as e:
            self._log_message(f"Error setting PV {pv_name}: {e}")
            return False

    def _load_current_values(self):
        """Load current binning and ROI values from PVs."""
        self._read_binning()
        self._read_roi()

    def _read_binning(self):
        """Read current binning from detector and store max sensor size."""
        prefix = self.pv_prefix_input.text()

        binx_val  = self._get_pv_value(f"{prefix}:BinX")
        biny_val  = self._get_pv_value(f"{prefix}:BinY")
        max_x_val = self._get_pv_value(f"{prefix}:MaxSizeX_RBV")
        max_y_val = self._get_pv_value(f"{prefix}:MaxSizeY_RBV")

        if binx_val:
            self.binx_spin.setValue(int(binx_val))
        if biny_val:
            self.biny_spin.setValue(int(biny_val))
        # MaxSizeX/Y_RBV is in binned units — recover unbinned sensor size
        if max_x_val and binx_val:
            self._max_sizex = int(max_x_val) * int(binx_val)
        if max_y_val and biny_val:
            self._max_sizey = int(max_y_val) * int(biny_val)

        self._refresh_computed_sizes()
        self._log_message(f"Read: BinX={binx_val}, BinY={biny_val}, MaxSizeX={max_x_val}, MaxSizeY={max_y_val}")

    def _refresh_computed_sizes(self):
        """Recompute SizeX/SizeY from max sensor size and current binning."""
        if self._max_sizex is None or self._max_sizey is None:
            return
        self.sizex_spin.setValue(self._max_sizex // self.binx_spin.value())
        self.sizey_spin.setValue(self._max_sizey // self.biny_spin.value())

    def _apply_binning(self):
        """Apply binning values to detector, computing SizeX/SizeY from max sensor size."""
        prefix = self.pv_prefix_input.text()
        binx = self.binx_spin.value()
        biny = self.biny_spin.value()

        if self._max_sizex is None or self._max_sizey is None:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Max sensor size not available. Click 'Read Current' first."
            )
            return

        sizex = self._max_sizex // binx
        sizey = self._max_sizey // biny

        success = True
        if not self._set_pv_value(f"{prefix}:BinX", binx):
            success = False
        if not self._set_pv_value(f"{prefix}:BinY", biny):
            success = False
        if not self._set_pv_value(f"{prefix}:SizeX", sizex):
            success = False
        if not self._set_pv_value(f"{prefix}:SizeY", sizey):
            success = False

        if success:
            self.sizex_spin.setValue(sizex)
            self.sizey_spin.setValue(sizey)
            self._log_message(f"Applied: BinX={binx}, BinY={biny}, SizeX={sizex}, SizeY={sizey}")
            QtWidgets.QMessageBox.information(
                self, "Success",
                f"Binning applied: BinX={binx}, BinY={biny}\nSizeX={sizex}, SizeY={sizey}"
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Failed to apply binning. Check log for details."
            )

    def _read_roi(self):
        """Read current ROI values from crop PVs."""
        crop_prefix = self.crop_prefix_input.text()

        crop_left = self._get_pv_value(f"{crop_prefix}:CropLeft")
        crop_right = self._get_pv_value(f"{crop_prefix}:CropRight")
        crop_top = self._get_pv_value(f"{crop_prefix}:CropTop")
        crop_bottom = self._get_pv_value(f"{crop_prefix}:CropBottom")

        if all([crop_left, crop_right, crop_top, crop_bottom]):
            self.roi_info_label.setText(
                f"Current Crop: Left={crop_left}, Right={crop_right}, "
                f"Top={crop_top}, Bottom={crop_bottom}"
            )
            self._log_message(f"Read Crop: Left={crop_left}, Right={crop_right}, Top={crop_top}, Bottom={crop_bottom}")

    # ── ROI drawing helpers (same pattern as plugins/roi.py) ─────────────

    def _gv(self):
        p = self.parent()
        if p and hasattr(p, 'image_view'):
            return p.image_view.ui.graphicsView
        return None

    def _sc(self):
        gv = self._gv()
        return gv.scene() if gv else None

    def _install_filter(self):
        gv = self._gv()
        if gv and not hasattr(self, '_vp_filter'):
            self._vp_filter = _DetectorRoiFilter(self)
            gv.viewport().installEventFilter(self._vp_filter)

    def _uninstall_filter(self):
        gv = self._gv()
        if gv and hasattr(self, '_vp_filter'):
            gv.viewport().removeEventFilter(self._vp_filter)
            del self._vp_filter

    def _set_crosshair(self, on: bool):
        gv = self._gv()
        if gv:
            gv.viewport().setCursor(
                QtCore.Qt.CrossCursor if on else QtCore.Qt.ArrowCursor)

    # ── toggle ────────────────────────────────────────────────────────────

    def _toggle_roi(self, checked: bool):
        self.roi_enabled = checked
        if checked:
            self.roi_toggle_btn.setText("Disable ROI Drawing")
            self.roi_reset_btn.setEnabled(True)
            self.apply_roi_btn.setEnabled(True)
            self._roi_state = 'idle'
            self._roi_press_scene = None
            self._roi_preview = None
            self._install_filter()
            self._set_crosshair(True)
            self._log_message("ROI: click and drag to draw")
        else:
            self.roi_toggle_btn.setText("Enable ROI Drawing")
            self._roi_erase()
            self._uninstall_filter()
            self._set_crosshair(False)
            self.roi_reset_btn.setEnabled(False)
            self.apply_roi_btn.setEnabled(False)
            self._log_message("ROI drawing disabled")

    # ── mouse events (called by _DetectorRoiFilter) ───────────────────────

    def _roi_on_press(self, vp_pos) -> bool:
        if not self.roi_enabled or getattr(self, '_roi_state', 'idle') != 'idle':
            return False
        gv = self._gv()
        sc = self._sc()
        if gv is None or sc is None:
            return False
        sp = gv.mapToScene(vp_pos)
        self._roi_press_scene = sp
        pen = pg.mkPen('r', width=2)
        pen.setCosmetic(True)
        self._roi_preview = QtWidgets.QGraphicsRectItem(sp.x(), sp.y(), 0, 0)
        self._roi_preview.setPen(pen)
        self._roi_preview.setZValue(1000)
        sc.addItem(self._roi_preview)
        self._roi_state = 'placing'
        return True

    def _roi_on_move(self, vp_pos) -> bool:
        if getattr(self, '_roi_state', 'idle') != 'placing' or self._roi_preview is None:
            return False
        gv = self._gv()
        if gv is None:
            return False
        sp = gv.mapToScene(vp_pos)
        p0 = self._roi_press_scene
        x = min(p0.x(), sp.x())
        y = min(p0.y(), sp.y())
        w = max(1.0, abs(sp.x() - p0.x()))
        h = max(1.0, abs(sp.y() - p0.y()))
        self._roi_preview.setRect(x, y, w, h)
        return True

    def _roi_on_release(self, vp_pos) -> bool:
        if getattr(self, '_roi_state', 'idle') != 'placing':
            return False
        gv = self._gv()
        sc = self._sc()
        if gv is None:
            return False
        sp = gv.mapToScene(vp_pos)

        # remove preview
        if sc and self._roi_preview:
            sc.removeItem(self._roi_preview)
        self._roi_preview = None

        p0 = self._roi_press_scene
        x = min(p0.x(), sp.x())
        y = min(p0.y(), sp.y())
        w = max(1.0, abs(sp.x() - p0.x()))
        h = max(1.0, abs(sp.y() - p0.y()))

        self._roi_build(x, y, w, h)
        self._roi_state = 'placed'
        self._set_crosshair(False)
        return True

    # ── build / erase ROI ─────────────────────────────────────────────────

    def _roi_erase(self):
        sc = self._sc()
        if self.roi is not None:
            try:
                self.roi.sigRegionChanged.disconnect(self._on_roi_changed)
            except Exception:
                pass
            if sc:
                try:
                    sc.removeItem(self.roi)
                except Exception:
                    pass
            self.roi = None
        if getattr(self, '_roi_preview', None) is not None and sc:
            try:
                sc.removeItem(self._roi_preview)
            except Exception:
                pass
            self._roi_preview = None

    def _roi_build(self, x, y, w, h):
        sc = self._sc()
        if sc is None:
            return
        self._roi_erase()

        pen       = pg.mkPen('r', width=2)
        hover_pen = pg.mkPen((255, 100, 100), width=3)
        self.roi = pg.RectROI([0, 0], [w, h],
                              pen=pen, hoverPen=hover_pen,
                              movable=True, resizable=True, removable=False)
        self.roi.setZValue(1000)
        sc.addItem(self.roi)
        self.roi.setPos(x, y)

        # 4 corners + 4 edges
        self.roi.addScaleHandle([1, 1], [0, 0])
        self.roi.addScaleHandle([0, 0], [1, 1])
        self.roi.addScaleHandle([1, 0], [0, 1])
        self.roi.addScaleHandle([0, 1], [1, 0])
        self.roi.addScaleHandle([0.5, 0],   [0.5, 1])
        self.roi.addScaleHandle([0.5, 1],   [0.5, 0])
        self.roi.addScaleHandle([0,   0.5], [1,   0.5])
        self.roi.addScaleHandle([1,   0.5], [0,   0.5])

        self.roi.sigRegionChanged.connect(self._on_roi_changed)
        self.roi.setVisible(True)
        self._on_roi_changed()
        self._log_message(f"ROI placed at scene ({x:.0f},{y:.0f}) size ({w:.0f}×{h:.0f})")

    # ── reset ────────────────────────────────────────────────────────────

    def _reset_roi(self):
        p = self.parent()
        if not p or not hasattr(p, 'image_view'):
            return
        iv  = p.image_view
        img = iv.getImageItem()
        if img is None or img.image is None:
            return
        gv  = iv.ui.graphicsView
        sc  = gv.scene()
        if sc is None:
            return
        h, w = img.image.shape[:2]
        rw = max(10, w // 2)
        rh = max(10, h // 2)
        rx = (w - rw) // 2
        ry = (h - rh) // 2
        # map image pixels → scene coords, exactly as plugins/roi.py does
        p1 = img.mapToScene(QtCore.QPointF(rx, ry))
        p2 = img.mapToScene(QtCore.QPointF(rx + rw, ry + rh))
        sx = min(p1.x(), p2.x())
        sy = min(p1.y(), p2.y())
        sw = abs(p2.x() - p1.x())
        sh = abs(p2.y() - p1.y())
        self._roi_build(sx, sy, sw, sh)
        self._roi_state = 'placed'
        self._set_crosshair(False)

    # ── ROI changed callback ──────────────────────────────────────────────

    def _scene_roi_fracs(self, img_item):
        """Return (cf0, cf1, rf0, rf1) — fractions of the image's local
        bounding rect [0..1] covered by the current ROI in scene space.
        cf = fraction along local x-axis (first array dimension),
        rf = fraction along local y-axis (second array dimension).
        Works regardless of ViewBox Y-inversion or zoom level."""
        if self.roi is None or img_item is None:
            return None
        br   = img_item.boundingRect()
        p_tl = img_item.mapToScene(br.topLeft())
        p_br = img_item.mapToScene(br.bottomRight())
        sc_dx = p_br.x() - p_tl.x()
        sc_dy = p_br.y() - p_tl.y()
        if abs(sc_dx) < 1e-6 or abs(sc_dy) < 1e-6:
            return None
        pos  = self.roi.pos()
        size = self.roi.size()
        cf0_raw = (pos[0]           - p_tl.x()) / sc_dx
        cf1_raw = (pos[0] + size[0] - p_tl.x()) / sc_dx
        rf0_raw = (pos[1]           - p_tl.y()) / sc_dy
        rf1_raw = (pos[1] + size[1] - p_tl.y()) / sc_dy
        cf0 = max(0.0, min(1.0, min(cf0_raw, cf1_raw)))
        cf1 = max(0.0, min(1.0, max(cf0_raw, cf1_raw)))
        rf0 = max(0.0, min(1.0, min(rf0_raw, rf1_raw)))
        rf1 = max(0.0, min(1.0, max(rf0_raw, rf1_raw)))
        return cf0, cf1, rf0, rf1

    def _fracs_to_sensor(self, cf0, cf1, rf0, rf1):
        """Convert image-local fracs → sensor pixel box (sx, sy, sw, sh).
        Undoes pystream display transforms (transpose / flip_h / flip_v).
        With transpose=True: local x-axis = sensor columns, y-axis = sensor rows.
        With transpose=False: local x-axis = sensor rows,   y-axis = sensor cols."""
        viewer    = self.parent()
        flip_h    = getattr(viewer, 'flip_h',        False)
        flip_v    = getattr(viewer, 'flip_v',        False)
        do_transp = getattr(viewer, 'transpose_img', False)
        sensor_w  = self._max_sizex
        sensor_h  = self._max_sizey
        if not sensor_w or not sensor_h:
            return None

        # undo flip_v (flips local y-axis)
        if flip_v:
            rf0, rf1 = 1.0 - rf1, 1.0 - rf0
        # undo flip_h (flips local x-axis)
        if flip_h:
            cf0, cf1 = 1.0 - cf1, 1.0 - cf0

        if do_transp:
            # local x → sensor col, local y → sensor row
            col0_f, col1_f = cf0, cf1
            row0_f, row1_f = rf0, rf1
        else:
            # local x → sensor row, local y → sensor col — swap axes
            col0_f, col1_f = rf0, rf1
            row0_f, row1_f = cf0, cf1

        sx  = int(col0_f * sensor_w)
        sx1 = int(col1_f * sensor_w)
        sy  = int(row0_f * sensor_h)
        sy1 = int(row1_f * sensor_h)
        return sx, sy, max(1, sx1 - sx), max(1, sy1 - sy)

    def _on_roi_changed(self):
        if self.roi is None:
            return
        p = self.parent()
        if p and hasattr(p, 'image_view'):
            img_item = p.image_view.getImageItem()
            fracs = self._scene_roi_fracs(img_item)
            if fracs is not None and self._max_sizex and self._max_sizey:
                result = self._fracs_to_sensor(*fracs)
                if result:
                    sx, sy, sw, sh = result
                    self.roi_info_label.setText(
                        f"ROI  x={sx}  y={sy}  w={sw}  h={sh}  (sensor px)")
                    return
        pos  = self.roi.pos()
        size = self.roi.size()
        self.roi_info_label.setText(
            f"ROI  pos ({pos[0]:.0f}, {pos[1]:.0f})  size {size[0]:.0f}×{size[1]:.0f}")

    # ── apply ROI to PVs ─────────────────────────────────────────────────

    def _apply_roi(self):
        if not self.roi:
            QtWidgets.QMessageBox.warning(self, "No ROI",
                "Please draw an ROI first.")
            return

        p = self.parent()
        if not p or not hasattr(p, 'image_view'):
            QtWidgets.QMessageBox.warning(self, "Error", "Cannot access image view.")
            return

        iv       = p.image_view
        img_item = iv.getImageItem()
        if img_item is None or img_item.image is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No image available.")
            return

        # ── Compute ROI fractions from scene space ───────────────────────
        # Uses mapToScene on image corners — independent of display resolution,
        # so it works even when the displayed image is tiny due to existing crop.
        fracs = self._scene_roi_fracs(img_item)
        if fracs is None:
            self._log_message("Cannot compute ROI — image has zero extent")
            return
        cf0, cf1, rf0, rf1 = fracs

        sensor_w = self._max_sizex
        sensor_h = self._max_sizey
        if not sensor_w or not sensor_h:
            QtWidgets.QMessageBox.warning(self, "Error",
                "Sensor size unknown. Click 'Read Current' first.")
            return

        # ── Convert fractions → sensor pixel ROI ─────────────────────────
        result = self._fracs_to_sensor(cf0, cf1, rf0, rf1)
        if result is None:
            return
        sx, sy, sw, sh = result
        sx1 = sx + sw
        sy1 = sy + sh

        # Vertical flip checkbox: tick if sensor hardware row 0 is at bottom
        if self.vertical_flip_check.isChecked():
            sy  = sensor_h - sy1
            sy1 = sy + sh

        # Crop = pixels removed from each border
        crop_left   = sx
        crop_right  = sensor_w - sx1
        crop_top    = sy
        crop_bottom = sensor_h - sy1

        self._log_message(
            f"Fracs: col=[{cf0:.3f},{cf1:.3f}] row=[{rf0:.3f},{rf1:.3f}]"
        )
        self._log_message(
            f"Sensor ROI: x={sx} y={sy} w={sw} h={sh} "
            f"(sensor {sensor_w}×{sensor_h})"
        )
        self._log_message(
            f"Crop: L={crop_left} R={crop_right} T={crop_top} B={crop_bottom}"
        )

        crop_prefix = self.crop_prefix_input.text()
        success = True
        for pv, val in [
            (f"{crop_prefix}:CropLeft",   crop_left),
            (f"{crop_prefix}:CropRight",  crop_right),
            (f"{crop_prefix}:CropTop",    crop_top),
            (f"{crop_prefix}:CropBottom", crop_bottom),
        ]:
            if not self._set_pv_value(pv, val):
                success = False

        if success:
            if not self._set_pv_value(f"{crop_prefix}:Crop", 1):
                success = False

        if success:
            self._log_message(
                f"Applied ROI: L={crop_left} R={crop_right} T={crop_top} B={crop_bottom}")
            QtWidgets.QMessageBox.information(
                self, "Success",
                f"ROI applied:\n"
                f"CropLeft={crop_left}  CropRight={crop_right}\n"
                f"CropTop={crop_top}  CropBottom={crop_bottom}\n"
                f"(sensor region: x={sx} y={sy} w={sw} h={sh})")
        else:
            QtWidgets.QMessageBox.warning(self, "Error",
                "Failed to apply ROI. Check log for details.")

    # ── remove ROI (full frame) ───────────────────────────────────────────

    def _remove_roi(self):
        prefix   = self.pv_prefix_input.text()
        max_sizex = self._get_pv_value(f"{prefix}:MaxSizeX_RBV")
        max_sizey = self._get_pv_value(f"{prefix}:MaxSizeY_RBV")
        if not max_sizex or not max_sizey:
            QtWidgets.QMessageBox.warning(self, "Error",
                "Could not read detector maximum size.")
            return
        success = all([
            self._set_pv_value(f"{prefix}:MinX", 0),
            self._set_pv_value(f"{prefix}:MinY", 0),
            self._set_pv_value(f"{prefix}:SizeX", max_sizex),
            self._set_pv_value(f"{prefix}:SizeY", max_sizey),
        ])
        if success:
            self._log_message(f"Reset to full frame {max_sizex}×{max_sizey}")
            QtWidgets.QMessageBox.information(self, "Success",
                f"Detector reset to full frame {max_sizex}×{max_sizey}")
            self._read_roi()
        else:
            QtWidgets.QMessageBox.warning(self, "Error",
                "Failed to remove ROI. Check log for details.")

    def closeEvent(self, event):
        self._roi_erase()
        self._uninstall_filter()
        event.accept()


class _DetectorRoiFilter(QtCore.QObject):
    """Viewport event filter — same pattern as plugins/roi.py _RoiVpFilter."""

    def __init__(self, dlg: DetectorControlDialog):
        super().__init__()
        self.dlg = dlg

    def eventFilter(self, _obj, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.LeftButton:
                return self.dlg._roi_on_press(event.pos())
        elif t == QtCore.QEvent.MouseMove:
            return self.dlg._roi_on_move(event.pos())
        elif t == QtCore.QEvent.MouseButtonRelease:
            if event.button() == QtCore.Qt.LeftButton:
                return self.dlg._roi_on_release(event.pos())
        return False
