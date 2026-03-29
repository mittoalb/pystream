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

    def _roi_to_sensor(self):
        """Convert scene-space ROI → sensor pixel box (sx, sy, sx1, sy1).

        mapSceneToView gives data coords that ARE pixel positions in the
        displayed numpy array.  Undo pystream flips/transpose to get sensor
        pixel positions.  No PV reads — fast enough for live drag updates.
        """
        p = self.parent()
        if self.roi is None or p is None or not hasattr(p, 'image_view'):
            return None
        iv       = p.image_view
        view     = iv.getView()
        img_item = iv.getImageItem()
        if img_item is None or img_item.image is None:
            return None

        # ── scene → data (pixel) coordinates ─────────────────────────────
        pos  = self.roi.pos()
        size = self.roi.size()
        d0 = view.mapSceneToView(QtCore.QPointF(pos[0], pos[1]))
        d1 = view.mapSceneToView(QtCore.QPointF(pos[0] + size[0],
                                                  pos[1] + size[1]))
        img_w = float(img_item.width())    # col-major: first axis
        img_h = float(img_item.height())   # col-major: second axis
        if img_w < 1 or img_h < 1:
            return None

        # sort & clamp to displayed image bounds
        px0 = max(0.0, min(img_w, min(d0.x(), d1.x())))
        px1 = max(0.0, min(img_w, max(d0.x(), d1.x())))
        py0 = max(0.0, min(img_h, min(d0.y(), d1.y())))
        py1 = max(0.0, min(img_h, max(d0.y(), d1.y())))

        # ── undo pystream display transforms ─────────────────────────────
        # pystream: transpose(swapaxes 0,1) → flip_h([:, ::-1]) → flip_v([::-1, :])
        # col-major: first axis = x on screen, second axis = y on screen
        viewer    = self.parent()
        flip_h    = getattr(viewer, 'flip_h',        False)
        flip_v    = getattr(viewer, 'flip_v',        False)

        # undo flip_v  (reverses first axis → x in col-major)
        if flip_v:
            px0, px1 = img_w - px1, img_w - px0
        # undo flip_h  (reverses second axis → y in col-major)
        if flip_h:
            py0, py1 = img_h - py1, img_h - py0

        # ── map display axes to sensor CropLeft/Right (sensor_w) and
        #    CropTop/Bottom (sensor_h) ────────────────────────────────────
        # Determine which display axis matches _max_sizex (sensor width).
        # This auto-detects the orientation regardless of transpose state.
        sensor_w = self._max_sizex or 0
        sensor_h = self._max_sizey or 0
        x_matches_w = abs(img_w - sensor_w) <= abs(img_h - sensor_w)

        if x_matches_w:
            # display x-axis = sensor width direction
            sx, sx1 = int(px0), int(px1)
            sy, sy1 = int(py0), int(py1)
            total_w = int(img_w)
            total_h = int(img_h)
        else:
            # display y-axis = sensor width direction
            sx, sx1 = int(py0), int(py1)
            sy, sy1 = int(px0), int(px1)
            total_w = int(img_h)
            total_h = int(img_w)

        return sx, sy, sx1, sy1, total_w, total_h

    def _on_roi_changed(self):
        if self.roi is None:
            return
        result = self._roi_to_sensor()
        if result is not None:
            sx, sy, sx1, sy1, total_w, total_h = result
            cl = sx
            cr = max(0, total_w - sx1)
            ct = sy
            cb = max(0, total_h - sy1)
            self.roi_info_label.setText(
                f"Crop L={cl} R={cr} T={ct} B={cb}  "
                f"(ROI {sx1-sx}×{sy1-sy})")
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

        result = self._roi_to_sensor()
        if result is None:
            QtWidgets.QMessageBox.warning(self, "Error",
                "Cannot compute ROI. Is an image displayed?")
            return

        sx, sy, sx1, sy1, sensor_w, sensor_h = result

        # Vertical flip checkbox
        if self.vertical_flip_check.isChecked():
            sy, sy1 = sensor_h - sy1, sensor_h - sy

        # Crop = distance from each border to the ROI edge
        crop_left   = max(0, sx)
        crop_right  = max(0, sensor_w - sx1)
        crop_top    = max(0, sy)
        crop_bottom = max(0, sensor_h - sy1)

        sw = sx1 - sx
        sh = sy1 - sy

        self._log_message(
            f"Crop: L={crop_left} R={crop_right} T={crop_top} B={crop_bottom}  "
            f"ROI {sw}×{sh}  image {sensor_w}×{sensor_h}"
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
                f"(ROI: {sw}×{sh} in {sensor_w}×{sensor_h})")
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
