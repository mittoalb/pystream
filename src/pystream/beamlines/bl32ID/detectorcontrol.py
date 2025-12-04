"""
Detector Control Plugin for bl32ID

Controls detector binning and ROI by:
- Setting BinX/BinY which automatically updates SizeX/SizeY
- Drawing an ROI on the image that sets MinX/MinY/SizeX/SizeY
"""

import subprocess
import logging
from typing import Optional
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore


class DetectorControlDialog(QtWidgets.QDialog):
    """Dialog for controlling detector binning and ROI."""

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Detector Control - bl32ID")
        self.resize(500, 600)

        self.roi = None
        self.roi_enabled = False
        self._last_image = None

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

        bin_button_layout = QtWidgets.QHBoxLayout()
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
            "ROI sets MinX, MinY, SizeX, SizeY on the detector."
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
        """Set PV value using caput."""
        try:
            result = subprocess.run(
                ['caput', pv_name, str(value)],
                capture_output=True,
                text=True,
                timeout=5
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
        """Read current binning values from detector."""
        prefix = self.pv_prefix_input.text()

        binx_val = self._get_pv_value(f"{prefix}:BinX")
        biny_val = self._get_pv_value(f"{prefix}:BinY")

        if binx_val:
            self.binx_spin.setValue(int(binx_val))
        if biny_val:
            self.biny_spin.setValue(int(biny_val))

        self._log_message(f"Read binning: BinX={binx_val}, BinY={biny_val}")

    def _apply_binning(self):
        """Apply binning values to detector."""
        prefix = self.pv_prefix_input.text()
        binx = self.binx_spin.value()
        biny = self.biny_spin.value()

        success = True
        if not self._set_pv_value(f"{prefix}:BinX", binx):
            success = False
        if not self._set_pv_value(f"{prefix}:BinY", biny):
            success = False

        if success:
            self._log_message(f"Applied binning: BinX={binx}, BinY={biny}")
            QtWidgets.QMessageBox.information(
                self, "Success",
                f"Binning applied: BinX={binx}, BinY={biny}"
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Failed to apply binning. Check log for details."
            )

    def _read_roi(self):
        """Read current ROI values from detector."""
        prefix = self.pv_prefix_input.text()

        minx = self._get_pv_value(f"{prefix}:MinX")
        miny = self._get_pv_value(f"{prefix}:MinY")
        sizex = self._get_pv_value(f"{prefix}:SizeX")
        sizey = self._get_pv_value(f"{prefix}:SizeY")

        if all([minx, miny, sizex, sizey]):
            self.roi_info_label.setText(
                f"Current ROI: MinX={minx}, MinY={miny}, "
                f"SizeX={sizex}, SizeY={sizey}"
            )
            self._log_message(f"Read ROI: MinX={minx}, MinY={miny}, SizeX={sizex}, SizeY={sizey}")

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

    def _create_or_show_roi(self):
        """Create or show the ROI on the image."""
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            self._log_message("Error: Cannot access image view")
            return

        image_view = parent_viewer.image_view

        if self.roi is None:
            # Create ROI if it doesn't exist
            if hasattr(parent_viewer, 'image_view'):
                image_item = image_view.getImageItem()
                if image_item is not None:
                    image = image_item.image
                    if image is not None:
                        h, w = image.shape[:2]
                        # Create ROI in center, 50% of image size
                        rw = max(10, w // 2)
                        rh = max(10, h // 2)
                        rx = (w - rw) // 2
                        ry = (h - rh) // 2

                        self.roi = pg.ROI([rx, ry], [rw, rh], pen='r')
                        self.roi.addScaleHandle([1, 1], [0, 0])
                        self.roi.addScaleHandle([0, 0], [1, 1])
                        self.roi.addScaleHandle([1, 0], [0, 1])
                        self.roi.addScaleHandle([0, 1], [1, 0])

                        image_view.addItem(self.roi)
                        self.roi.sigRegionChanged.connect(self._on_roi_changed)
                        self._log_message(f"ROI created at ({rx}, {ry}) size ({rw}, {rh})")
        else:
            # Show existing ROI
            self.roi.setVisible(True)

    def _reset_roi(self):
        """Reset ROI to center of image."""
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            return

        image_view = parent_viewer.image_view
        image_item = image_view.getImageItem()
        if image_item is not None:
            image = image_item.image
            if image is not None:
                h, w = image.shape[:2]
                rw = max(10, w // 2)
                rh = max(10, h // 2)
                rx = (w - rw) // 2
                ry = (h - rh) // 2

                if self.roi:
                    self.roi.setPos([rx, ry])
                    self.roi.setSize([rw, rh])
                    self._log_message(f"ROI reset to ({rx}, {ry}) size ({rw}, {rh})")

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
        """Apply the drawn ROI to detector PVs."""
        if not self.roi:
            QtWidgets.QMessageBox.warning(
                self, "No ROI",
                "Please enable and draw an ROI first."
            )
            return

        pos = self.roi.pos()
        size = self.roi.size()

        minx = int(pos[0])
        miny = int(pos[1])
        sizex = int(size[0])
        sizey = int(size[1])

        # Apply to detector
        prefix = self.pv_prefix_input.text()
        success = True

        if not self._set_pv_value(f"{prefix}:MinX", minx):
            success = False
        if not self._set_pv_value(f"{prefix}:MinY", miny):
            success = False
        if not self._set_pv_value(f"{prefix}:SizeX", sizex):
            success = False
        if not self._set_pv_value(f"{prefix}:SizeY", sizey):
            success = False

        if success:
            self._log_message(f"Applied ROI: MinX={minx}, MinY={miny}, SizeX={sizex}, SizeY={sizey}")
            QtWidgets.QMessageBox.information(
                self, "Success",
                f"ROI applied to detector:\n"
                f"MinX={minx}, MinY={miny}\n"
                f"SizeX={sizex}, SizeY={sizey}"
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Failed to apply ROI. Check log for details."
            )

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Remove ROI from image view
        if self.roi:
            parent_viewer = self.parent()
            if parent_viewer and hasattr(parent_viewer, 'image_view'):
                try:
                    parent_viewer.image_view.removeItem(self.roi)
                except Exception:
                    pass
            self.roi = None
        event.accept()
