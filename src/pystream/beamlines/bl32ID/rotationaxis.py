"""
Rotation Axis Detection Plugin for bl32ID

Detects the vertical rotation axis position in tomography image sequences.
Uses image correlation between consecutive angles to find the axis of rotation.
"""

import time
import logging
import numpy as np
from typing import Optional, Deque
from collections import deque
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg


class RotationAxisDialog(QtWidgets.QDialog):
    """Dialog for detecting and displaying rotation axis position."""

    BUTTON_TEXT = "Rotation Axis"
    HANDLER_TYPE = 'singleton'  # Keep one instance, show/hide it

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Rotation Axis Detection - bl32ID")
        self.resize(600, 700)

        self.axis_line = None
        self.is_detecting = False
        self.image_buffer: Deque[np.ndarray] = deque(maxlen=10)
        self.axis_position = None
        self.axis_history = []

        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Title
        title = QtWidgets.QLabel("Rotation Axis Detection")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        desc = QtWidgets.QLabel(
            "Automatically detects the vertical rotation axis position "
            "from tomography image sequences."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status section
        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout()

        self.status_label = QtWidgets.QLabel("Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; color: gray;")
        status_layout.addWidget(self.status_label)

        self.axis_label = QtWidgets.QLabel("Detected Axis: N/A")
        self.axis_label.setStyleSheet("font-size: 12pt;")
        status_layout.addWidget(self.axis_label)

        self.images_label = QtWidgets.QLabel("Images Analyzed: 0")
        status_layout.addWidget(self.images_label)

        self.confidence_label = QtWidgets.QLabel("Confidence: N/A")
        status_layout.addWidget(self.confidence_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Settings section
        settings_group = QtWidgets.QGroupBox("Settings")
        settings_layout = QtWidgets.QFormLayout()

        self.buffer_size_spin = QtWidgets.QSpinBox()
        self.buffer_size_spin.setRange(2, 50)
        self.buffer_size_spin.setValue(10)
        self.buffer_size_spin.setToolTip("Number of images to use for detection")
        self.buffer_size_spin.valueChanged.connect(self._update_buffer_size)
        settings_layout.addRow("Buffer Size:", self.buffer_size_spin)

        self.show_axis_checkbox = QtWidgets.QCheckBox()
        self.show_axis_checkbox.setChecked(True)
        self.show_axis_checkbox.setToolTip("Display detected axis as vertical line on image")
        self.show_axis_checkbox.stateChanged.connect(self._toggle_axis_display)
        settings_layout.addRow("Show Axis Line:", self.show_axis_checkbox)

        self.auto_update_checkbox = QtWidgets.QCheckBox()
        self.auto_update_checkbox.setChecked(True)
        self.auto_update_checkbox.setToolTip("Continuously update axis position as new images arrive")
        settings_layout.addRow("Auto Update:", self.auto_update_checkbox)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Axis position plot
        plot_group = QtWidgets.QGroupBox("Axis Position History")
        plot_layout = QtWidgets.QVBoxLayout()

        try:
            import pyqtgraph as pg
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setLabel('left', 'Axis Position (pixels)')
            self.plot_widget.setLabel('bottom', 'Image Number')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_widget.setMinimumHeight(200)

            self.axis_curve = self.plot_widget.plot(pen='g', width=2, symbol='o', symbolSize=5)
            plot_layout.addWidget(self.plot_widget)
            self.has_plot = True
        except ImportError:
            no_plot_label = QtWidgets.QLabel("PyQtGraph not available for plotting")
            plot_layout.addWidget(no_plot_label)
            self.has_plot = False

        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)

        # Log area
        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Control buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.start_button = QtWidgets.QPushButton("Start Detection")
        self.start_button.clicked.connect(self._start_detection)
        button_layout.addWidget(self.start_button)

        self.stop_button = QtWidgets.QPushButton("Stop Detection")
        self.stop_button.clicked.connect(self._stop_detection)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        self.reset_button = QtWidgets.QPushButton("Reset")
        self.reset_button.clicked.connect(self._reset)
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

    def _update_buffer_size(self, size: int):
        """Update the image buffer size."""
        self.image_buffer = deque(maxlen=size)
        self._log_message(f"Buffer size updated to {size}")

    def _toggle_axis_display(self, state: int):
        """Toggle the axis line display on the image."""
        if state == QtCore.Qt.Checked:
            if self.axis_position is not None:
                self._show_axis_line()
        else:
            self._hide_axis_line()

    def _start_detection(self):
        """Start rotation axis detection."""
        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_ready'):
            self._log_message("Error: Cannot connect to image viewer")
            QtWidgets.QMessageBox.warning(
                self, "Error",
                "Cannot connect to image viewer. Make sure the plugin is opened from the main viewer."
            )
            return

        self.is_detecting = True
        self.image_buffer.clear()

        # Connect to image_ready signal
        parent_viewer.image_ready.connect(self._on_image_ready)

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Status: Detecting")
        self.status_label.setStyleSheet("font-weight: bold; color: green;")
        self._log_message("Rotation axis detection started")

    def _stop_detection(self):
        """Stop rotation axis detection."""
        parent_viewer = self.parent()
        if parent_viewer and hasattr(parent_viewer, 'image_ready'):
            try:
                parent_viewer.image_ready.disconnect(self._on_image_ready)
            except TypeError:
                pass

        self.is_detecting = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")
        self._log_message("Rotation axis detection stopped")

    def _reset(self):
        """Reset detection data."""
        self.image_buffer.clear()
        self.axis_position = None
        self.axis_history = []

        self.axis_label.setText("Detected Axis: N/A")
        self.images_label.setText("Images Analyzed: 0")
        self.confidence_label.setText("Confidence: N/A")

        if self.has_plot:
            self.axis_curve.setData([], [])

        self._hide_axis_line()
        self._log_message("Detection data reset")

    @QtCore.pyqtSlot(int, np.ndarray, float)
    def _on_image_ready(self, uid: int, img: np.ndarray, ts: float):
        """Process new image for rotation axis detection."""
        if not self.is_detecting:
            return

        try:
            # Convert to grayscale if color
            if img.ndim == 3:
                img = np.mean(img, axis=2)

            # Add to buffer
            self.image_buffer.append(img.copy())

            num_images = len(self.image_buffer)
            self.images_label.setText(f"Images Analyzed: {num_images}")

            # Need at least 2 images for detection
            if num_images < 2:
                return

            # Detect axis if auto-update is enabled
            if self.auto_update_checkbox.isChecked():
                axis_pos, confidence = self._detect_rotation_axis()

                if axis_pos is not None:
                    self.axis_position = axis_pos
                    self.axis_history.append(axis_pos)

                    # Check if axis is outside field of view
                    if axis_pos < 0:
                        location_note = " (LEFT of FOV)"
                    elif axis_pos >= img.shape[1]:
                        location_note = " (RIGHT of FOV)"
                    else:
                        location_note = ""

                    self.axis_label.setText(f"Detected Axis: X = {axis_pos:.1f} pixels{location_note}")
                    self.confidence_label.setText(f"Confidence: {confidence:.2%}")

                    # Update plot
                    if self.has_plot:
                        y_data = list(self.axis_history)
                        x_data = list(range(len(y_data)))
                        self.axis_curve.setData(x_data, y_data)

                    # Update axis line on image
                    if self.show_axis_checkbox.isChecked():
                        self._show_axis_line()

        except Exception as e:
            self._log_message(f"Error processing image: {e}")
            if self.logger:
                self.logger.error(f"Rotation axis detection error: {e}")

    def _detect_rotation_axis(self) -> tuple[Optional[float], float]:
        """
        Detect rotation axis by finding where image intensity variance is minimum.

        For tomography: features at the rotation axis don't move, so they have
        low variance across angles. Features far from axis move a lot = high variance.

        The axis can be outside the field of view (negative or beyond width).

        Returns:
            tuple: (axis_position, confidence) where axis_position is in pixels
                   (can be negative or > width if outside FOV)
                   and confidence is between 0 and 1
        """
        if len(self.image_buffer) < 3:
            return None, 0.0

        num_images = len(self.image_buffer)
        height, width = self.image_buffer[0].shape[:2]

        # Stack all images into 3D array (angles × height × width)
        image_stack = np.array(self.image_buffer[:num_images])

        # Use middle rows for robust analysis
        row_start = height // 4
        row_end = 3 * height // 4

        # Compute variance along angle dimension for each pixel column
        # For each column x, calculate how much the vertical profile varies across angles
        variance_map = np.var(image_stack[:, row_start:row_end, :], axis=0)

        # Average variance across vertical dimension to get 1D variance profile
        # variance_profile[x] = how much column x varies across angles
        variance_profile = np.mean(variance_map, axis=0)

        # Smooth to reduce noise
        if len(variance_profile) > 10:
            kernel_size = min(11, len(variance_profile) // 10)
            if kernel_size % 2 == 0:
                kernel_size += 1
            kernel = np.ones(kernel_size) / kernel_size
            variance_profile = np.convolve(variance_profile, kernel, mode='same')

        # The rotation axis should be at the MINIMUM variance
        # But axis might be outside FOV, so we need to extrapolate

        # Find the general trend: variance should increase away from axis
        # Fit a parabola to find the minimum
        x_coords = np.arange(width)

        # Try to fit parabola: variance = a*(x - x_axis)^2 + c
        # This works even if axis is outside [0, width]
        try:
            # Parabolic fit
            coeffs = np.polyfit(x_coords, variance_profile, 2)
            a, b, c = coeffs

            if abs(a) > 1e-10:
                # Minimum of parabola ax^2 + bx + c is at x = -b/(2a)
                axis_x = -b / (2 * a)

                # Confidence based on how well the parabola fits
                fitted_curve = np.polyval(coeffs, x_coords)
                residuals = variance_profile - fitted_curve
                r_squared = 1 - (np.sum(residuals**2) / np.sum((variance_profile - np.mean(variance_profile))**2))
                confidence = max(0.0, min(1.0, r_squared))

                # Also check that parabola opens upward (a > 0)
                if a <= 0:
                    # Parabola opens downward - not what we expect
                    # Fall back to simple minimum
                    axis_x = float(np.argmin(variance_profile))
                    confidence = 0.3
            else:
                # Not really a parabola, just find minimum
                axis_x = float(np.argmin(variance_profile))
                confidence = 0.3

        except Exception:
            # Fit failed, use simple minimum
            axis_x = float(np.argmin(variance_profile))
            confidence = 0.3

        # DO NOT clamp axis position - allow outside FOV
        return float(axis_x), float(confidence)

    def _compute_shift(self, img1: np.ndarray, img2: np.ndarray) -> tuple[Optional[float], float]:
        """
        Compute horizontal shift between two images using projection correlation.

        Returns:
            tuple: (shift_in_pixels, confidence)
        """
        # Compute vertical projections (collapse to 1D)
        proj1 = np.sum(img1, axis=0)
        proj2 = np.sum(img2, axis=0)

        # Normalize
        proj1 = (proj1 - np.mean(proj1)) / (np.std(proj1) + 1e-8)
        proj2 = (proj2 - np.mean(proj2)) / (np.std(proj2) + 1e-8)

        # Cross-correlation
        correlation = np.correlate(proj1, proj2, mode='full')

        # Find peak
        max_idx = np.argmax(correlation)
        width = len(proj1)

        # Convert to shift (positive = rightward shift)
        shift = max_idx - (width - 1)

        # Refine shift using parabolic interpolation around peak
        if 0 < max_idx < len(correlation) - 1:
            y1 = correlation[max_idx - 1]
            y2 = correlation[max_idx]
            y3 = correlation[max_idx + 1]

            # Parabolic fit for sub-pixel accuracy
            denom = 2 * (y1 - 2*y2 + y3)
            if abs(denom) > 1e-10:
                shift_correction = (y1 - y3) / denom
                shift += shift_correction

        # Confidence from correlation peak quality
        corr_max = correlation[max_idx]
        corr_mean = np.mean(correlation)
        corr_std = np.std(correlation)

        if corr_std > 1e-10:
            # Signal-to-noise ratio
            confidence = (corr_max - corr_mean) / corr_std
            confidence = min(1.0, confidence / 10.0)  # Normalize
        else:
            confidence = 0.0

        return float(shift), float(confidence)

    def _show_axis_line(self):
        """Show the detected axis as a vertical line on the image."""
        if self.axis_position is None:
            return

        parent_viewer = self.parent()
        if not parent_viewer or not hasattr(parent_viewer, 'image_view'):
            return

        image_view = parent_viewer.image_view

        # Remove old line if exists
        if self.axis_line:
            try:
                image_view.removeItem(self.axis_line)
            except Exception:
                pass

        # Create vertical line at axis position
        self.axis_line = pg.InfiniteLine(
            pos=self.axis_position,
            angle=90,
            pen=pg.mkPen('r', width=2, style=QtCore.Qt.DashLine),
            label='Rotation Axis',
            labelOpts={'position': 0.95, 'color': 'r'}
        )

        image_view.addItem(self.axis_line)

    def _hide_axis_line(self):
        """Hide the axis line from the image."""
        if self.axis_line:
            parent_viewer = self.parent()
            if parent_viewer and hasattr(parent_viewer, 'image_view'):
                try:
                    parent_viewer.image_view.removeItem(self.axis_line)
                except Exception:
                    pass
            self.axis_line = None

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Stop detection if active
        if self.is_detecting:
            self._stop_detection()

        # Remove axis line from image view
        self._hide_axis_line()

        event.accept()
