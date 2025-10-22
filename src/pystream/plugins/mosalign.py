#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D Motor Scan Plugin for PyQtGraph Viewer
------------------------------------------
Moves 3 motors through a 3D grid with LIVE X-Y stitched preview.

- Z-axis: Just moves through positions (no stitching)
- X-Y grid: Stitched together in real-time preview
- Shows live mosaic as scan progresses

FIXED: Added timer to update stitched preview display
"""

import logging
import subprocess
import time
import numpy as np
from typing import Optional
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
pg.setConfigOptions(imageAxisOrder='row-major')
import pvaccess as pva


class MotorScanDialog(QtWidgets.QDialog):
    """Dialog for configuring and running 3D motor scans"""
    
    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.scanning = False
        self.scan_thread = None
        self.image_monitor = None
        self.current_image = None
        
        # For stitched preview
        self.stitched_image = None
        self.stitched_lock = QtCore.QMutex()
        
        # Crosshair
        self.crosshair_enabled = False
        self.crosshair_x = None
        self.crosshair_y = None
        
        # ADDED: Timer to refresh preview during scan
        self.preview_timer = QtCore.QTimer()
        self.preview_timer.timeout.connect(self._refresh_stitched_preview)
        
        self.setWindowTitle("Mosalign")
        self.setModal(False)
        self.resize(1200, 800)
        
        self._build_ui()
        self._load_defaults()
    
    def _build_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setSpacing(10)
        
        # Left panel - Controls
        left_panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(left_panel)
        layout.setSpacing(10)
        
        # Title
        title = QtWidgets.QLabel("Mosalign PVs")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Motor PVs group
        pv_group = QtWidgets.QGroupBox("Motor PVs")
        pv_layout = QtWidgets.QFormLayout()
        
        self.motor1_pv = QtWidgets.QLineEdit("2bmb:m17")
        self.motor2_pv = QtWidgets.QLineEdit("2bmHXP:m3")
        
        pv_layout.addRow("Motor 1 (X-axis):", self.motor1_pv)
        pv_layout.addRow("Motor 2 (Y-axis):", self.motor2_pv)
        
        pv_group.setLayout(pv_layout)
        layout.addWidget(pv_group)
        
        # Scan parameters group
        params_group = QtWidgets.QGroupBox("Scan Parameters")
        params_layout = QtWidgets.QGridLayout()
        
        # Headers
        params_layout.addWidget(QtWidgets.QLabel("<b>Axis</b>"), 0, 0)
        params_layout.addWidget(QtWidgets.QLabel("<b>Start</b>"), 0, 1)
        params_layout.addWidget(QtWidgets.QLabel("<b>Step Size</b>"), 0, 2)
        params_layout.addWidget(QtWidgets.QLabel("<b>Steps</b>"), 0, 3)
        
        # X-axis
        params_layout.addWidget(QtWidgets.QLabel("X:"), 1, 0)
        self.x_start = QtWidgets.QDoubleSpinBox()
        self.x_start.setRange(-1000, 1000)
        self.x_start.setDecimals(3)
        self.x_start.setValue(-0.16)
        params_layout.addWidget(self.x_start, 1, 1)
        
        self.x_step = QtWidgets.QDoubleSpinBox()
        self.x_step.setRange(-1000, 1000)
        self.x_step.setDecimals(3)
        self.x_step.setValue(4.0)
        params_layout.addWidget(self.x_step, 1, 2)
        
        self.x_step_size = QtWidgets.QSpinBox()
        self.x_step_size.setRange(1, 1000)
        self.x_step_size.setValue(2)
        params_layout.addWidget(self.x_step_size, 1, 3)
        
        # Y-axis
        params_layout.addWidget(QtWidgets.QLabel("Y:"), 2, 0)
        self.y_start = QtWidgets.QDoubleSpinBox()
        self.y_start.setRange(-1000, 1000)
        self.y_start.setDecimals(3)
        self.y_start.setValue(0.0)
        params_layout.addWidget(self.y_start, 2, 1)
        
        self.y_step = QtWidgets.QDoubleSpinBox()
        self.y_step.setRange(-1000, 1000)
        self.y_step.setDecimals(3)
        self.y_step.setValue(1.4)
        params_layout.addWidget(self.y_step, 2, 2)
        
        self.y_step_size = QtWidgets.QSpinBox()
        self.y_step_size.setRange(1, 1000)
        self.y_step_size.setValue(3)
        params_layout.addWidget(self.y_step_size, 2, 3)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # Overlap settings
        overlap_group = QtWidgets.QGroupBox("Stitching Settings")
        overlap_layout = QtWidgets.QFormLayout()
        
        self.pixel_size = QtWidgets.QDoubleSpinBox()
        self.pixel_size.setRange(0.001, 100)
        self.pixel_size.setDecimals(3)
        self.pixel_size.setValue(1.0)
        self.pixel_size.setSuffix(" µm")
        overlap_layout.addRow("Pixel Size:", self.pixel_size)
        
        self.h_overlap = QtWidgets.QDoubleSpinBox()
        self.h_overlap.setRange(0, 0.9)
        self.h_overlap.setDecimals(2)
        self.h_overlap.setValue(0.15)
        self.h_overlap.setSuffix(" (15%)")
        overlap_layout.addRow("Horizontal Overlap:", self.h_overlap)
        
        self.v_overlap = QtWidgets.QDoubleSpinBox()
        self.v_overlap.setRange(0, 0.9)
        self.v_overlap.setDecimals(2)
        self.v_overlap.setValue(0.15)
        self.v_overlap.setSuffix(" (15%)")
        overlap_layout.addRow("Vertical Overlap:", self.v_overlap)
        
        # Button to calculate overlap from pixel size
        calc_overlap_btn = QtWidgets.QPushButton("Calculate from Step Size")
        calc_overlap_btn.clicked.connect(self._calculate_overlap_from_steps)
        overlap_layout.addRow("", calc_overlap_btn)
        
        overlap_group.setLayout(overlap_layout)
        layout.addWidget(overlap_group)
        
        # Additional settings
        settings_group = QtWidgets.QGroupBox("Additional Settings")
        settings_layout = QtWidgets.QFormLayout()
        
        self.settle_time = QtWidgets.QDoubleSpinBox()
        self.settle_time.setRange(0, 60)
        self.settle_time.setDecimals(1)
        self.settle_time.setValue(5.0)
        self.settle_time.setSuffix(" s")
        settings_layout.addRow("Settle Time:", self.settle_time)
        
        self.motor_tolerance = QtWidgets.QDoubleSpinBox()
        self.motor_tolerance.setRange(0.0001, 1.0)
        self.motor_tolerance.setDecimals(4)
        self.motor_tolerance.setValue(0.0010)
        self.motor_tolerance.setSuffix(" mm")
        settings_layout.addRow("Motor Position Tolerance:", self.motor_tolerance)
        
        self.start_from = QtWidgets.QSpinBox()
        self.start_from.setRange(1, 10000)
        self.start_from.setValue(1)
        settings_layout.addRow("Start From Position:", self.start_from)
        
        self.caput_timeout = QtWidgets.QDoubleSpinBox()
        self.caput_timeout.setRange(1, 300)
        self.caput_timeout.setValue(10.0)
        self.caput_timeout.setSuffix(" s")
        settings_layout.addRow("Caput Timeout:", self.caput_timeout)
        
        self.run_tomoscan = QtWidgets.QCheckBox("Run tomoscan at each position")
        settings_layout.addRow("", self.run_tomoscan)
        
        self.tomoscan_prefix = QtWidgets.QLineEdit("2bmb:TomoScan:")
        self.tomoscan_prefix.setEnabled(False)
        self.run_tomoscan.toggled.connect(self.tomoscan_prefix.setEnabled)
        settings_layout.addRow("Tomoscan Prefix:", self.tomoscan_prefix)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Image PV settings
        image_group = QtWidgets.QGroupBox("Camera PV (Input)")
        image_layout = QtWidgets.QVBoxLayout()
        image_layout.setSpacing(6)
        
        info_text = QtWidgets.QLabel(
            "Note: Connect to your camera PV. The stitched mosaic\n"
            "will be displayed in the preview panel on the right."
        )
        info_text.setStyleSheet("color: #aaa; font-size: 10px;")
        image_layout.addWidget(info_text)
        
        pv_input_layout = QtWidgets.QHBoxLayout()
        self.image_pv = QtWidgets.QLineEdit("2bmbSP1:Pva1:Image")
        pv_input_layout.addWidget(QtWidgets.QLabel("Image PV:"))
        pv_input_layout.addWidget(self.image_pv)
        image_layout.addLayout(pv_input_layout)
        
        button_layout = QtWidgets.QHBoxLayout()
        self.test_pv_btn = QtWidgets.QPushButton("Test PV")
        self.test_pv_btn.clicked.connect(self._test_pv_connection)
        self.connect_pv_btn = QtWidgets.QPushButton("Connect")
        self.connect_pv_btn.clicked.connect(self._connect_image_pv)
        button_layout.addWidget(self.test_pv_btn)
        button_layout.addWidget(self.connect_pv_btn)
        image_layout.addLayout(button_layout)
        
        self.connection_status = QtWidgets.QLabel("Status: Not connected")
        self.connection_status.setStyleSheet("color: #f88; font-size: 10px;")
        image_layout.addWidget(self.connection_status)
        
        image_group.setLayout(image_layout)
        layout.addWidget(image_group)
        
        # Preview settings
        preview_group = QtWidgets.QGroupBox("Preview Settings")
        preview_layout = QtWidgets.QVBoxLayout()
        
        self.enable_preview = QtWidgets.QCheckBox("Enable Live Preview")
        self.enable_preview.setChecked(True)
        preview_layout.addWidget(self.enable_preview)
        
        # Contrast controls
        contrast_frame = QtWidgets.QWidget()
        contrast_layout = QtWidgets.QFormLayout()
        contrast_layout.setSpacing(5)
        
        self.auto_contrast = QtWidgets.QCheckBox("Auto Contrast")
        self.auto_contrast.setChecked(True)
        contrast_layout.addRow("", self.auto_contrast)
        
        self.min_contrast = QtWidgets.QSpinBox()
        self.min_contrast.setRange(0, 65535)
        self.min_contrast.setValue(0)
        self.min_contrast.setEnabled(False)
        contrast_layout.addRow("Min:", self.min_contrast)
        
        self.max_contrast = QtWidgets.QSpinBox()
        self.max_contrast.setRange(0, 65535)
        self.max_contrast.setValue(65535)
        self.max_contrast.setEnabled(False)
        contrast_layout.addRow("Max:", self.max_contrast)
        
        # Enable/disable manual controls based on auto checkbox
        self.auto_contrast.toggled.connect(lambda checked: self.min_contrast.setEnabled(not checked))
        self.auto_contrast.toggled.connect(lambda checked: self.max_contrast.setEnabled(not checked))
        
        contrast_frame.setLayout(contrast_layout)
        preview_layout.addWidget(contrast_frame)
        
        # Crosshair
        self.chk_crosshair = QtWidgets.QCheckBox("Crosshair")
        self.chk_crosshair.stateChanged.connect(self._toggle_crosshair)
        preview_layout.addWidget(self.chk_crosshair)
        
        self.lbl_crosshair = QtWidgets.QLabel("Disabled")
        self.lbl_crosshair.setStyleSheet("color: #aaa; font-size: 10px; padding: 5px;")
        self.lbl_crosshair.setWordWrap(True)
        preview_layout.addWidget(self.lbl_crosshair)
        
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)
        
        # Info label
        self.info_label = QtWidgets.QLabel()
        self.info_label.setStyleSheet("color: #aaa; padding: 10px; border: 1px solid #555; border-radius: 5px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        
        # Add stretch
        layout.addStretch()
        
        # Action buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.start_btn = QtWidgets.QPushButton("Start Scan")
        self.start_btn.clicked.connect(self._start_scan)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_scan)
        button_layout.addWidget(self.stop_btn)
        
        layout.addLayout(button_layout)
        
        # Progress
        self.progress = QtWidgets.QProgressBar()
        layout.addWidget(self.progress)
        
        # Position display
        self.position_label = QtWidgets.QLabel("Position: -")
        self.position_label.setStyleSheet("font-size: 11px; color: #ccc;")
        layout.addWidget(self.position_label)
        
        # Add left panel to main layout
        main_layout.addWidget(left_panel, 1)
        
        # Right panel - Image preview & log
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        
        # Image view
        view_label = QtWidgets.QLabel("Live Preview (Stitched Mosaic)")
        view_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(view_label)
        
        self.graphics_view = pg.GraphicsLayoutWidget()
        self.view_box = self.graphics_view.addViewBox()
        self.view_box.setAspectLocked(True)
        self.image_view = pg.ImageItem()
        self.view_box.addItem(self.image_view)
        
        # Add crosshair lines
        self.crosshair_vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('y', width=2))
        self.crosshair_hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('y', width=2))
        self.crosshair_vline.setVisible(False)
        self.crosshair_hline.setVisible(False)
        self.view_box.addItem(self.crosshair_vline)
        self.view_box.addItem(self.crosshair_hline)
        
        # Connect mouse events
        self.graphics_view.scene().sigMouseMoved.connect(self._on_mouse_move)
        self.graphics_view.scene().sigMouseClicked.connect(self._on_mouse_click)
        
        right_layout.addWidget(self.graphics_view, 2)
        
        # Log output
        log_label = QtWidgets.QLabel("Scan Log")
        log_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(log_label)
        
        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        self.log_output.setStyleSheet("background-color: #1a1a1a; color: #0f0; font-family: monospace; font-size: 10px;")
        right_layout.addWidget(self.log_output, 1)
        
        # Add right panel to main layout
        main_layout.addWidget(right_panel, 2)
        
        # Update initial info
        self._update_info()
        
        # Connect value changes to info update
        for widget in [self.x_step_size, self.y_step_size, 
                      self.settle_time, self.caput_timeout]:
            widget.valueChanged.connect(self._update_info)
    
    def _load_defaults(self):
        """Load default values from config if available"""
        import os
        import json
        
        config_file = "motor_scan_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                # Load PVs
                if 'motor1_pv' in config:
                    self.motor1_pv.setText(config['motor1_pv'])
                if 'motor2_pv' in config:
                    self.motor2_pv.setText(config['motor2_pv'])
                if 'image_pv' in config:
                    self.image_pv.setText(config['image_pv'])
                if 'tomoscan_prefix' in config:
                    self.tomoscan_prefix.setText(config['tomoscan_prefix'])
                
                # Load scan parameters
                if 'pixel_size' in config:
                    self.pixel_size.setValue(config['pixel_size'])
                if 'x_start' in config:
                    self.x_start.setValue(config['x_start'])
                if 'x_step' in config:
                    self.x_step.setValue(config['x_step'])
                if 'x_step_size' in config:
                    self.x_step_size.setValue(config['x_step_size'])
                if 'y_start' in config:
                    self.y_start.setValue(config['y_start'])
                if 'y_step' in config:
                    self.y_step.setValue(config['y_step'])
                if 'y_step_size' in config:
                    self.y_step_size.setValue(config['y_step_size'])
                if 'settle_time' in config:
                    self.settle_time.setValue(config['settle_time'])
                if 'caput_timeout' in config:
                    self.caput_timeout.setValue(config['caput_timeout'])
                
                self._log("✓ Loaded settings from config")
            except Exception as e:
                self._log(f"Could not load config: {e}")
    
    def _save_config(self):
        """Save current settings to config file"""
        import json
        
        config = {
            'motor1_pv': self.motor1_pv.text(),
            'motor2_pv': self.motor2_pv.text(),
            'image_pv': self.image_pv.text(),
            'tomoscan_prefix': self.tomoscan_prefix.text(),
            'pixel_size': self.pixel_size.value(),
            'x_start': self.x_start.value(),
            'x_step': self.x_step.value(),
            'x_step_size': self.x_step_size.value(),
            'y_start': self.y_start.value(),
            'y_step': self.y_step.value(),
            'y_step_size': self.y_step_size.value(),
            'settle_time': self.settle_time.value(),
            'caput_timeout': self.caput_timeout.value(),
        }
        
        try:
            with open("motor_scan_config.json", 'w') as f:
                json.dump(config, f, indent=2)
            self._log("✓ Settings saved")
        except Exception as e:
            self._log(f"Failed to save config: {e}")
    
    def _update_info(self):
        """Update information label"""
        total = self.x_step_size.value() * self.y_step_size.value()
        settle = self.settle_time.value()
        timeout = self.caput_timeout.value()
        est_time = total * (2 * timeout + settle)  # 2 motors (X, Y)
        
        info = (
            f"<b>Total Positions:</b> {total}<br>"
            f"<b>Estimated Time:</b> {est_time/60:.1f} minutes<br>"
            f"<b>Grid Size:</b> {self.x_step_size.value()} × {self.y_step_size.value()}<br>"
            f"<b>Note:</b> Preview shows X-Y stitched mosaic"
        )
        self.info_label.setText(info)
    
    def _calculate_overlap_from_steps(self):
        """Auto-calculate overlap from pixel size and step sizes"""
        try:
            pixel_size = self.pixel_size.value()  # µm
            x_step_mm = self.x_step.value()  # mm
            y_step_mm = self.y_step.value()  # mm
            
            # Get image size from PV
            pv_name = self.image_pv.text().strip()
            if not pv_name:
                self._log("⚠ Please enter image PV first")
                return
            
            size_x_pv = pv_name.replace("Pva1:Image", "cam1:ArraySizeX_RBV")
            size_y_pv = pv_name.replace("Pva1:Image", "cam1:SizeY_RBV")
            
            import epics
            img_w = int(epics.caget(size_x_pv))
            img_h = int(epics.caget(size_y_pv))
            
            # Convert to same units
            x_step_um = x_step_mm * 1000
            y_step_um = y_step_mm * 1000
            
            img_w_um = img_w * pixel_size
            img_h_um = img_h * pixel_size
            
            # Calculate overlap
            h_overlap = max(0, (img_w_um - x_step_um) / img_w_um)
            v_overlap = max(0, (img_h_um - y_step_um) / img_h_um)
            
            self.h_overlap.setValue(h_overlap)
            self.v_overlap.setValue(v_overlap)
            
            self._log(f"✓ Calculated overlap: H={h_overlap:.1%}, V={v_overlap:.1%}")
            self._log(f"  Image: {img_w}×{img_h} px = {img_w_um:.0f}×{img_h_um:.0f} µm")
            self._log(f"  Steps: {x_step_um:.0f}×{y_step_um:.0f} µm")
            
        except Exception as e:
            self._log(f"Failed to calculate overlap: {e}")
    
    def _log(self, message: str):
        """Add message to log"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        if self.logger:
            self.logger.info(message)
    
    def _test_pv_connection(self):
        """Test if PV is accessible using pvaccess"""
        pv_name = self.image_pv.text().strip()
        
        self._log(f"Testing PV: {pv_name}")
        
        try:
            self._log("Attempting pvaccess connection...")
            chan = pva.Channel(pv_name)
            
            try:
                data = chan.get()
                self._log(f"✓ PV accessible via pvaccess")
                self._log(f"  Type: {type(data)}")
                if 'dimension' in data:
                    dims = data['dimension']
                    self._log(f"  Dimensions: {[d['size'] for d in dims]}")
                else:
                    self._log(f"  Keys: {list(data.keys())}")
            except Exception as e:
                self._log(f"✗ Failed to get PV data: {e}")
                
        except ImportError:
            self._log("✗ pvaccess not installed (pip install pvaccess)")
        except Exception as e:
            self._log(f"✗ Test failed: {e}")
    
    def _connect_image_pv(self):
        """Connect to the image PV for live preview"""
        pv_name = self.image_pv.text().strip()
        if not pv_name:
            QtWidgets.QMessageBox.warning(self, "Warning", "Please enter an image PV name")
            return
        
        try:
            # Stop existing monitor if any
            if self.image_monitor:
                self.image_monitor.stop()
                self.image_monitor = None
            
            # Start new monitor
            self.image_monitor = ImagePVMonitor(pv_name, self)
            self.image_monitor.image_updated.connect(self._update_current_image)
            self.image_monitor.connection_status.connect(self._update_connection_status)
            self.image_monitor.start()
            
            self._log(f"Connecting to image PV: {pv_name}")
        except Exception as e:
            self._log(f"Failed to connect to PV: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to connect to PV:\n{e}")
    
    def _update_current_image(self, image_data):
        """Store current image from PV - called from monitor thread via signal"""
        if image_data is not None:
            print(f"Received image: shape={image_data.shape}, dtype={image_data.dtype}, range={image_data.min()}-{image_data.max()}")
            self.current_image = image_data.copy()
            
    
    def _refresh_stitched_preview(self):
        """Refresh the stitched mosaic display"""
        if not self.enable_preview.isChecked():
            return
        
        # Show stitched image when it exists (during scanning)
        self.stitched_lock.lock()
        try:
            if self.stitched_image is not None:
                # Flip vertically to correct display orientation
                img = np.flipud(self.stitched_image.copy())
                
                print(f"Refreshing preview: shape={img.shape}, range={img.min()}-{img.max()}, nonzero={np.count_nonzero(img)}")
                
                # Auto-range only on the first update
                auto_range = not hasattr(self, '_preview_initialized')
                if auto_range:
                    self._preview_initialized = True
                    print(f"✓ First preview update - auto ranging")
                
                # Use percentile-based contrast like working code
                if self.auto_contrast.isChecked():
                    # Calculate percentiles from non-zero values
                    nz = img[img > 0]
                    if nz.size > 0:
                        vmin, vmax = np.percentile(nz, [1, 99])
                    else:
                        vmin, vmax = 0, 65535
                    
                    print(f"Auto contrast: {vmin:.0f} - {vmax:.0f}")
                    
                    self.image_view.setImage(img, levels=[vmin, vmax])
                    if auto_range:
                        self.view_box.autoRange()
                else:
                    # Manual contrast
                    vmin = self.min_contrast.value()
                    vmax = self.max_contrast.value()
                    self.image_view.setImage(img, levels=[vmin, vmax])
                    if auto_range:
                        self.view_box.autoRange()
                
                # Update crosshair if enabled
                if self.crosshair_enabled:
                    if self.crosshair_x is None or self.crosshair_y is None:
                        self.crosshair_x = img.shape[1] // 2
                        self.crosshair_y = img.shape[0] // 2
                    self._update_crosshair_display()
            else:
                print("Preview: No stitched_image")
        finally:
            self.stitched_lock.unlock()
    
    def _update_connection_status(self, connected: bool, message: str):
        """Update connection status"""
        if connected:
            status_text = f"Camera: {message}"
            self.connection_status.setStyleSheet("color: #8f8; font-size: 10px;")
        else:
            status_text = f"Camera: {message}"
            self.connection_status.setStyleSheet("color: #f88; font-size: 10px;")
        
        self.connection_status.setText(status_text)
    
    def _get_image_now(self):
        """Get image from PV right now - EXACT copy of working code"""
        try:
            pv_name = self.image_pv.text().strip()
            
            # Get image size from EPICS
            size_x_pv = pv_name.replace("Pva1:Image", "cam1:ArraySizeX_RBV")
            size_y_pv = pv_name.replace("Pva1:Image", "cam1:SizeY_RBV")
            
            import epics
            size_x = epics.caget(size_x_pv)
            size_y = epics.caget(size_y_pv)
            
            print('HEREEEEEEEEEEEEEEE', size_x, size_y)
            img_h, img_w = int(size_y), int(size_x)  # height, width
            
            pv = pva.Channel(pv_name)
            arr = pv.get()['value'][0]['ushortValue']
            img = np.asarray(arr, dtype=np.uint16).reshape(img_h, img_w)
            #print(img.shape)
            #exit(0)
            # Rotate 90 degrees
            #img = np.rot90(img, k=-1)  # 90 degrees counter-clockwise
            
            return img
        except Exception as e:
            self._log(f"Error getting image: {e}")
            return None
    
    def _caput(self, pv: str, value: float, timeout: float):
        """Set motor position using caput"""
        try:
            subprocess.run(
                ['caput', '-w', str(timeout), pv, str(value)],
                capture_output=True,
                timeout=timeout + 5,
                check=True
            )
        except subprocess.TimeoutExpired:
            self._log(f"⚠ caput timeout for {pv}")
        except subprocess.CalledProcessError as e:
            self._log(f"⚠ caput error for {pv}: {e}")
    
    def _wait_for_motor(self, pv: str, target: float, tolerance: float = 0.001, timeout: float = 30.0, poll_interval: float = 0.1):
        """Wait for motor to reach target position within tolerance
        
        Args:
            pv: Motor PV name (e.g., '2bmb:m17')
            target: Target position
            tolerance: Acceptable position error (default 0.001 mm)
            timeout: Maximum wait time in seconds
            poll_interval: Time between position checks in seconds
        
        Returns:
            True if motor reached position, False if timeout
        """
        readback_pv = f"{pv}.RBV"  # Most EPICS motors use .RBV for readback
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                # Read current position
                result = subprocess.run(
                    ['caget', '-t', readback_pv],
                    capture_output=True,
                    text=True,
                    timeout=2.0
                )
                
                if result.returncode == 0:
                    current_pos = float(result.stdout.strip())
                    error = abs(current_pos - target)
                    
                    if error <= tolerance:
                        return True
                    
                    # Optional: log if taking too long
                    if (time.time() - start_time) > 5.0 and int(time.time() - start_time) % 5 == 0:
                        self._log(f"  Waiting for {pv}: current={current_pos:.4f}, target={target:.4f}, error={error:.4f}")
                
            except (subprocess.TimeoutExpired, ValueError) as e:
                self._log(f"  Warning: Error reading {readback_pv}: {e}")
            
            time.sleep(poll_interval)
        
        # Timeout reached
        self._log(f"⚠ Motor {pv} timeout - did not reach target {target:.3f} within {timeout}s")
        return False
    
    def _start_scan(self):
        """Start the 3D motor scan"""
        self.scanning = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)
        
        # Reset preview initialization for new scan
        if hasattr(self, '_preview_initialized'):
            delattr(self, '_preview_initialized')
        
        # ADDED: Start the preview refresh timer (update every 500ms)
        self.preview_timer.start(500)
        
        # Create and start scan thread
        self.scan_thread = ScanWorker(self)
        self.scan_thread.progress_signal.connect(self._update_progress)
        self.scan_thread.log_signal.connect(self._log)
        self.scan_thread.position_signal.connect(self._update_position)
        self.scan_thread.finished_signal.connect(self._scan_finished)
        self.scan_thread.start()
        
        self._log("=== Scan started ===")
    
    def _stop_scan(self):
        """Stop the running scan"""
        self.scanning = False
        self._log("⚠ Stopping scan...")
        self.stop_btn.setEnabled(False)
    
    def _scan_finished(self):
        """Called when scan completes"""
        self.scanning = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        # ADDED: Stop the preview refresh timer
        self.preview_timer.stop()
        
        self._log("=== Scan finished ===")
    
    def _update_progress(self, current: int, total: int):
        """Update progress bar"""
        percentage = int((current / total) * 100)
        self.progress.setValue(percentage)
    
    def _update_position(self, position: int, total: int, x: float, y: float, z: float):
        """Update current position display"""
        self.position_label.setText(
            f"Position: {position}/{total} | X={x:.3f}, Y={y:.3f}"
        )
    
    # ------------- Crosshair methods -------------
    def _toggle_crosshair(self):
        """Toggle crosshair on/off"""
        self.crosshair_enabled = self.chk_crosshair.isChecked()
        self.crosshair_vline.setVisible(self.crosshair_enabled)
        self.crosshair_hline.setVisible(self.crosshair_enabled)
        
        if not self.crosshair_enabled:
            self.lbl_crosshair.setText("Disabled")
        else:
            self.lbl_crosshair.setText("Enabled\n(click or move mouse)")
            if self.stitched_image is not None:
                if self.crosshair_x is None or self.crosshair_y is None:
                    self.crosshair_x = self.stitched_image.shape[1] // 2
                    self.crosshair_y = self.stitched_image.shape[0] // 2
                self._update_crosshair_display()
    
    def _update_crosshair_display(self):
        """Update crosshair position and display value"""
        if not self.crosshair_enabled or self.stitched_image is None:
            return
        
        self.crosshair_vline.setPos(self.crosshair_x)
        self.crosshair_hline.setPos(self.crosshair_y)
        
        try:
            # Get flipped image coordinates (since display is flipped)
            img_flipped = np.flipud(self.stitched_image)
            h, w = img_flipped.shape[:2]
            x_pix = int(np.clip(self.crosshair_x, 0, w - 1))
            y_pix = int(np.clip(self.crosshair_y, 0, h - 1))
            value = float(img_flipped[y_pix, x_pix])
            
            # Calculate motor positions
            pixel_size_mm = self.pixel_size.value() / 1000.0
            x_start = self.x_start.value()
            y_start = self.y_start.value()
            
            # X motor position
            x_motor = x_start + (x_pix * pixel_size_mm)
            
            # Y motor position (account for vertical flip in display)
            y_motor = y_start + ((h - 1 - y_pix) * pixel_size_mm)
            
            self.lbl_crosshair.setText(
                f"Pixel: ({x_pix}, {y_pix})\n"
                f"Motor X: {x_motor:.3f} mm\n"
                f"Motor Y: {y_motor:.3f} mm\n"
                f"Value: {value:.0f}"
            )
        except Exception as e:
            self.lbl_crosshair.setText(f"Error: {e}")
    
    def _on_mouse_move(self, pos):
        """Handle mouse move for crosshair"""
        if not self.crosshair_enabled or self.stitched_image is None:
            return
        
        img_pos = self.image_view.mapFromScene(pos)
        self.crosshair_x = img_pos.x()
        self.crosshair_y = img_pos.y()
        self._update_crosshair_display()
    
    def _on_mouse_click(self, event):
        """Handle mouse click for crosshair"""
        if not self.crosshair_enabled or self.stitched_image is None:
            return
        
        pos = event.scenePos()
        img_pos = self.image_view.mapFromScene(pos)
        self.crosshair_x = img_pos.x()
        self.crosshair_y = img_pos.y()
        self._update_crosshair_display()
    
    def closeEvent(self, event):
        """Clean up when dialog is closed"""
        self.scanning = False
        
        # Save settings
        self._save_config()
        
        # FORCE STOP: Stop the timer
        if self.preview_timer.isActive():
            self.preview_timer.stop()
        
        # FORCE STOP: Terminate image monitor thread
        if self.image_monitor:
            self.image_monitor.running = False
            self.image_monitor.quit()
            self.image_monitor.wait(1000)
            if self.image_monitor.isRunning():
                self.image_monitor.terminate()
                self.image_monitor.wait(500)
        
        # FORCE STOP: Terminate scan thread
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.quit()
            self.scan_thread.wait(1000)
            if self.scan_thread.isRunning():
                self.scan_thread.terminate()
                self.scan_thread.wait(500)
        
        event.accept()


