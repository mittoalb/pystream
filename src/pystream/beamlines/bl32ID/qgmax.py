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
    HANDLER_TYPE = 'singleton'  # Keep one instance, show/hide it

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("QGMax - bl32ID")
        self.resize(600, 700)

        self.is_running = False
        self.optimization_timer = QtCore.QTimer()
        self.optimization_timer.timeout.connect(self._run_optimization_cycle)

        # State for synchronized optimization
        self.optimization_active = False
        self.current_motor = None  # 'motor1' or 'motor2'
        self.motor_direction = {}  # {motor_name: +1 or -1}
        self.motor_consecutive_decreases = {}  # Track consecutive decreases
        self.motor_last_mean = {}  # Last mean value for each motor
        self.motor_max_mean = {}  # Best mean seen for each motor
        self.motor_max_position = {}  # Position with best mean
        self.steps_taken = 0
        self.waiting_for_image = False

        self._init_ui()
        self._load_current_values()
        self._connect_to_image_stream()

    def _connect_to_image_stream(self):
        """Connect to the parent viewer's image update signal."""
        if self.parent() and hasattr(self.parent(), 'new_image_for_plugins'):
            self.parent().new_image_for_plugins.connect(self._on_new_image)
            self._log_message("Connected to image stream")
            if self.logger:
                self.logger.info("QGMax: Connected to image stream")
        else:
            self._log_message("WARNING: Could not connect to image stream!")
            if self.logger:
                self.logger.warning("QGMax: Failed to connect to image stream")

    def _on_new_image(self, uid: int, img: np.ndarray, ts: float):
        """Called when a new image arrives from the stream."""
        if not self.optimization_active:
            return

        if not self.waiting_for_image:
            return

        self._log_message(f"New image received (UID: {uid})")

        # Calculate mean of new image
        mean_value = float(np.mean(img))

        # Process the new data point
        self._process_optimization_step(mean_value)

        self.waiting_for_image = False

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Title
        title = QtWidgets.QLabel("QGMax - Beam Intensity")
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
        """Start a new optimization cycle synchronized with image stream."""
        if self.optimization_active:
            self._log_message("Optimization already running")
            return

        self._log_message("=== Starting optimization cycle ===")

        # Reset state
        self.optimization_active = True
        self.motor_direction = {}
        self.motor_consecutive_decreases = {'motor1': 0, 'motor2': 0}
        self.motor_last_mean = {}
        self.motor_max_mean = {}
        self.motor_max_position = {}

        # Get initial mean from current image
        initial_mean = self._get_image_mean()
        if initial_mean is None:
            self._log_message("ERROR: Cannot get image mean")
            self.optimization_active = False
            return

        self._log_message(f"Initial mean: {initial_mean:.2f}")

        # Initialize for both motors
        for motor_name in ['motor1', 'motor2']:
            self.motor_last_mean[motor_name] = initial_mean
            self.motor_max_mean[motor_name] = initial_mean
            pv = self._get_motor_pv(motor_name)
            pos = self._get_pv_value(pv)
            if pos is not None:
                self.motor_max_position[motor_name] = pos
                self._log_message(f"{motor_name}: Initial position = {pos:.4f}")

        # Start with motor 1, direction +1 (will be set properly after first step)
        self.current_motor = 'motor1'
        self.motor_direction['motor1'] = +1
        self.steps_taken = 0

        # Take first step
        self._take_next_step()

    def _take_next_step(self):
        """Move the current motor by 2 steps and wait for next image."""
        if not self.optimization_active:
            return

        motor_name = self.current_motor
        pv = self._get_motor_pv(motor_name)
        step_size = self._get_motor_step(motor_name)

        # Get current position
        current_pos = self._get_pv_value(pv)
        if current_pos is None:
            self._log_message(f"ERROR: Cannot read {motor_name} position")
            self._finish_optimization()
            return

        # Determine direction (initialize to +1 if first time)
        if motor_name not in self.motor_direction:
            self.motor_direction[motor_name] = +1

        direction = self.motor_direction[motor_name]

        # Move by 4 steps
        new_pos = current_pos + (direction * 4 * step_size)

        self._log_message(f"{motor_name}: Moving {direction * 4 * step_size:+.4f} → {new_pos:.4f}")

        if self._set_pv_value(pv, new_pos):
            # Wait for next image to arrive
            self.waiting_for_image = True
            self.steps_taken += 1
            self._log_message(f"{motor_name}: Waiting for next image...")
        else:
            self._log_message(f"ERROR: Failed to move {motor_name}")
            self._finish_optimization()

    def _process_optimization_step(self, new_mean: float):
        """Process the mean value from the new image after a motor move."""
        motor_name = self.current_motor
        last_mean = self.motor_last_mean.get(motor_name, new_mean)
        max_mean = self.motor_max_mean.get(motor_name, new_mean)

        self._log_message(f"{motor_name}: Mean {last_mean:.2f} → {new_mean:.2f}")

        # Check if mean increased or decreased
        if new_mean > last_mean:
            # INCREASING - good! Continue in same direction
            self._log_message(f"{motor_name}: Increasing (+{new_mean - last_mean:.2f}) - Continue")
            self.motor_consecutive_decreases[motor_name] = 0

            # Update max if this is the best
            if new_mean > max_mean:
                self.motor_max_mean[motor_name] = new_mean
                pv = self._get_motor_pv(motor_name)
                pos = self._get_pv_value(pv)
                if pos is not None:
                    self.motor_max_position[motor_name] = pos

            self.motor_last_mean[motor_name] = new_mean

            # Take another step in same direction
            self._take_next_step()

        else:
            # DECREASING - need to check what to do
            decrease = last_mean - new_mean
            self._log_message(f"{motor_name}: Decreasing (-{decrease:.2f})")

            self.motor_consecutive_decreases[motor_name] += 1

            if self.motor_consecutive_decreases[motor_name] == 1:
                # First decrease - reverse direction and try
                self._log_message(f"{motor_name}: First decrease - Reversing direction")
                self.motor_direction[motor_name] *= -1
                self.motor_last_mean[motor_name] = new_mean

                # Take step in reversed direction
                self._take_next_step()

            elif self.motor_consecutive_decreases[motor_name] >= 2:
                # Second consecutive decrease - go back to max and finish this motor
                self._log_message(f"{motor_name}: 2nd decrease - Going back to max")

                # Move back to best position
                pv = self._get_motor_pv(motor_name)
                best_pos = self.motor_max_position.get(motor_name)
                if best_pos is not None:
                    self._set_pv_value(pv, best_pos)
                    self._log_message(f"{motor_name}: Returned to best position {best_pos:.4f}")

                # Move to next motor
                self._switch_to_next_motor()

    def _switch_to_next_motor(self):
        """Switch to optimizing the next motor or finish."""
        if self.current_motor == 'motor1':
            # Switch to motor 2
            self._log_message("--- Switching to Motor 2 ---")
            self.current_motor = 'motor2'
            self.motor_direction['motor2'] = +1  # Start with positive direction
            self.steps_taken = 0

            # Take first step for motor 2
            self._take_next_step()

        else:
            # Both motors done
            self._finish_optimization()

    def _finish_optimization(self):
        """Complete the optimization cycle."""
        self.optimization_active = False
        self.waiting_for_image = False

        # Report final results
        motor1_improvement = self.motor_max_mean.get('motor1', 0) - self.motor_last_mean.get('motor1', 0)
        motor2_improvement = self.motor_max_mean.get('motor2', 0) - self.motor_last_mean.get('motor2', 0)

        self._log_message(
            f"=== Optimization Complete ==="
        )
        self._log_message(f"Motor 1: Best mean = {self.motor_max_mean.get('motor1', 0):.2f}")
        self._log_message(f"Motor 2: Best mean = {self.motor_max_mean.get('motor2', 0):.2f}")

        self._update_status_display()

    def _get_motor_pv(self, motor_name: str) -> str:
        """Get PV name for a motor."""
        if motor_name == 'motor1':
            return self.motor1_pv_input.text()
        else:
            return self.motor2_pv_input.text()

    def _get_motor_step(self, motor_name: str) -> float:
        """Get step size for a motor."""
        if motor_name == 'motor1':
            return self.motor1_step_input.value()
        else:
            return self.motor2_step_input.value()

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Stop optimization if running
        if self.is_running:
            self.optimization_timer.stop()
            self._log_message("Stopped optimization (dialog closed)")

        event.accept()
