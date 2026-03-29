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

    def _toggle_roi(self, checked: bool):
        """Toggle ROI drawing on the image."""
        self.roi_enabled = checked

        if checked:
            self.roi_toggle_btn.setText("Disable ROI Drawing")
            self._create_or_show_roi()
            self.roi_reset_btn.setEnabled(True)
            self.apply_roi_btn.setEnabled(True)
            self._log_message("ROI drawing enabled")
        else:
            self.roi_toggle_btn.setText("Enable ROI Drawing")
            if self.roi:
                self.roi.setVisible(False)
            self.roi_reset_btn.setEnabled(False)
            self.apply_roi_btn.setEnabled(False)
            self._log_message("ROI drawing disabled")

    def _get_scene(self):
        parent_viewer = self.parent()
        if parent_viewer and hasattr(parent_viewer, 'image_view'):
            return parent_viewer.image_view.ui.graphicsView.scene()
        return None

    def _create_or_show_roi(self):
        """Create or show the ROI on the image."""
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            self._log_message("Error: Cannot access image view")
            return

        image_view = parent_viewer.image_view

        if self.roi is None:
            image_item = image_view.getImageItem()
            if image_item is None or image_item.image is None:
                self._log_message("Error: No image available")
                return

            sc = image_view.ui.graphicsView.scene()
            if sc is None:
                return

            image = image_item.image
            h, w = image.shape[:2]
            rw = max(10, w // 2)
            rh = max(10, h // 2)
            rx = (w - rw) // 2
            ry = (h - rh) // 2

            # Convert image-pixel coords to scene coords so the ROI
            # appears at the correct position regardless of y-axis orientation.
            p_tl = image_item.mapToScene(QtCore.QPointF(rx, ry))
            p_br = image_item.mapToScene(QtCore.QPointF(rx + rw, ry + rh))
            sx = min(p_tl.x(), p_br.x())
            sy = min(p_tl.y(), p_br.y())
            sw = abs(p_br.x() - p_tl.x())
            sh = abs(p_br.y() - p_tl.y())

            self.roi = pg.ROI([0, 0], [sw, sh], pen='r')
            self.roi.addScaleHandle([1, 1], [0, 0])
            self.roi.addScaleHandle([0, 0], [1, 1])
            self.roi.addScaleHandle([1, 0], [0, 1])
            self.roi.addScaleHandle([0, 1], [1, 0])
            self.roi.setZValue(1000)
            sc.addItem(self.roi)
            self.roi.setPos(sx, sy)
            self.roi.sigRegionChanged.connect(self._on_roi_changed)
            self._log_message(f"ROI created at image ({rx},{ry}) size ({rw},{rh})")
        else:
            self.roi.setVisible(True)

    def _reset_roi(self):
        """Reset ROI to center of image."""
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            return

        image_view = parent_viewer.image_view
        image_item = image_view.getImageItem()
        if image_item is not None and image_item.image is not None and self.roi:
            image = image_item.image
            h, w = image.shape[:2]
            rw = max(10, w // 2)
            rh = max(10, h // 2)
            rx = (w - rw) // 2
            ry = (h - rh) // 2

            p_tl = image_item.mapToScene(QtCore.QPointF(rx, ry))
            p_br = image_item.mapToScene(QtCore.QPointF(rx + rw, ry + rh))
            sx = min(p_tl.x(), p_br.x())
            sy = min(p_tl.y(), p_br.y())
            sw = abs(p_br.x() - p_tl.x())
            sh = abs(p_br.y() - p_tl.y())

            self.roi.setPos([sx, sy])
            self.roi.setSize([sw, sh])
            self._log_message(f"ROI reset to image ({rx},{ry}) size ({rw},{rh})")

    def _on_roi_changed(self):
        """Called when ROI is moved or resized."""
        if self.roi:
            pos = self.roi.pos()
            size = self.roi.size()
            x, y = int(pos[0]), int(pos[1])
            w, h = int(size[0]), int(size[1])
            self.roi_info_label.setText(
                f"ROI Position: ({x}, {y}), Size: {w}×{h}"
            )

    def _apply_roi(self):
        """Apply the drawn ROI to crop PVs."""
        if not self.roi:
            QtWidgets.QMessageBox.warning(
                self, "No ROI",
                "Please enable and draw an ROI first."
            )
            return

        # Get image and convert ROI (scene coords) → image pixel coords
        # via getArraySlice, which handles all coordinate transforms correctly.
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            QtWidgets.QMessageBox.warning(self, "Error",
                "Cannot access image view.")
            return

        image_view = parent_viewer.image_view
        image_item = image_view.getImageItem()
        if image_item is None or image_item.image is None:
            QtWidgets.QMessageBox.warning(self, "Error",
                "No image available.")
            return

        image = image_item.image
        img_h, img_w = image.shape[:2]

        try:
            roi_slice, _ = self.roi.getArraySlice(image, image_item)
            # roi_slice[0] = row (y) slice, roi_slice[1] = col (x) slice
            row_sl = roi_slice[0]
            col_sl = roi_slice[1]
            x = max(0, col_sl.start or 0)
            y = max(0, row_sl.start or 0)
            w = max(1, (col_sl.stop or img_w) - x)
            h = max(1, (row_sl.stop or img_h) - y)
        except Exception as e:
            self._log_message(f"getArraySlice failed: {e}")
            return

        crop_left   = x
        crop_right  = img_w - (x + w)
        crop_top    = y
        crop_bottom = img_h - (y + h)

        # Apply to crop PVs
        crop_prefix = self.crop_prefix_input.text()
        success = True

        if not self._set_pv_value(f"{crop_prefix}:CropLeft", crop_left):
            success = False
        if not self._set_pv_value(f"{crop_prefix}:CropRight", crop_right):
            success = False
        if not self._set_pv_value(f"{crop_prefix}:CropTop", crop_top):
            success = False
        if not self._set_pv_value(f"{crop_prefix}:CropBottom", crop_bottom):
            success = False

        # Apply the crop
        if success:
            if not self._set_pv_value(f"{crop_prefix}:Crop", 1):
                success = False

        if success:
            self._log_message(
                f"Applied ROI: Left={crop_left}, Right={crop_right}, "
                f"Top={crop_top}, Bottom={crop_bottom}"
            )
            QtWidgets.QMessageBox.information(
                self, "Success",
                f"ROI applied to detector:\n"
                f"CropLeft={crop_left}, CropRight={crop_right}\n"
                f"CropTop={crop_top}, CropBottom={crop_bottom}\n"
                f"ROI region: ({x},{y}) size {w}×{h}"
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Failed to apply ROI. Check log for details."
            )

    def _remove_roi(self):
        """Remove ROI from detector (reset to full frame)."""
        prefix = self.pv_prefix_input.text()

        # Get the full detector size
        max_sizex = self._get_pv_value(f"{prefix}:MaxSizeX_RBV")
        max_sizey = self._get_pv_value(f"{prefix}:MaxSizeY_RBV")

        if not max_sizex or not max_sizey:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Could not read detector maximum size.\n"
                "Make sure the PV prefix is correct."
            )
            return

        # Set ROI to full frame: MinX=0, MinY=0, SizeX=Max, SizeY=Max
        success = True
        if not self._set_pv_value(f"{prefix}:MinX", 0):
            success = False
        if not self._set_pv_value(f"{prefix}:MinY", 0):
            success = False
        if not self._set_pv_value(f"{prefix}:SizeX", max_sizex):
            success = False
        if not self._set_pv_value(f"{prefix}:SizeY", max_sizey):
            success = False

        if success:
            self._log_message(f"Removed ROI: Reset to full frame {max_sizex}×{max_sizey}")
            QtWidgets.QMessageBox.information(
                self, "Success",
                f"ROI removed. Detector reset to full frame:\n"
                f"{max_sizex}×{max_sizey}"
            )
            # Update the display
            self._read_roi()
        else:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Failed to remove ROI. Check log for details."
            )

    def closeEvent(self, event):
        """Handle dialog close event."""
        if self.roi:
            sc = self._get_scene()
            if sc:
                try:
                    sc.removeItem(self.roi)
                except Exception:
                    pass
            self.roi = None
        event.accept()