class ImagePVMonitor(QtCore.QThread):
    """Background thread to monitor image PV"""
    image_updated = QtCore.pyqtSignal(object)  # numpy array
    connection_status = QtCore.pyqtSignal(bool, str)  # connected, message
    
    def __init__(self, pv_name: str, parent=None):
        super().__init__(parent)
        self.pv_name = pv_name
        self.running = True
        self.channel = None
        self.first_data = True
    
    def run(self):
        """Monitor loop"""
        try:
            self.channel = pva.Channel(self.pv_name)
            self.connection_status.emit(True, f"Connected to {self.pv_name}")
            
            # Try to get image size from the PVs
            try:
                size_x_pv = self.pv_name.replace("Pva1:Image", "cam1:ArraySizeX_RBV")
                size_y_pv = self.pv_name.replace("Pva1:Image", "cam1:SizeY_RBV")
                
                import epics
                img_w = epics.caget(size_x_pv)
                img_h = epics.caget(size_y_pv)
                
                if img_w and img_h:
                    print(f"✓ Got image dimensions from EPICS: {img_w}x{img_h}")
                else:
                    img_w = img_h = None
            except:
                img_w = img_h = None
            
            while self.running:
                try:
                    # Get image data
                    data = self.channel.get()
                    
                    # Debug: print structure on first data
                    if self.first_data:
                        print(f"\n=== PVA Data Structure ===")
                        print(f"Type: {type(data)}")
                        print(f"Keys: {list(data.keys()) if hasattr(data, 'keys') else 'N/A'}")
                        
                        # Check for nested value structure
                        if 'value' in data:
                            val = data['value']
                            print(f"'value' type: {type(val)}, len: {len(val) if hasattr(val, '__len__') else 'N/A'}")
                            if hasattr(val, '__getitem__'):
                                try:
                                    print(f"'value[0]' keys: {list(val[0].keys()) if hasattr(val[0], 'keys') else 'N/A'}")
                                except:
                                    pass
                        
                        self.first_data = False
                    
                    # Try the working format first: data['value'][0]['ushortValue']
                    img_1d = None
                    data_field = None
                    
                    try:
                        # Format 1: Nested structure (MOST COMMON for Area Detector)
                        if 'value' in data:
                            val = data['value']
                            if hasattr(val, '__getitem__') and len(val) > 0:
                                inner = val[0]
                                # Try different data types
                                for field in ['ushortValue', 'ubyteValue', 'shortValue', 'intValue', 
                                            'floatValue', 'doubleValue']:
                                    if field in inner:
                                        img_1d = np.array(inner[field], dtype=np.uint16)
                                        data_field = f"value[0][{field}]"
                                        print(f"✓ Found image data in nested structure: {data_field}")
                                        break
                    except Exception as e:
                        print(f"Failed nested access: {e}")
                    
                    # Format 2: Direct field access (fallback)
                    if img_1d is None:
                        for field in ['value', 'ubyteValue', 'ushortValue', 'shortValue', 
                                     'intValue', 'floatValue', 'doubleValue']:
                            if field in data:
                                try:
                                    img_1d = np.array(data[field], dtype=np.uint16)
                                    data_field = field
                                    print(f"✓ Found image data in direct field: {data_field}")
                                    break
                                except:
                                    pass
                    
                    if img_1d is None:
                        print(f"⚠ No image data found in PV structure")
                        time.sleep(1)
                        continue
                    
                    # Get dimensions
                    height = width = None
                    
                    # Use cached dimensions if available
                    if img_w and img_h:
                        width = img_w
                        height = img_h
                    else:
                        # Try to extract from PVA structure
                        # Format 1: dimension array with 'size' keys
                        if 'dimension' in data:
                            dims = data['dimension']
                            if isinstance(dims, (list, tuple)) and len(dims) >= 2:
                                try:
                                    height = dims[0]['size']
                                    width = dims[1]['size']
                                except (KeyError, TypeError):
                                    pass
                        
                        # Format 2: dims array
                        if height is None and 'dims' in data:
                            dims = data['dims']
                            if isinstance(dims, (list, tuple)) and len(dims) >= 2:
                                height = dims[0]
                                width = dims[1]
                        
                        # Format 3: Try attribute
                        if height is None and 'attribute' in data:
                            attrs = data['attribute']
                            for attr in attrs:
                                if attr.get('name') == 'ImageSize':
                                    val = attr.get('value', [])
                                    if len(val) >= 2:
                                        width = val[0]
                                        height = val[1]
                    
                    if height is None or width is None:
                        print(f"⚠ Could not determine image dimensions")
                        time.sleep(1)
                        continue
                    
                    # Reshape the image
                    try:
                        img_2d = img_1d.reshape((height, width))
                        
                        # Emit the image (no rotation - not used for stitching)
                        self.image_updated.emit(img_2d)
                        
                        if self.first_data:
                            print(f"✓ Successfully extracted image: {width}x{height} from '{data_field}'")
                    except ValueError as e:
                        print(f"⚠ Reshape error: {e} (data length={len(img_1d)}, expected={height*width})")
                    
                    # Small delay to avoid hammering
                    time.sleep(0.1)
                    
                except Exception as e:
                    if self.running:
                        print(f"Monitor error: {e}")
                        import traceback
                        traceback.print_exc()
                        time.sleep(1)
        
        except Exception as e:
            self.connection_status.emit(False, f"Failed: {e}")
            import traceback
            traceback.print_exc()
    
    def stop(self):
        """Stop monitoring"""
        self.running = False


