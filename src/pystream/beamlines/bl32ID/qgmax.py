"""
Mean Value Optimizer Plugin for bl32ID

Monitors the image mean value and optimizes two motors to maximize it.
- Can run continuously (every 1 minute) or on-demand
- Handles motors that may increase or decrease the mean value
- Uses simple gradient-based optimization
"""

import subprocess
import logging
import time
from typing import Optional, Tuple
import numpy as np
from PyQt5 import QtWidgets, QtCore


class QGMaxDialog(QtWidgets.QDialog):
    """Dialog for optimizing image mean by adjusting two motors."""

    BUTTON_TEXT = "QGMax"

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("QGMax - bl32ID")
        self.resize(600, 700)

        self.is_running = False
        self.optimization_timer = QtCore.QTimer()
        self.optimization_timer.timeout.connect(self._run_optimization_cycle)

        self._init_ui()
        self._load_current_values()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Title
        title = QtWidgets.QLabel("QGMax - Quantum Gain Maximizer")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        desc = QtWidgets.QLabel(
            "Automatically optimize two motors to maximize image mean value."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Create tab widget
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self._create_control_tab()
        self._create_settings_tab()

        # Bottom buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def _create_control_tab(self):
        """Create the main control tab."""
        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout(control_widget)

        # Control Buttons
        control_group = QtWidgets.QGroupBox("Control")
        control_group_layout = QtWidgets.QVBoxLayout()

        # Start/Stop button
        self.toggle_btn = QtWidgets.QPushButton("Start Continuous Optimization")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._toggle_optimization)
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-size: 12pt; padding: 10px; }"
        )
        control_group_layout.addWidget(self.toggle_btn)

        # Run once button
        self.run_once_btn = QtWidgets.QPushButton("Run Optimization Once")
        self.run_once_btn.clicked.connect(self._run_once)
        self.run_once_btn.setStyleSheet(
            "QPushButton { font-size: 11pt; padding: 8px; }"
        )
        control_group_layout.addWidget(self.run_once_btn)

        control_group.setLayout(control_group_layout)
        control_layout.addWidget(control_group)

        # Status Display
        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout()

        self.status_label = QtWidgets.QLabel("Status: Idle")
        self.status_label.setStyleSheet("padding: 5px; background: #f0f0f0; font-weight: bold;")
        status_layout.addWidget(self.status_label)

        self.current_mean_label = QtWidgets.QLabel("Current Mean: --")
        self.current_mean_label.setStyleSheet("padding: 5px; background: #f0f0f0;")
        status_layout.addWidget(self.current_mean_label)

        self.motor_positions_label = QtWidgets.QLabel("Motor Positions: --")
        self.motor_positions_label.setStyleSheet("padding: 5px; background: #f0f0f0;")
        status_layout.addWidget(self.motor_positions_label)

        status_group.setLayout(status_layout)
        control_layout.addWidget(status_group)

        # Activity Log
        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        control_layout.addWidget(log_group)

        control_layout.addStretch()

        self.tabs.addTab(control_widget, "Control")

    def _create_settings_tab(self):
        """Create the settings/configuration tab."""
        settings_widget = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout(settings_widget)

        # Motor 1 Configuration
        motor1_group = QtWidgets.QGroupBox("Motor 1 Configuration")
        motor1_layout = QtWidgets.QFormLayout()

        self.motor1_pv_input = QtWidgets.QLineEdit("32id:m1")
        motor1_layout.addRow("Motor 1 PV:", self.motor1_pv_input)

        self.motor1_step_input = QtWidgets.QDoubleSpinBox()
        self.motor1_step_input.setDecimals(4)
        self.motor1_step_input.setRange(0.0001, 1000.0)
        self.motor1_step_input.setValue(0.01)
        motor1_layout.addRow("Step Size:", self.motor1_step_input)

        motor1_group.setLayout(motor1_layout)
        settings_layout.addWidget(motor1_group)

        # Motor 2 Configuration
        motor2_group = QtWidgets.QGroupBox("Motor 2 Configuration")
        motor2_layout = QtWidgets.QFormLayout()

        self.motor2_pv_input = QtWidgets.QLineEdit("32id:m2")
        motor2_layout.addRow("Motor 2 PV:", self.motor2_pv_input)

        self.motor2_step_input = QtWidgets.QDoubleSpinBox()
        self.motor2_step_input.setDecimals(4)
        self.motor2_step_input.setRange(0.0001, 1000.0)
        self.motor2_step_input.setValue(0.01)
        motor2_layout.addRow("Step Size:", self.motor2_step_input)

        motor2_group.setLayout(motor2_layout)
        settings_layout.addWidget(motor2_group)

        # Optimization Settings
        opt_settings_group = QtWidgets.QGroupBox("Optimization Settings")
        opt_settings_layout = QtWidgets.QFormLayout()

        self.interval_input = QtWidgets.QSpinBox()
        self.interval_input.setRange(10, 600)
        self.interval_input.setValue(60)
        self.interval_input.setSuffix(" seconds")
        opt_settings_layout.addRow("Optimization Interval:", self.interval_input)

        self.max_iterations_input = QtWidgets.QSpinBox()
        self.max_iterations_input.setRange(1, 20)
        self.max_iterations_input.setValue(5)
        opt_settings_layout.addRow("Max Iterations per Cycle:", self.max_iterations_input)

        self.convergence_threshold_input = QtWidgets.QDoubleSpinBox()
        self.convergence_threshold_input.setDecimals(1)
        self.convergence_threshold_input.setRange(0.1, 10.0)
        self.convergence_threshold_input.setValue(0.5)
        self.convergence_threshold_input.setSuffix(" %")
        opt_settings_layout.addRow("Convergence Threshold:", self.convergence_threshold_input)

        opt_settings_group.setLayout(opt_settings_layout)
        settings_layout.addWidget(opt_settings_group)

        settings_layout.addStretch()

        self.tabs.addTab(settings_widget, "Settings")

    def _log_message(self, message: str):
        """Add a message to the log with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        if self.logger:
            self.logger.info(f"MeanOptimizer: {message}")

    def _get_pv_value(self, pv_name: str) -> Optional[float]:
        """Get PV value using caget."""
        try:
            result = subprocess.run(
                ['caget', '-t', pv_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
            else:
                self._log_message(f"Failed to get PV {pv_name}: {result.stderr}")
                return None
        except Exception as e:
            self._log_message(f"Error getting PV {pv_name}: {e}")
            return None

    def _set_pv_value(self, pv_name: str, value: float) -> bool:
        """Set PV value using caput."""
        try:
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

    def _get_image_mean(self) -> Optional[float]:
        """Get the current mean value of the image."""
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            self._log_message("Error: Cannot access image view")
            return None

        image_view = parent_viewer.image_view
        image_item = image_view.getImageItem()
        if image_item is None or image_item.image is None:
            self._log_message("Error: No image available")
            return None

        image = image_item.image
        mean_value = float(np.mean(image))
        return mean_value

    def _load_current_values(self):
        """Load current motor positions and image mean."""
        self._update_status_display()

    def _update_status_display(self):
        """Update the status display with current values."""
        # Get current mean
        mean_value = self._get_image_mean()
        if mean_value is not None:
            self.current_mean_label.setText(f"Current Mean: {mean_value:.2f}")
        else:
            self.current_mean_label.setText("Current Mean: --")

        # Get motor positions
        motor1_pv = self.motor1_pv_input.text()
        motor2_pv = self.motor2_pv_input.text()

        motor1_pos = self._get_pv_value(motor1_pv)
        motor2_pos = self._get_pv_value(motor2_pv)

        if motor1_pos is not None and motor2_pos is not None:
            self.motor_positions_label.setText(
                f"Motor Positions: M1={motor1_pos:.4f}, M2={motor2_pos:.4f}"
            )
        else:
            self.motor_positions_label.setText("Motor Positions: --")

    def _toggle_optimization(self, checked: bool):
        """Toggle continuous optimization on/off."""
        self.is_running = checked

        if checked:
            # Start continuous optimization
            self.toggle_btn.setText("Stop Continuous Optimization")
            self.toggle_btn.setStyleSheet(
                "QPushButton { font-size: 12pt; padding: 10px; background-color: #ff6b6b; }"
            )
            self.run_once_btn.setEnabled(False)
            self.status_label.setText("Status: Running (Continuous)")

            interval_ms = self.interval_input.value() * 1000
            self.optimization_timer.start(interval_ms)

            self._log_message(f"Started continuous optimization (interval: {self.interval_input.value()}s)")

            # Run first optimization immediately
            self._run_optimization_cycle()
        else:
            # Stop continuous optimization
            self.toggle_btn.setText("Start Continuous Optimization")
            self.toggle_btn.setStyleSheet(
                "QPushButton { font-size: 12pt; padding: 10px; }"
            )
            self.run_once_btn.setEnabled(True)
            self.status_label.setText("Status: Idle")

            self.optimization_timer.stop()

            self._log_message("Stopped continuous optimization")

    def _run_once(self):
        """Run optimization once immediately."""
        self._log_message("Running one-time optimization")
        self.status_label.setText("Status: Optimizing (One-time)")
        QtWidgets.QApplication.processEvents()  # Update UI

        self._run_optimization_cycle()

        self.status_label.setText("Status: Idle")

    def _run_optimization_cycle(self):
        """Run one optimization cycle to maximize the mean value."""
        self._log_message("=== Starting optimization cycle ===")

        motor1_pv = self.motor1_pv_input.text()
        motor2_pv = self.motor2_pv_input.text()
        motor1_step = self.motor1_step_input.value()
        motor2_step = self.motor2_step_input.value()
        max_iterations = self.max_iterations_input.value()
        convergence_threshold = self.convergence_threshold_input.value() / 100.0

        # Get initial state
        initial_mean = self._get_image_mean()
        if initial_mean is None:
            self._log_message("ERROR: Cannot get image mean")
            return

        motor1_pos = self._get_pv_value(motor1_pv)
        motor2_pos = self._get_pv_value(motor2_pv)

        if motor1_pos is None or motor2_pos is None:
            self._log_message("ERROR: Cannot read motor positions")
            return

        self._log_message(f"Initial mean: {initial_mean:.2f}")
        self._log_message(f"Initial positions: M1={motor1_pos:.4f}, M2={motor2_pos:.4f}")

        best_mean = initial_mean
        best_m1 = motor1_pos
        best_m2 = motor2_pos

        # Determine gradient direction for each motor
        # Try small step in each direction for each motor
        m1_direction = self._find_gradient_direction(motor1_pv, motor1_step, initial_mean)
        m2_direction = self._find_gradient_direction(motor2_pv, motor2_step, initial_mean)

        if m1_direction == 0 and m2_direction == 0:
            self._log_message("Already at local maximum")
            self._update_status_display()
            return

        # Iterative optimization
        for iteration in range(max_iterations):
            improved = False

            # Try moving motor 1
            if m1_direction != 0:
                new_m1 = motor1_pos + (m1_direction * motor1_step)
                if self._set_pv_value(motor1_pv, new_m1):
                    time.sleep(0.5)  # Wait for motor to settle
                    new_mean = self._get_image_mean()

                    if new_mean is not None and new_mean > best_mean:
                        improvement = ((new_mean - best_mean) / best_mean) * 100
                        self._log_message(
                            f"Iter {iteration+1}: M1 step improved mean: "
                            f"{best_mean:.2f} → {new_mean:.2f} (+{improvement:.2f}%)"
                        )
                        best_mean = new_mean
                        motor1_pos = new_m1
                        best_m1 = new_m1
                        improved = True
                    else:
                        # Revert
                        self._set_pv_value(motor1_pv, motor1_pos)
                        time.sleep(0.3)

            # Try moving motor 2
            if m2_direction != 0:
                new_m2 = motor2_pos + (m2_direction * motor2_step)
                if self._set_pv_value(motor2_pv, new_m2):
                    time.sleep(0.5)  # Wait for motor to settle
                    new_mean = self._get_image_mean()

                    if new_mean is not None and new_mean > best_mean:
                        improvement = ((new_mean - best_mean) / best_mean) * 100
                        self._log_message(
                            f"Iter {iteration+1}: M2 step improved mean: "
                            f"{best_mean:.2f} → {new_mean:.2f} (+{improvement:.2f}%)"
                        )
                        best_mean = new_mean
                        motor2_pos = new_m2
                        best_m2 = new_m2
                        improved = True
                    else:
                        # Revert
                        self._set_pv_value(motor2_pv, motor2_pos)
                        time.sleep(0.3)

            # Check convergence
            if not improved:
                self._log_message(f"Converged after {iteration+1} iterations (no improvement)")
                break

            improvement_pct = ((best_mean - initial_mean) / initial_mean) * 100
            if improvement_pct < convergence_threshold:
                self._log_message(
                    f"Converged after {iteration+1} iterations "
                    f"(improvement {improvement_pct:.2f}% < threshold {convergence_threshold*100:.1f}%)"
                )
                break

        # Final report
        total_improvement = ((best_mean - initial_mean) / initial_mean) * 100
        self._log_message(
            f"=== Optimization complete: {initial_mean:.2f} → {best_mean:.2f} "
            f"(+{total_improvement:.2f}%) ==="
        )

        self._update_status_display()

    def _find_gradient_direction(self, motor_pv: str, step: float, current_mean: float) -> int:
        """
        Find the gradient direction for a motor.
        Returns: +1 for positive direction, -1 for negative, 0 for no improvement.
        """
        original_pos = self._get_pv_value(motor_pv)
        if original_pos is None:
            return 0

        # Try positive direction
        if self._set_pv_value(motor_pv, original_pos + step):
            time.sleep(0.5)
            mean_pos = self._get_image_mean()

            # Try negative direction
            if self._set_pv_value(motor_pv, original_pos - step):
                time.sleep(0.5)
                mean_neg = self._get_image_mean()

                # Restore original position
                self._set_pv_value(motor_pv, original_pos)
                time.sleep(0.3)

                if mean_pos is None or mean_neg is None:
                    return 0

                # Determine best direction
                if mean_pos > current_mean and mean_pos > mean_neg:
                    self._log_message(f"{motor_pv}: Gradient direction = POSITIVE")
                    return +1
                elif mean_neg > current_mean and mean_neg > mean_pos:
                    self._log_message(f"{motor_pv}: Gradient direction = NEGATIVE")
                    return -1
                else:
                    self._log_message(f"{motor_pv}: No clear gradient direction")
                    return 0

        return 0

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Stop optimization if running
        if self.is_running:
            self.optimization_timer.stop()
            self._log_message("Stopped optimization (dialog closed)")

        event.accept()
