#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mosalign - Motor Scan Plugin for PyStream
------------------------------------------
Performs 2D motor scan with live stitched preview.

Features:
- X-Y motor grid scan with image stitching
- Tomoscan integration at each position
- Test mode for offline development
"""

import logging
import subprocess
import time
import numpy as np
from typing import Optional
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
pg.setConfigOptions(imageAxisOrder='row-major')


class MotorScanDialog(QtWidgets.QDialog):
    """Dialog for configuring and running 2D motor scans"""

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.scanning = False
        self.scan_thread = None
        self.current_image = None

        # For stitched preview
        self.stitched_image = None
        self.stitched_lock = QtCore.QMutex()

        # Test/Mock mode
        self.test_mode = False

        # Timer to refresh preview during scan
        self.preview_timer = QtCore.QTimer()
        self.preview_timer.timeout.connect(self._refresh_stitched_preview)

        self.setWindowTitle("Mosalign")
        self.resize(1200, 800)

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)

        # Left panel - Controls
        left_panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(left_panel)

        # Motor PVs group
        pv_group = QtWidgets.QGroupBox("Motor PVs")
        pv_layout = QtWidgets.QFormLayout()

        self.motor1_pv = QtWidgets.QLineEdit("2bmb:m17")
        self.motor2_pv = QtWidgets.QLineEdit("2bmHXP:m3")
        self.tomoscan_path = QtWidgets.QLineEdit("tomoscan")

        pv_layout.addRow("Motor 1 (X):", self.motor1_pv)
        pv_layout.addRow("Motor 2 (Y):", self.motor2_pv)
        pv_layout.addRow("Tomoscan Path:", self.tomoscan_path)

        pv_group.setLayout(pv_layout)
        layout.addWidget(pv_group)

        # Scan parameters group
        params_group = QtWidgets.QGroupBox("Scan Parameters")
        params_layout = QtWidgets.QGridLayout()

        # Headers
        params_layout.addWidget(QtWidgets.QLabel("<b>Axis</b>"), 0, 0)
        params_layout.addWidget(QtWidgets.QLabel("<b>Start</b>"), 0, 1)
        params_layout.addWidget(QtWidgets.QLabel("<b>Step</b>"), 0, 2)
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

        # Settings group
        settings_group = QtWidgets.QGroupBox("Settings")
        settings_layout = QtWidgets.QFormLayout()

        # Test mode checkbox
        self.test_mode_checkbox = QtWidgets.QCheckBox("Test Mode (Mock PVs/Tomoscan)")
        self.test_mode_checkbox.toggled.connect(self._toggle_test_mode)
        settings_layout.addRow("", self.test_mode_checkbox)

        self.pixel_size = QtWidgets.QDoubleSpinBox()
        self.pixel_size.setRange(0.001, 100)
        self.pixel_size.setDecimals(3)
        self.pixel_size.setValue(1.0)
        self.pixel_size.setSuffix(" µm")
        settings_layout.addRow("Pixel Size:", self.pixel_size)

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
        settings_layout.addRow("Motor Tolerance:", self.motor_tolerance)

        self.caput_timeout = QtWidgets.QDoubleSpinBox()
        self.caput_timeout.setRange(1, 300)
        self.caput_timeout.setValue(10.0)
        self.caput_timeout.setSuffix(" s")
        settings_layout.addRow("Caput Timeout:", self.caput_timeout)

        self.run_tomoscan = QtWidgets.QCheckBox("Run tomoscan at each position")
        settings_layout.addRow("", self.run_tomoscan)

        self.tomoscan_prefix = QtWidgets.QLineEdit("2bmb:TomoScan:")
        settings_layout.addRow("Tomoscan Prefix:", self.tomoscan_prefix)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Image PV settings
        image_group = QtWidgets.QGroupBox("Camera PV")
        image_layout = QtWidgets.QVBoxLayout()

        self.image_pv = QtWidgets.QLineEdit("2bmbSP1:Pva1:Image")
        image_layout.addWidget(QtWidgets.QLabel("Image PV:"))
        image_layout.addWidget(self.image_pv)

        self.connection_status = QtWidgets.QLabel("Status: Not connected")
        image_layout.addWidget(self.connection_status)

        image_group.setLayout(image_layout)
        layout.addWidget(image_group)

        # Preview settings
        self.enable_preview = QtWidgets.QCheckBox("Enable Live Preview")
        self.enable_preview.setChecked(True)
        layout.addWidget(self.enable_preview)

        self.auto_contrast = QtWidgets.QCheckBox("Auto Contrast")
        self.auto_contrast.setChecked(True)
        layout.addWidget(self.auto_contrast)

        layout.addStretch()

        # Action buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.start_btn = QtWidgets.QPushButton("Start Scan")
        self.start_btn.setAutoDefault(False)  # Prevent Enter from triggering
        self.start_btn.setDefault(False)
        self.start_btn.clicked.connect(self._start_scan)
        button_layout.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setAutoDefault(False)  # Prevent Enter from triggering
        self.stop_btn.setDefault(False)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_scan)
        button_layout.addWidget(self.stop_btn)

        layout.addLayout(button_layout)

        # Progress
        self.progress = QtWidgets.QProgressBar()
        layout.addWidget(self.progress)

        self.position_label = QtWidgets.QLabel("Position: -")
        layout.addWidget(self.position_label)

        main_layout.addWidget(left_panel, 1)

        # Right panel - Image preview & log
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)

        # Image view
        right_layout.addWidget(QtWidgets.QLabel("Live Preview (Stitched Mosaic)"))

        self.graphics_view = pg.GraphicsLayoutWidget()
        self.view_box = self.graphics_view.addViewBox()
        self.view_box.setAspectLocked(True)
        self.image_view = pg.ImageItem()
        self.view_box.addItem(self.image_view)

        right_layout.addWidget(self.graphics_view, 2)

        # Log output
        right_layout.addWidget(QtWidgets.QLabel("Scan Log"))

        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        right_layout.addWidget(self.log_output, 1)

        main_layout.addWidget(right_panel, 2)

    def _load_config(self):
        """Load settings from config file"""
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

    def _toggle_test_mode(self, checked: bool):
        """Toggle test/mock mode"""
        self.test_mode = checked
        if checked:
            self._log("Test Mode ENABLED - using mock PVs and tomoscan")
            self.connection_status.setText("Test Mode: Mock camera enabled")
        else:
            self._log("Test Mode DISABLED - using real PVs and tomoscan")
            self.connection_status.setText("Status: Not connected")

    def _generate_mock_image(self, position_index: int, total_positions: int):
        """Generate a mock image for testing"""
        img_h, img_w = 1024, 1280

        # Create base gradient
        y_grad = np.linspace(0, 1, img_h)[:, np.newaxis]
        x_grad = np.linspace(0, 1, img_w)[np.newaxis, :]

        # Position-dependent pattern
        pattern = (np.sin(x_grad * 10 + position_index) * 0.3 +
                  np.cos(y_grad * 8 + position_index * 0.5) * 0.3 +
                  0.4)

        # Add circular features
        center_y, center_x = img_h // 2, img_w // 2
        y_coords = np.arange(img_h)[:, np.newaxis] - center_y
        x_coords = np.arange(img_w)[np.newaxis, :] - center_x
        radius = np.sqrt(x_coords**2 + y_coords**2)
        circle_pattern = np.exp(-radius / 300) * 0.3

        # Combine patterns
        img = pattern + circle_pattern

        # Add noise
        noise = np.random.normal(0, 0.05, (img_h, img_w))
        img = img + noise

        # Normalize to uint16 range
        img = np.clip(img, 0, 1)
        img = (img * 40000 + 5000).astype(np.uint16)

        return img

    def _log(self, message: str):
        """Add message to log"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")
        if self.logger:
            self.logger.info(message)

    def _refresh_stitched_preview(self):
        """Refresh the stitched mosaic display"""
        if not self.enable_preview.isChecked():
            return

        self.stitched_lock.lock()
        try:
            if self.stitched_image is not None:
                # Flip vertically to correct display orientation
                img = np.flipud(self.stitched_image.copy())

                # Auto-range only on first update
                auto_range = not hasattr(self, '_preview_initialized')
                if auto_range:
                    self._preview_initialized = True

                # Use percentile-based contrast
                if self.auto_contrast.isChecked():
                    nz = img[img > 0]
                    if nz.size > 0:
                        vmin, vmax = np.percentile(nz, [1, 99])
                    else:
                        vmin, vmax = 0, 65535

                    self.image_view.setImage(img, levels=[vmin, vmax])
                    if auto_range:
                        self.view_box.autoRange()
                else:
                    self.image_view.setImage(img)
                    if auto_range:
                        self.view_box.autoRange()
        finally:
            self.stitched_lock.unlock()

    def _get_image_now(self, position_index: int = 1, total_positions: int = 1):
        """Get image from PV - supports test mode

        Thread-safe method that gets image from parent viewer to avoid pvapy segfaults.
        Uses retry logic and careful numpy array handling for thread safety.
        """
        # TEST MODE: Return mock image
        if self.test_mode:
            return self._generate_mock_image(position_index, total_positions)

        # REAL MODE: Get from parent viewer's current image
        # This completely avoids pvapy segfault issues by reusing the parent's connection
        try:
            parent = self.parent()

            # Verify parent exists
            if not parent:
                self._log(f"⚠ No parent viewer available")
                return None

            # Try up to 3 times with small delays to handle timing issues
            for attempt in range(3):
                try:
                    if not hasattr(parent, '_last_display_img'):
                        self._log(f"⚠ Parent viewer does not have _last_display_img attribute")
                        return None

                    img_ref = parent._last_display_img

                    if img_ref is None:
                        if attempt < 2:
                            time.sleep(0.05)  # Wait for next frame
                            continue
                        else:
                            self._log(f"⚠ No image available from main viewer after retries")
                            self._log(f"   Please ensure the main viewer is connected and receiving images")
                            return None

                    # Thread-safe copy using np.array() instead of .copy()
                    # This creates a deep copy that's independent of the parent's array
                    img = np.array(img_ref, dtype=img_ref.dtype)

                    if img.size == 0:
                        self._log(f"⚠ Empty image from main viewer")
                        return None

                    self._log(f"✓ Got image from main viewer ({img.shape[1]}x{img.shape[0]})")
                    return img

                except (AttributeError, RuntimeError, ValueError) as e:
                    if attempt < 2:
                        self._log(f"⚠ Retry {attempt + 1}/3: {e}")
                        time.sleep(0.05)
                        continue
                    else:
                        self._log(f"⚠ Could not copy viewer image after retries: {e}")
                        return None

            return None

        except KeyboardInterrupt:
            raise
        except Exception as e:
            self._log(f"⚠ Unexpected error getting image: {e}")
            import traceback
            self._log(traceback.format_exc())
            return None

    def _caput(self, pv: str, value: float, timeout: float):
        """Set motor position using caput - supports test mode"""
        # TEST MODE: Just log the action
        if self.test_mode:
            self._log(f"  [MOCK] caput {pv} {value}")
            return

        # REAL MODE: Execute caput
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

    def _wait_for_motor(self, pv: str, target: float, tolerance: float = 0.001, timeout: float = 30.0):
        """Wait for motor to reach target position - supports test mode"""
        # TEST MODE: Simulate instant motor arrival
        if self.test_mode:
            time.sleep(0.05)
            return True

        # REAL MODE: Wait for motor
        readback_pv = f"{pv}.RBV"
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            try:
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

            except (subprocess.TimeoutExpired, ValueError) as e:
                self._log(f"  Warning: Error reading {readback_pv}: {e}")

            time.sleep(0.1)

        self._log(f"⚠ Motor {pv} timeout")
        return False

    def _start_scan(self):
        """Start the 2D motor scan"""
        self.scanning = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)

        # Reset preview initialization
        if hasattr(self, '_preview_initialized'):
            delattr(self, '_preview_initialized')

        # Start preview refresh timer
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

    def closeEvent(self, event):
        """Clean up when dialog is closed"""
        self.scanning = False

        # Save settings
        self._save_config()

        if self.preview_timer.isActive():
            self.preview_timer.stop()

        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.quit()
            self.scan_thread.wait(1000)
            if self.scan_thread.isRunning():
                self.scan_thread.terminate()

        event.accept()