class ScanWorker(QtCore.QThread):
    """Worker thread for running the scan"""
    progress_signal = QtCore.pyqtSignal(int, int)  # current, total
    log_signal = QtCore.pyqtSignal(str)
    position_signal = QtCore.pyqtSignal(int, int, float, float, float)  # pos, total, x, y, z
    finished_signal = QtCore.pyqtSignal()
    
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
    
    def run(self):
        """Run the 2D X-Y scan"""
        try:
            # Get parameters
            motor1_pv = self.dialog.motor1_pv.text().strip()
            motor2_pv = self.dialog.motor2_pv.text().strip()
            
            x_start = self.dialog.x_start.value()
            x_step = self.dialog.x_step.value()
            x_step_size = self.dialog.x_step_size.value()
            
            y_start = self.dialog.y_start.value()
            y_step = self.dialog.y_step.value()
            y_step_size = self.dialog.y_step_size.value()
            
            settle_time = self.dialog.settle_time.value()
            motor_tolerance = self.dialog.motor_tolerance.value()
            start_from = self.dialog.start_from.value()
            timeout = self.dialog.caput_timeout.value()
            
            h_overlap = self.dialog.h_overlap.value()
            v_overlap = self.dialog.v_overlap.value()
            
            total_positions = x_step_size * y_step_size
            position = 0
            
            # FIRST: Move to start position before taking any images
            self.log_signal.emit(f"Moving to start position: X={x_start:.3f}, Y={y_start:.3f}")
            self.dialog._caput(motor1_pv, x_start, timeout)
            time.sleep(0.1)
            self.dialog._caput(motor2_pv, y_start, timeout)
            time.sleep(settle_time)
            
            # Get a test image to determine canvas size
            self.log_signal.emit("Getting test image to determine canvas size...")
            test_img = self.dialog._get_image_now()
            
            if test_img is not None:
                img_h, img_w = test_img.shape
                
                # Calculate effective step size in PIXELS
                # number_of_pixels = step / pixel_size
                pixel_size_um = self.dialog.pixel_size.value()  # µm per pixel
                x_step_um = x_step * 1000  # convert mm to µm
                y_step_um = y_step * 1000  # convert mm to µm
                
                # Effective size = how many pixels to move between images
                eff_w = int(x_step_um / pixel_size_um)  # pixels to step in X (width)
                eff_h = int(y_step_um / pixel_size_um)  # pixels to step in Y (height)
                
                self.log_signal.emit(
                    f"Pixel calculation: pixel_size={pixel_size_um}µm, "
                    f"x_step={x_step_um}µm→{eff_w}px, y_step={y_step_um}µm→{eff_h}px"
                )
                
                # Total canvas size - CORRECTED for proper axis mapping
                # X steps create COLUMNS (horizontal/width)
                # Y steps create ROWS (vertical/height)
                out_w = eff_w * x_step_size + (img_w - eff_w)  # X motor → width
                out_h = eff_h * y_step_size + (img_h - eff_h)  # Y motor → height
                
                self.log_signal.emit(
                    f"Stitching setup: Image={img_w}×{img_h}, "
                    f"Effective={eff_w}×{eff_h}, Canvas={out_w}×{out_h}"
                )
            else:
                self.log_signal.emit("⚠ Failed to get test image - cannot determine canvas size!")
                return
            
            # Initialize stitched canvas
            self.dialog.stitched_lock.lock()
            self.dialog.stitched_image = np.zeros((out_h, out_w), dtype=np.uint16)
            self.dialog.stitched_lock.unlock()
            
            # Scan X-Y grid
            # Outer loop: X axis (creates columns, left to right)
            # Inner loop: Y axis (creates rows, bottom to top in motor, top to bottom in image)
            for i in range(x_step_size):
                if not self.dialog.scanning:
                    break
                
                for j in range(y_step_size):
                    if not self.dialog.scanning:
                        break
                    
                    # MOTOR POSITIONS - use start position + step * index
                    x_pos = x_start + (i * x_step)
                    y_pos = y_start + (j * y_step)
                    
                    position += 1
                    
                    if position < start_from:
                        continue
                    
                    self.log_signal.emit(
                        f"[{position}/{total_positions}] (X:{i+1}/{x_step_size}, Y:{j+1}/{y_step_size}) "
                        f"X={x_pos:.3f}, Y={y_pos:.3f}"
                    )
                    
                    # Move motors WITHOUT waiting (remove -w flag)
                    try:
                        subprocess.run(
                            ['caput', motor1_pv, str(x_pos)],
                            capture_output=True,
                            timeout=5
                        )
                        subprocess.run(
                            ['caput', motor2_pv, str(y_pos)],
                            capture_output=True,
                            timeout=5
                        )
                    except Exception as e:
                        self.log_signal.emit(f"  ⚠ Error moving motors: {e}")
                    
                    # Wait for BOTH motors to reach target positions
                    motor1_ready = self.dialog._wait_for_motor(motor1_pv, x_pos, tolerance=motor_tolerance, timeout=timeout)
                    motor2_ready = self.dialog._wait_for_motor(motor2_pv, y_pos, tolerance=motor_tolerance, timeout=timeout)
                    
                    if not motor1_ready or not motor2_ready:
                        self.log_signal.emit(f"  ⚠ Motors did not reach target position!")
                        # Continue anyway or skip? Let's continue but log warning
                    
                    # Update position display
                    self.position_signal.emit(position, total_positions, x_pos, y_pos, 0)
                    
                    # Wait for settling (vibrations to dampen)
                    time.sleep(settle_time)
                    
                    img = self.dialog._get_image_now()
                    
                    if img is not None and out_h > 0:
                        # FLIP IMAGE VERTICALLY - detector view is upside down
                        #img = np.flipud(img)
                        
                        img_h, img_w = img.shape
                        
                        self.log_signal.emit(f"  Got image: {img.shape}, range {img.min()}-{img.max()}")
                        
                        # Calculate position in stitched canvas
                        # CORRECTED: Proper X-Y mapping for row-major array [rows, cols]
                        # X motor (i) → horizontal/columns position
                        # Y motor (j) → vertical/rows position (NO inversion)
                        start_x = i * eff_w  # X motor: columns (left to right)
                        start_y = j * eff_h  # Y motor: rows (top to bottom, no flip)
                        end_x = min(start_x + img_w, out_w)
                        end_y = min(start_y + img_h, out_h)
                        
                        self.log_signal.emit(f"  Placing at row {start_y}:{end_y}, col {start_x}:{end_x}")
                        
                        sub = img[:end_y - start_y, :end_x - start_x]
                        print(end_y - start_y, end_x - start_x)
                        
                        # Update stitched image (thread-safe)
                        self.dialog.stitched_lock.lock()
                        try:
                            # Place image at [row, col] position
                            self.dialog.stitched_image[start_y:end_y, start_x:end_x] = sub
                            print(start_y, end_y, start_x, end_x)
                            # Draw border for visibility
                            border_val = int(np.max(sub)) if sub.size > 0 else 65535
                            thickness = 3
                            for t in range(thickness):
                                if start_y + t < end_y:
                                    self.dialog.stitched_image[start_y + t, start_x:end_x] = border_val
                                if end_y - 1 - t >= start_y:
                                    self.dialog.stitched_image[end_y - 1 - t, start_x:end_x] = border_val
                                if start_x + t < end_x:
                                    self.dialog.stitched_image[start_y:end_y, start_x + t] = border_val
                                if end_x - 1 - t >= start_x:
                                    self.dialog.stitched_image[start_y:end_y, end_x - 1 - t] = border_val
                            
                            self.log_signal.emit(f"  ✓ Stitched! Canvas range now: {self.dialog.stitched_image.min()}-{self.dialog.stitched_image.max()}")
                        finally:
                            self.dialog.stitched_lock.unlock()
                    else:
                        if img is None:
                            self.log_signal.emit(f"  ⚠ Failed to get image from PV!")
                        if out_h == 0:
                            self.log_signal.emit(f"  ⚠ Canvas size is 0!")
                    
                    # Run tomoscan if enabled
                    if self.dialog.run_tomoscan.isChecked():
                        prefix = self.dialog.tomoscan_prefix.text()
                        try:
                            subprocess.run(
                                ['tomoscan', 'single', '--tomoscan-prefix', prefix],
                                capture_output=True,
                                timeout=60
                            )
                        except Exception as e:
                            self.log_signal.emit(f"Tomoscan failed: {e}")
                    
                    self.progress_signal.emit(position, total_positions)
            
            # Force one final display update to show the last image
            QtCore.QMetaObject.invokeMethod(self.dialog, '_refresh_stitched_preview', QtCore.Qt.QueuedConnection)
            
            self.log_signal.emit(f"\nScan complete! Total positions: {position}")
            
        except Exception as e:
            self.log_signal.emit(f"\n✗ Scan failed with error: {e}")
            import traceback
            self.log_signal.emit(traceback.format_exc())
        finally:
            # ALWAYS emit finished signal to re-enable UI
            self.finished_signal.emit()


