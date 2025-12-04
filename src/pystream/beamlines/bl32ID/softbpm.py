"""
SoftBPM (Software Beam Position Monitor) Plugin for bl32ID

Monitors beam-normalized image intensity during data acquisition and
automatically adjusts motors to maximize intensity when it drops beyond threshold.

Features:
- Normalizes intensity by storage ring beam current (S:SRcurrentAI)
- Detects intensity drops exceeding configurable threshold
- Moves motors to restore and maximize beam intensity
- Continuous monitoring during /exchange/data_white acquisition
- Test mode for safe observation without motor movements
"""

import time
import subprocess
import logging
import numpy as np
from typing import Optional
from PyQt5 import QtWidgets, QtCore
import pvaccess as pva


class SoftBPMDialog(QtWidgets.QDialog):
    """Dialog for monitoring image intensity and controlling motors."""

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("SoftBPM - bl32ID")
        self.resize(750, 900)

        self.monitor_thread = None
        self.is_monitoring = False
        self.last_intensity = None

        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Title and description
        title = QtWidgets.QLabel("SoftBPM")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        desc = QtWidgets.QLabel(
            "Monitors beam-normalized image intensity during data acquisition.\n"
            "Automatically adjusts motors to maximize intensity when it drops beyond threshold."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status section
        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout()

        self.status_label = QtWidgets.QLabel("Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; color: gray;")
        status_layout.addWidget(self.status_label)

        self.beam_current_label = QtWidgets.QLabel("Beam Current: N/A")
        status_layout.addWidget(self.beam_current_label)

        self.last_intensity_label = QtWidgets.QLabel("Last Normalized Intensity: N/A")
        status_layout.addWidget(self.last_intensity_label)

        self.current_intensity_label = QtWidgets.QLabel("Current Normalized Intensity: N/A")
        status_layout.addWidget(self.current_intensity_label)

        self.change_label = QtWidgets.QLabel("Change: N/A")
        status_layout.addWidget(self.change_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Create tabs for settings and PV configuration
        tabs = QtWidgets.QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #cccccc;
                background: white;
            }
            QTabBar::tab {
                background: #333333;
                color: white;
                border: 1px solid #555555;
                padding: 8px 20px;
                margin-right: 2px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #000000;
                color: white;
                border-bottom: 2px solid white;
            }
            QTabBar::tab:hover {
                background: #555555;
                color: white;
            }
        """)

        # Tab 1: Numeric Settings (all values)
        settings_tab = QtWidgets.QWidget()
        settings_tab_layout = QtWidgets.QVBoxLayout(settings_tab)

        self.settings_table = QtWidgets.QTableWidget(5, 2)
        self.settings_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.settings_table.horizontalHeader().setStretchLastSection(True)
        self.settings_table.verticalHeader().setVisible(False)
        self.settings_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.settings_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # Row 0: Threshold percentage
        self.settings_table.setItem(0, 0, QtWidgets.QTableWidgetItem("Threshold (%)"))
        self.threshold_input = QtWidgets.QDoubleSpinBox()
        self.threshold_input.setRange(0.1, 100.0)
        self.threshold_input.setValue(10.0)
        self.threshold_input.setSuffix(" %")
        self.settings_table.setCellWidget(0, 1, self.threshold_input)

        # Row 1: Test Mode checkbox
        self.settings_table.setItem(1, 0, QtWidgets.QTableWidgetItem("Test Mode (no motors)"))
        self.test_mode_checkbox = QtWidgets.QCheckBox()
        self.test_mode_checkbox.setChecked(False)
        self.test_mode_checkbox.setToolTip("Monitor and plot intensity without moving motors")
        self.settings_table.setCellWidget(1, 1, self.test_mode_checkbox)

        # Row 2: Polling interval
        self.settings_table.setItem(2, 0, QtWidgets.QTableWidgetItem("Poll Interval (s)"))
        self.poll_interval_input = QtWidgets.QDoubleSpinBox()
        self.poll_interval_input.setRange(0.1, 60.0)
        self.poll_interval_input.setValue(1.0)
        self.poll_interval_input.setSuffix(" s")
        self.settings_table.setCellWidget(2, 1, self.poll_interval_input)

        # Row 3: Motor 1 Step
        self.settings_table.setItem(3, 0, QtWidgets.QTableWidgetItem("Motor 1 Step"))
        self.motor1_step = QtWidgets.QDoubleSpinBox()
        self.motor1_step.setRange(-1000.0, 1000.0)
        self.motor1_step.setValue(0.1)
        self.motor1_step.setDecimals(4)
        self.settings_table.setCellWidget(3, 1, self.motor1_step)

        # Row 4: Motor 2 Step
        self.settings_table.setItem(4, 0, QtWidgets.QTableWidgetItem("Motor 2 Step"))
        self.motor2_step = QtWidgets.QDoubleSpinBox()
        self.motor2_step.setRange(-1000.0, 1000.0)
        self.motor2_step.setValue(0.1)
        self.motor2_step.setDecimals(4)
        self.settings_table.setCellWidget(4, 1, self.motor2_step)

        # Resize table to fit content without scrollbars
        self.settings_table.resizeRowsToContents()
        self.settings_table.setFixedHeight(
            self.settings_table.horizontalHeader().height() +
            sum(self.settings_table.rowHeight(i) for i in range(self.settings_table.rowCount())) + 2
        )

        settings_tab_layout.addWidget(self.settings_table)
        settings_tab_layout.addStretch()
        tabs.addTab(settings_tab, "Settings")

        # Tab 2: PV Names
        pv_tab = QtWidgets.QWidget()
        pv_tab_layout = QtWidgets.QVBoxLayout(pv_tab)

        self.pv_table = QtWidgets.QTableWidget(4, 2)
        self.pv_table.setHorizontalHeaderLabels(["PV Name", "Value"])
        self.pv_table.horizontalHeader().setStretchLastSection(True)
        self.pv_table.verticalHeader().setVisible(False)
        self.pv_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.pv_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # Row 0: HDF5 Location PV
        self.pv_table.setItem(0, 0, QtWidgets.QTableWidgetItem("HDF5 Location PV"))
        self.hdf5_location_pv = QtWidgets.QLineEdit("32id:TomoScan:HDF5Location")
        self.pv_table.setCellWidget(0, 1, self.hdf5_location_pv)

        # Row 1: Image PV
        self.pv_table.setItem(1, 0, QtWidgets.QTableWidgetItem("Image PV"))
        self.image_pv_input = QtWidgets.QLineEdit("32idcPG3:Pva1:Image")
        self.pv_table.setCellWidget(1, 1, self.image_pv_input)

        # Row 2: Beam current PV
        self.pv_table.setItem(2, 0, QtWidgets.QTableWidgetItem("Beam Current PV"))
        self.beam_current_pv_input = QtWidgets.QLineEdit("S:SRcurrentAI")
        self.pv_table.setCellWidget(2, 1, self.beam_current_pv_input)

        # Row 3: Motor 1 PV
        self.pv_table.setItem(3, 0, QtWidgets.QTableWidgetItem("Motor 1 PV"))
        self.motor1_pv = QtWidgets.QLineEdit("32idb:m1")
        self.pv_table.setCellWidget(3, 1, self.motor1_pv)

        # Row 4: Motor 2 PV
        self.pv_table.setRowCount(5)
        self.pv_table.setItem(4, 0, QtWidgets.QTableWidgetItem("Motor 2 PV"))
        self.motor2_pv = QtWidgets.QLineEdit("32idb:m2")
        self.pv_table.setCellWidget(4, 1, self.motor2_pv)

        # Resize table to fit content without scrollbars
        self.pv_table.resizeRowsToContents()
        self.pv_table.setFixedHeight(
            self.pv_table.horizontalHeader().height() +
            sum(self.pv_table.rowHeight(i) for i in range(self.pv_table.rowCount())) + 2
        )

        pv_tab_layout.addWidget(self.pv_table)
        pv_tab_layout.addStretch()
        tabs.addTab(pv_tab, "PV Names")

        # Add tabs widget to main layout
        layout.addWidget(tabs)

        # Log area
        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Plot area for intensity over time
        plot_group = QtWidgets.QGroupBox("Intensity Plot")
        plot_layout = QtWidgets.QVBoxLayout()

        try:
            import pyqtgraph as pg
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setLabel('left', 'Normalized Intensity')
            self.plot_widget.setLabel('bottom', 'Time (s)')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_widget.setMinimumHeight(200)

            # Data arrays for plotting
            self.time_data = []
            self.intensity_data = []
            self.plot_curve = self.plot_widget.plot(pen='y', width=2)

            plot_layout.addWidget(self.plot_widget)
            self.has_plot = True
        except ImportError:
            no_plot_label = QtWidgets.QLabel("PyQtGraph not available for plotting")
            plot_layout.addWidget(no_plot_label)
            self.has_plot = False

        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)

        # Control buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.start_button = QtWidgets.QPushButton("Start Monitoring")
        self.start_button.clicked.connect(self._start_monitoring)
        button_layout.addWidget(self.start_button)

        self.stop_button = QtWidgets.QPushButton("Stop Monitoring")
        self.stop_button.clicked.connect(self._stop_monitoring)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        self.reset_button = QtWidgets.QPushButton("Reset Reference")
        self.reset_button.clicked.connect(self._reset_reference)
        button_layout.addWidget(self.reset_button)

        button_layout.addStretch()

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def _log_message(self, message: str):
        """Add a message to the log with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def _start_monitoring(self):
        """Start the monitoring thread."""
        if self.is_monitoring:
            return

        self.is_monitoring = True
        self.last_intensity = None

        # Clear plot data
        if self.has_plot:
            self.time_data = []
            self.intensity_data = []
            self.start_time = time.time()

        self.monitor_thread = SoftBPMThread(
            hdf5_location_pv=self.hdf5_location_pv.text(),
            image_pv=self.image_pv_input.text(),
            beam_current_pv=self.beam_current_pv_input.text(),
            motor1_pv=self.motor1_pv.text(),
            motor1_step=self.motor1_step.value(),
            motor2_pv=self.motor2_pv.text(),
            motor2_step=self.motor2_step.value(),
            threshold_percent=self.threshold_input.value(),
            poll_interval=self.poll_interval_input.value(),
            test_mode=self.test_mode_checkbox.isChecked(),
            parent_dialog=self
        )

        self.monitor_thread.status_update.connect(self._update_status)
        self.monitor_thread.intensity_update.connect(self._update_intensity)
        self.monitor_thread.log_message.connect(self._log_message)
        self.monitor_thread.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Status: Monitoring")
        self.status_label.setStyleSheet("font-weight: bold; color: green;")
        self._log_message("Monitoring started")

    def _stop_monitoring(self):
        """Stop the monitoring thread."""
        if not self.is_monitoring:
            return

        self.is_monitoring = False

        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
            self.monitor_thread = None

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")
        self._log_message("Monitoring stopped")

    def _reset_reference(self):
        """Reset the reference intensity value."""
        self.last_intensity = None
        if self.monitor_thread:
            self.monitor_thread.last_normalized_intensity = None
        self.last_intensity_label.setText("Last Normalized Intensity: N/A")
        self.change_label.setText("Change: N/A")
        self._log_message("Reference intensity reset")

    def _update_status(self, status: str):
        """Update the status label."""
        self.status_label.setText(f"Status: {status}")

    def _update_intensity(self, last_intensity: Optional[float],
                          current_intensity: float,
                          change_percent: float,
                          beam_current: float):
        """Update intensity display and plot."""
        self.beam_current_label.setText(f"Beam Current: {beam_current:.3f} mA")

        if last_intensity is not None:
            self.last_intensity_label.setText(f"Last Normalized Intensity: {last_intensity:.2f}")
            self.change_label.setText(f"Change: {change_percent:+.2f}%")

            # Color code the change - red if intensity dropped (bad), green if stable/increased
            if change_percent < -self.threshold_input.value():
                self.change_label.setStyleSheet("color: red; font-weight: bold;")
            else:
                self.change_label.setStyleSheet("color: green;")
        else:
            self.last_intensity_label.setText("Last Normalized Intensity: N/A (establishing reference)")

        self.current_intensity_label.setText(f"Current Normalized Intensity: {current_intensity:.2f}")

        # Update plot
        if self.has_plot and hasattr(self, 'start_time'):
            elapsed_time = time.time() - self.start_time
            self.time_data.append(elapsed_time)
            self.intensity_data.append(current_intensity)

            # Keep only last 1000 points to avoid memory issues
            if len(self.time_data) > 1000:
                self.time_data = self.time_data[-1000:]
                self.intensity_data = self.intensity_data[-1000:]

            # Update plot curve
            self.plot_curve.setData(self.time_data, self.intensity_data)

    def _load_settings(self):
        """Load settings from config file."""
        pass

    def _save_settings(self):
        """Save settings to config file."""
        pass

    def closeEvent(self, event):
        """Handle dialog close event."""
        if self.is_monitoring:
            reply = QtWidgets.QMessageBox.question(
                self,
                'Stop Monitoring?',
                'Monitoring is active. Stop monitoring and close?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )

            if reply == QtWidgets.QMessageBox.Yes:
                self._stop_monitoring()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


class SoftBPMThread(QtCore.QThread):
    """Background thread for monitoring intensity and controlling motors."""

    status_update = QtCore.pyqtSignal(str)
    intensity_update = QtCore.pyqtSignal(object, float, float, float)  # last, current, change%, beam_current
    log_message = QtCore.pyqtSignal(str)

    def __init__(self, hdf5_location_pv: str, image_pv: str, beam_current_pv: str,
                 motor1_pv: str, motor1_step: float,
                 motor2_pv: str, motor2_step: float,
                 threshold_percent: float, poll_interval: float,
                 test_mode: bool = False,
                 parent_dialog=None):
        super().__init__()
        self.hdf5_location_pv = hdf5_location_pv
        self.image_pv = image_pv
        self.beam_current_pv = beam_current_pv
        self.motor1_pv = motor1_pv
        self.motor1_step = motor1_step
        self.motor2_pv = motor2_pv
        self.motor2_step = motor2_step
        self.threshold_percent = threshold_percent
        self.poll_interval = poll_interval
        self.test_mode = test_mode
        self.parent_dialog = parent_dialog

        self.last_normalized_intensity = None
        self.running = False
        self.logger = logging.getLogger(__name__)

        # Create PVA channel for image data (reuse for performance)
        self.image_channel = None
        try:
            self.image_channel = pva.Channel(self.image_pv)
            self.logger.info(f"PVA channel created for {self.image_pv}")
        except Exception as e:
            self.logger.warning(f"Failed to create PVA channel: {e}, will use fallback")

    def run(self):
        """Main monitoring loop."""
        self.running = True
        mode_str = "[TEST MODE - Motors disabled]" if self.test_mode else "[ACTIVE - Motors enabled]"
        self.log_message.emit(f"Starting monitoring loop {mode_str}")

        while self.running:
            try:
                # Check HDF5 location
                location = self._get_pv_value(self.hdf5_location_pv)

                if location and location.strip() == "/exchange/data_white":
                    mode_indicator = " [TEST MODE]" if self.test_mode else ""
                    self.status_update.emit(f"Monitoring (HDF5 at /exchange/data_white){mode_indicator}")

                    # Get beam current for normalization
                    beam_current = self._get_beam_current()
                    if beam_current is None or beam_current <= 0:
                        self.log_message.emit("Warning: Invalid beam current, skipping measurement")
                        continue

                    # Get current image average
                    raw_intensity = self._get_image_average()

                    if raw_intensity is not None:
                        # Normalize by beam current
                        normalized_intensity = raw_intensity / beam_current

                        if self.last_normalized_intensity is None:
                            # First measurement - establish reference
                            self.last_normalized_intensity = normalized_intensity
                            self.intensity_update.emit(None, normalized_intensity, 0.0, beam_current)
                            self.log_message.emit(
                                f"Reference intensity established: {normalized_intensity:.2f} "
                                f"(raw: {raw_intensity:.1f}, current: {beam_current:.3f} mA)"
                            )
                        else:
                            # Calculate change percentage
                            change_percent = ((normalized_intensity - self.last_normalized_intensity) /
                                            self.last_normalized_intensity * 100.0)

                            # Skip images with intensity below 70% of reference (likely empty/first images)
                            if change_percent < -30.0:  # Less than 70% of reference
                                self.log_message.emit(
                                    f"Skipping low intensity image: {change_percent:+.2f}% "
                                    f"(below 70% threshold, likely empty image)"
                                )
                                continue

                            self.intensity_update.emit(
                                self.last_normalized_intensity,
                                normalized_intensity,
                                change_percent,
                                beam_current
                            )

                            # Check if intensity dropped beyond threshold (optimization needed)
                            if change_percent < -self.threshold_percent:
                                if self.test_mode:
                                    # Test mode: only log, don't move motors
                                    self.log_message.emit(
                                        f"[TEST MODE] Intensity dropped! Change: {change_percent:+.2f}% "
                                        f"(threshold: -{self.threshold_percent}%) - Motors NOT moved"
                                    )
                                else:
                                    # Production mode: move motors
                                    self.log_message.emit(
                                        f"Intensity dropped! Change: {change_percent:+.2f}% "
                                        f"(threshold: -{self.threshold_percent}%)"
                                    )

                                    # Move motors to maximize intensity (climb the gradient)
                                    # Negative change means we moved away from optimum, reverse direction
                                    self._move_motors(change_percent)

                                    # Update reference intensity to new value
                                    self.last_normalized_intensity = normalized_intensity
                                    self.log_message.emit(
                                        f"Adjusted motors. New reference: {normalized_intensity:.2f}"
                                    )

                else:
                    self.status_update.emit(f"Waiting (HDF5 at: {location})")

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                self.log_message.emit(f"Error: {str(e)}")

            # Wait before next poll
            time.sleep(self.poll_interval)

    def stop(self):
        """Stop the monitoring thread."""
        self.running = False

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
                self.logger.warning(f"Failed to get PV {pv_name}: {result.stderr}")
                return None
        except Exception as e:
            self.logger.error(f"Error getting PV {pv_name}: {e}")
            return None

    def _get_beam_current(self) -> Optional[float]:
        """Get storage ring beam current in mA."""
        try:
            current_str = self._get_pv_value(self.beam_current_pv)
            if current_str:
                return float(current_str)
            return None
        except Exception as e:
            self.logger.error(f"Error getting beam current: {e}")
            return None

    def _get_image_average(self) -> Optional[float]:
        """Get average intensity from image PV by actively fetching fresh data."""
        try:
            # Method 1: Use pvaccess to get fresh image data from PV
            # This actively fetches the current image from the PV
            if self.image_channel is not None:
                try:
                    pv_data = self.image_channel.get()

                    # Extract image array from NTNDArray structure
                    if 'value' in pv_data:
                        # Get the image data array
                        image_data = pv_data['value']
                        if isinstance(image_data, np.ndarray) and image_data.size > 0:
                            mean_intensity = float(np.mean(image_data))
                            self.logger.debug(f"Fresh PV data: mean={mean_intensity:.2f}, shape={image_data.shape}")
                            return mean_intensity
                    else:
                        self.logger.debug(f"PV data structure: {pv_data.getStructureDict()}")

                except Exception as pva_error:
                    self.logger.debug(f"PVA fetch failed: {pva_error}")

            # Method 2: Fallback to parent viewer's cached image
            # This ensures we still work if PVA fails
            if self.parent_dialog is not None:
                parent_viewer = self.parent_dialog.parent()
                if hasattr(parent_viewer, 'current_image'):
                    image = parent_viewer.current_image
                    if image is not None and isinstance(image, np.ndarray):
                        self.logger.debug("Using cached image from parent viewer")
                        return float(np.mean(image))

                # Also check for image_view attribute
                if hasattr(parent_viewer, 'image_view'):
                    image_item = parent_viewer.image_view.getImageItem()
                    if image_item is not None:
                        image = image_item.image
                        if image is not None and isinstance(image, np.ndarray):
                            self.logger.debug("Using cached image from image_view")
                            return float(np.mean(image))

            self.logger.warning("Unable to access fresh image data via PV or parent viewer")
            return None

        except Exception as e:
            self.logger.error(f"Error calculating image average: {e}")
            return None

    def _move_motors(self, change_percent: float):
        """
        Move both motors to maximize beam intensity.

        Args:
            change_percent: Percentage change in normalized intensity (negative = decreased)

        Logic:
            - Intensity dropped (negative change): Move motors in NEGATIVE direction
            - This is a simple gradient ascent to find the intensity maximum
            - Motors move to compensate for beam drift and maximize signal
        """
        try:
            # When intensity drops, move in negative direction to restore/maximize it
            # The step direction should be configured to move toward higher intensity
            direction = -1.0 if change_percent < 0 else 1.0

            motor1_step = self.motor1_step * direction
            motor2_step = self.motor2_step * direction

            # Move motor 1
            motor1_result = self._move_motor(self.motor1_pv, motor1_step)
            if motor1_result:
                self.log_message.emit(
                    f"Motor 1 ({self.motor1_pv}) moved by {motor1_step:+.4f} "
                    f"(maximizing intensity after {change_percent:+.2f}% drop)"
                )
            else:
                self.log_message.emit(f"Failed to move Motor 1 ({self.motor1_pv})")

            # Move motor 2
            motor2_result = self._move_motor(self.motor2_pv, motor2_step)
            if motor2_result:
                self.log_message.emit(
                    f"Motor 2 ({self.motor2_pv}) moved by {motor2_step:+.4f} "
                    f"(maximizing intensity after {change_percent:+.2f}% drop)"
                )
            else:
                self.log_message.emit(f"Failed to move Motor 2 ({self.motor2_pv})")

        except Exception as e:
            self.logger.error(f"Error moving motors: {e}")
            self.log_message.emit(f"Error moving motors: {str(e)}")

    def _move_motor(self, motor_pv: str, step: float) -> bool:
        """Move a motor by relative step using caput."""
        try:
            # Get current position
            current_pos_str = self._get_pv_value(f"{motor_pv}.RBV")
            if current_pos_str is None:
                return False

            current_pos = float(current_pos_str)
            new_pos = current_pos + step

            # Set new position
            result = subprocess.run(
                ['caput', motor_pv, str(new_pos)],
                capture_output=True,
                text=True,
                timeout=10
            )

            return result.returncode == 0

        except Exception as e:
            self.logger.error(f"Error moving motor {motor_pv}: {e}")
            return False