class ScanWorker(QtCore.QThread):
    """Worker thread for running the scan"""
    progress_signal = QtCore.pyqtSignal(int, int)
    log_signal = QtCore.pyqtSignal(str)
    position_signal = QtCore.pyqtSignal(int, int, float, float, float)
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
            timeout = self.dialog.caput_timeout.value()

            total_positions = x_step_size * y_step_size
            position = 0

            # Move to start position
            self.log_signal.emit(f"Moving to start: X={x_start:.3f}, Y={y_start:.3f}")
            self.dialog._caput(motor1_pv, x_start, timeout)
            time.sleep(0.1)
            self.dialog._caput(motor2_pv, y_start, timeout)
            time.sleep(settle_time if not self.dialog.test_mode else 0.1)

            # Get test image to determine canvas size
            self.log_signal.emit("Getting test image...")
            test_img = self.dialog._get_image_now(0, total_positions)

            if test_img is not None:
                img_h, img_w = test_img.shape

                # Calculate effective step size in pixels
                pixel_size_um = self.dialog.pixel_size.value()
                x_step_um = x_step * 1000
                y_step_um = y_step * 1000

                eff_w = int(x_step_um / pixel_size_um)
                eff_h = int(y_step_um / pixel_size_um)

                # Total canvas size
                out_w = eff_w * x_step_size + (img_w - eff_w)
                out_h = eff_h * y_step_size + (img_h - eff_h)

                self.log_signal.emit(
                    f"Canvas: {out_w}×{out_h}, Image: {img_w}×{img_h}, Step: {eff_w}×{eff_h}px"
                )
            else:
                self.log_signal.emit("⚠ Failed to get test image!")
                return

            # Initialize stitched canvas
            self.dialog.stitched_lock.lock()
            self.dialog.stitched_image = np.zeros((out_h, out_w), dtype=np.uint16)
            self.dialog.stitched_lock.unlock()

            # Scan X-Y grid
            for i in range(x_step_size):
                if not self.dialog.scanning:
                    break

                for j in range(y_step_size):
                    if not self.dialog.scanning:
                        break

                    # Motor positions
                    x_pos = x_start + (i * x_step)
                    y_pos = y_start + (j * y_step)

                    position += 1

                    self.log_signal.emit(
                        f"[{position}/{total_positions}] X={x_pos:.3f}, Y={y_pos:.3f}"
                    )

                    # Move motors
                    if not self.dialog.test_mode:
                        try:
                            subprocess.run(['caput', motor1_pv, str(x_pos)],
                                         capture_output=True, timeout=5)
                            subprocess.run(['caput', motor2_pv, str(y_pos)],
                                         capture_output=True, timeout=5)
                        except Exception as e:
                            self.log_signal.emit(f"  ⚠ Motor error: {e}")

                    # Wait for motors
                    self.dialog._wait_for_motor(motor1_pv, x_pos, motor_tolerance, timeout)
                    self.dialog._wait_for_motor(motor2_pv, y_pos, motor_tolerance, timeout)

                    # Update position display
                    self.position_signal.emit(position, total_positions, x_pos, y_pos, 0)

                    # Wait for settling
                    time.sleep(0.1 if self.dialog.test_mode else settle_time)

                    # Capture preview image
                    img = self.dialog._get_image_now(position, total_positions)

                    if img is not None:
                        self._place_image_in_canvas(img, i, j, eff_w, eff_h, out_w, out_h)

                    # Run tomoscan if enabled
                    if self.dialog.run_tomoscan.isChecked():
                        self._run_tomoscan_at_position(
                            x_pos, y_pos, i, j, position, total_positions,
                            eff_w, eff_h, out_w, out_h, motor1_pv, motor2_pv
                        )

                    self.progress_signal.emit(position, total_positions)

            self.log_signal.emit(f"Scan complete! Total positions: {position}")

        except Exception as e:
            self.log_signal.emit(f"✗ Scan failed: {e}")
            import traceback
            self.log_signal.emit(traceback.format_exc())
        finally:
            self.finished_signal.emit()

    def _place_image_in_canvas(self, img, i, j, eff_w, eff_h, out_w, out_h):
        """Place image in stitched canvas"""
        img_h, img_w = img.shape

        # Calculate position
        start_x = i * eff_w
        start_y = j * eff_h
        end_x = min(start_x + img_w, out_w)
        end_y = min(start_y + img_h, out_h)

        sub = img[:end_y - start_y, :end_x - start_x]

        # Update stitched image
        self.dialog.stitched_lock.lock()
        try:
            self.dialog.stitched_image[start_y:end_y, start_x:end_x] = sub

            # Draw border
            border_val = int(np.max(sub)) if sub.size > 0 else 65535
            for t in range(3):
                if start_y + t < end_y:
                    self.dialog.stitched_image[start_y + t, start_x:end_x] = border_val
                if end_y - 1 - t >= start_y:
                    self.dialog.stitched_image[end_y - 1 - t, start_x:end_x] = border_val
                if start_x + t < end_x:
                    self.dialog.stitched_image[start_y:end_y, start_x + t] = border_val
                if end_x - 1 - t >= start_x:
                    self.dialog.stitched_image[start_y:end_y, end_x - 1 - t] = border_val
        finally:
            self.dialog.stitched_lock.unlock()

    def _run_tomoscan_at_position(self, x_pos, y_pos, i, j, position, total_positions,
                                   eff_w, eff_h, out_w, out_h, motor1_pv, motor2_pv):
        """Run tomoscan at current position"""
        prefix = self.dialog.tomoscan_prefix.text().strip()
        tomoscan_cmd = self.dialog.tomoscan_path.text().strip()

        # Build full command for logging
        full_cmd = f"{tomoscan_cmd} single --tomoscan-prefix {prefix}"

        self.log_signal.emit(f"  Starting tomoscan at ({x_pos:.3f}, {y_pos:.3f})...")
        self.log_signal.emit(f"  Command: {full_cmd}")

        try:
            # Store absolute positions (tomoscan zeros motors)
            abs_x_pos = x_pos
            abs_y_pos = y_pos

            # Run tomoscan
            if self.dialog.test_mode:
                self.log_signal.emit(f"  [MOCK MODE - not actually running]")
                time.sleep(0.5)
                result_returncode = 0
            else:
                result = subprocess.run(
                    [tomoscan_cmd, 'single', '--tomoscan-prefix', prefix],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                result_returncode = result.returncode

            if result_returncode == 0:
                self.log_signal.emit("  ✓ Tomoscan completed")

                # Wait for first projection
                time.sleep(0.5 if self.dialog.test_mode else 1.0)

                # Capture first projection (different pattern)
                tomo_img = self.dialog._get_image_now(position + 1000, total_positions)

                if tomo_img is not None:
                    self.log_signal.emit("  Got tomoscan projection")
                    self._place_image_in_canvas(tomo_img, i, j, eff_w, eff_h, out_w, out_h)
                    self.log_signal.emit("  ✓ Placed in preview")
                else:
                    self.log_signal.emit("  ⚠ Could not capture projection")

                # Restore motor positions (tomoscan zeros motors during rotation)
                self.log_signal.emit(f"  Restoring motors to grid position X={abs_x_pos:.3f}, Y={abs_y_pos:.3f}")
                if self.dialog.test_mode:
                    self.log_signal.emit(f"  [MOCK MODE - not actually moving motors]")
                else:
                    subprocess.run(['caput', motor1_pv, str(abs_x_pos)],
                                 capture_output=True, timeout=5)
                    subprocess.run(['caput', motor2_pv, str(abs_y_pos)],
                                 capture_output=True, timeout=5)
                    self.log_signal.emit(f"  ✓ Motors restored")
                time.sleep(0.2)

            else:
                if not self.dialog.test_mode:
                    self.log_signal.emit("  ✗ Tomoscan failed")

        except subprocess.TimeoutExpired:
            self.log_signal.emit("  ✗ Tomoscan timeout")
        except Exception as e:
            self.log_signal.emit(f"  ✗ Tomoscan error: {e}")


def main():
    """Run mosalign as standalone application"""
    import sys

    app = QtWidgets.QApplication(sys.argv)

    # Apply basic styling
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
    app.setPalette(palette)

    dialog = MotorScanDialog()
    dialog.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