# ==================== Standalone Mode ====================
def main():
    """Run the motor scan dialog as a standalone application"""
    import sys
    
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Mosalign")
    
    # Apply dark theme
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(25, 25, 25))
    palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor(127, 127, 127))
    
    app.setPalette(palette)
    
    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            font-weight: bold;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QSpinBox, QDoubleSpinBox, QLineEdit {
            background-color: #2a2a2a;
            border: 1px solid #555;
            border-radius: 3px;
            padding: 3px;
            min-height: 20px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
            border: 1px solid #2a82da;
        }
        QPushButton {
            background-color: #454545;
            border: 1px solid #666;
            border-radius: 4px;
            padding: 6px 16px;
            min-width: 80px;
        }
        QPushButton:hover {
            background-color: #505050;
            border: 1px solid #888;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton:disabled {
            background-color: #353535;
            color: #666;
        }
        QProgressBar {
            border: 1px solid #555;
            border-radius: 3px;
            text-align: center;
            background-color: #2a2a2a;
        }
        QProgressBar::chunk {
            background-color: #2a82da;
            border-radius: 2px;
        }
        QCheckBox {
            color: #e0e0e0;
            spacing: 5px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #555;
            border-radius: 3px;
            background-color: #2a2a2a;
        }
        QCheckBox::indicator:checked {
            background-color: #2a82da;
            border: 1px solid #3a95d8;
        }
    """)
    
    dialog = MotorScanDialog()
    dialog.show()
    
    # Ensure proper cleanup on exit
    app.aboutToQuit.connect(lambda: dialog.close())
    
    ret = app.exec_()
    
    # Force cleanup of any remaining threads
    QtCore.QThreadPool.globalInstance().waitForDone(1000)
    
    sys.exit(ret)


if __name__ == '__main__':
    main()
