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
        Detect rotation axis using sinogram symmetry analysis.

        For tomography, we analyze horizontal line profiles across multiple angles.
        The rotation axis is where the sinogram is most symmetric when mirrored.

        The axis can be outside the field of view (negative or beyond width).

        Returns:
            tuple: (axis_position, confidence) where axis_position is in pixels
                   (can be negative or > width if outside FOV)
                   and confidence is between 0 and 1
        """
        if len(self.image_buffer) < 2:
            return None, 0.0

        num_images = len(self.image_buffer)
        if num_images < 2:
            return None, 0.0

        # Get image dimensions
        height, width = self.image_buffer[0].shape[:2]

        # Use middle rows for analysis (avoid edges)
        row_start = height // 4
        row_end = 3 * height // 4
        rows_to_use = list(range(row_start, row_end, max(1, (row_end - row_start) // 20)))

        # Try different possible axis positions
        # Search range: allow axis to be outside FOV
        search_range = np.linspace(-width * 0.5, width * 1.5, 200)

        symmetry_scores = []

        for axis_candidate in search_range:
            score = 0.0
            count = 0

            # For each row, check symmetry across all image pairs
            for row_idx in rows_to_use:
                sinogram_line = []

                # Build sinogram line from all images
                for img in self.image_buffer:
                    if row_idx < img.shape[0]:
                        sinogram_line.append(img[row_idx, :])

                if len(sinogram_line) < 2:
                    continue

                # Stack into 2D sinogram (angles × detector_columns)
                sino = np.array(sinogram_line)

                # Measure symmetry for this axis position
                row_score = self._measure_sinogram_symmetry(sino, axis_candidate, width)
                if row_score > 0:
                    score += row_score
                    count += 1

            if count > 0:
                symmetry_scores.append(score / count)
            else:
                symmetry_scores.append(0.0)

        # Find axis position with best symmetry (maximum score)
        symmetry_scores = np.array(symmetry_scores)

        if np.max(symmetry_scores) == 0:
            return None, 0.0

        best_idx = np.argmax(symmetry_scores)
        axis_x = search_range[best_idx]

        # Refine using parabolic fit around peak
        if 0 < best_idx < len(symmetry_scores) - 1:
            y1 = symmetry_scores[best_idx - 1]
            y2 = symmetry_scores[best_idx]
            y3 = symmetry_scores[best_idx + 1]

            denom = 2 * (y1 - 2*y2 + y3)
            if abs(denom) > 1e-10:
                dx = (y1 - y3) / denom
                axis_x = search_range[best_idx] + dx * (search_range[1] - search_range[0])

        # Confidence based on peak sharpness
        peak_value = np.max(symmetry_scores)
        mean_value = np.mean(symmetry_scores)
        std_value = np.std(symmetry_scores)

        if std_value > 1e-10:
            confidence = (peak_value - mean_value) / (peak_value + 1e-10)
            confidence = min(1.0, max(0.0, confidence))
        else:
            confidence = 0.0

        # DO NOT clamp axis position - allow outside FOV
        return float(axis_x), float(confidence)

    def _measure_sinogram_symmetry(self, sino: np.ndarray, axis_pos: float, width: int) -> float:
        """
        Measure symmetry of sinogram when mirrored around a candidate axis position.

        For correct rotation axis, the sinogram should be symmetric when we compare
        pixels equidistant from the axis.

        Args:
            sino: 2D sinogram (angles × detector_columns)
            axis_pos: Candidate axis position in pixels
            width: Image width in pixels

        Returns:
            Symmetry score (higher = more symmetric)
        """
        num_angles = sino.shape[0]
        if num_angles < 2:
            return 0.0

        # For 180-degree opposed angles, compare mirrored profiles
        # Use first and last images (should be ~180 degrees apart in tomography)
        proj_0 = sino[0, :]
        proj_180 = sino[-1, :]

        # Flip the 180-degree projection around the axis
        flipped_180 = self._flip_around_axis(proj_180, axis_pos, width)

        # Compare correlation between proj_0 and flipped proj_180
        # High correlation = correct axis
        score = self._compute_correlation(proj_0, flipped_180)

        return score

    def _flip_around_axis(self, profile: np.ndarray, axis_pos: float, width: int) -> np.ndarray:
        """
        Flip a 1D profile around an axis position.

        Args:
            profile: 1D intensity profile
            axis_pos: Axis position in pixels (can be outside [0, width])
            width: Profile width

        Returns:
            Flipped profile
        """
        # Create output array
        flipped = np.zeros_like(profile)

        for i in range(width):
            # Mirror position around axis
            mirror_i = 2 * axis_pos - i

            # Interpolate if mirror position is valid
            if 0 <= mirror_i < width - 1:
                # Linear interpolation
                i_low = int(np.floor(mirror_i))
                i_high = int(np.ceil(mirror_i))
                frac = mirror_i - i_low

                if i_high < width:
                    flipped[i] = profile[i_low] * (1 - frac) + profile[i_high] * frac
            elif 0 <= int(mirror_i) < width:
                flipped[i] = profile[int(mirror_i)]

        return flipped

    def _compute_correlation(self, arr1: np.ndarray, arr2: np.ndarray) -> float:
        """
        Compute normalized correlation between two arrays.

        Returns:
            Correlation coefficient (0 to 1)
        """
        if len(arr1) != len(arr2) or len(arr1) == 0:
            return 0.0

        # Normalize
        a1 = arr1 - np.mean(arr1)
        a2 = arr2 - np.mean(arr2)

        std1 = np.std(a1)
        std2 = np.std(a2)

        if std1 < 1e-10 or std2 < 1e-10:
            return 0.0

        # Pearson correlation
        corr = np.sum(a1 * a2) / (len(arr1) * std1 * std2)

        return max(0.0, min(1.0, corr))

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
