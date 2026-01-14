"""
Live Difference Viewer

Shows real-time difference between adjacent frames (frame N vs frame N-1).
Window opens automatically when you execute this script.
"""

import numpy as np
from PyQt5 import QtWidgets
import pyqtgraph as pg

# Previous frame for comparison
_prev_frame = None

# Diff window
_diff_win = None

# Minimum size to consider a real frame (not test image)
_MIN_FRAME_SIZE = 100


class DiffWindow(QtWidgets.QWidget):
    """Real-time difference viewer window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Difference Viewer (Adjacent Frames)")
        self.setGeometry(100, 100, 700, 700)

        self.running = True
        self.paused = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Control buttons
        btn_layout = QtWidgets.QHBoxLayout()

        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.clicked.connect(self._on_start)
        btn_layout.addWidget(self.btn_start)

        self.btn_pause = QtWidgets.QPushButton("Pause")
        self.btn_pause.clicked.connect(self._on_pause)
        btn_layout.addWidget(self.btn_pause)

        btn_layout.addStretch()

        self.lbl_stats = QtWidgets.QLabel("Waiting for frames...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # Image view
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        layout.addWidget(self.image_view)

        self._update_buttons()

    def _on_start(self):
        self.running = True
        self.paused = False
        self._update_buttons()

    def _on_pause(self):
        if self.running:
            self.paused = not self.paused
            self._update_buttons()

    def _update_buttons(self):
        if self.running and not self.paused:
            self.btn_start.setText("Running")
            self.btn_start.setEnabled(False)
            self.btn_pause.setText("Pause")
            self.btn_pause.setEnabled(True)
        elif self.paused:
            self.btn_start.setText("Start")
            self.btn_start.setEnabled(True)
            self.btn_pause.setText("Paused")
            self.btn_pause.setEnabled(True)
        else:
            self.btn_start.setText("Start")
            self.btn_start.setEnabled(True)
            self.btn_pause.setText("Pause")
            self.btn_pause.setEnabled(False)

    def update_image(self, img, stats_text):
        if not self.running or self.paused:
            return
        self.image_view.setImage(img, autoLevels=True)
        self.lbl_stats.setText(stats_text)


def process(img):
    """Process each frame - compute difference with previous frame."""
    global _prev_frame, _diff_win

    # Skip tiny test images from console
    if img.shape[0] < _MIN_FRAME_SIZE or img.shape[1] < _MIN_FRAME_SIZE:
        return img

    # Skip if window not running
    if _diff_win is None or not _diff_win.running or _diff_win.paused:
        _prev_frame = img.copy()
        return img

    # First frame - just store it
    if _prev_frame is None:
        _prev_frame = img.copy()
        if _diff_win is not None:
            _diff_win.lbl_stats.setText(f"First frame captured ({img.shape[1]}x{img.shape[0]}). Waiting for next...")
        return img

    # Compute difference between current and previous frame
    diff = np.abs(img.astype(np.float32) - _prev_frame.astype(np.float32))
    stats = f"Min: {diff.min():.1f}  Max: {diff.max():.1f}  Mean: {diff.mean():.1f}"
    _diff_win.update_image(diff, stats)

    # Store current as previous for next iteration
    _prev_frame = img.copy()

    return img


# Reset state and open window when script is executed
_prev_frame = None
_diff_win = DiffWindow()
_diff_win.show()
_diff_win.raise_()
print("Diff window opened. Showing difference between adjacent frames.")