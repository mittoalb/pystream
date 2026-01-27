"""
Live Difference Viewer & SSIM value

Shows real-time difference between adjacent frames (frame N vs frame N-1).
Window opens automatically when you execute this script and it shows the value of SSIM 
it contains a warning when the value is under a treshold
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

# Warning SSIM : real warning in range  < 0.6	sudden damage the value 0.9860 is a test , in real case you should use 0.6 
_SSIM_WARN_THRESHOLD = 0.9860
_low_ssim_active = False

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

def similarity_ssim(img_a: np.ndarray, img_b: np.ndarray, eps: float = 1e-6) -> float:
    if img_a is None or img_b is None:
        return 1.0
    if img_a.shape != img_b.shape:
        return 1.0

    A = img_a.astype(np.float32)
    B = img_b.astype(np.float32)

    muA = A.mean()
    muB = B.mean()

    sigmaA = A.var()
    sigmaB = B.var()

    sigmaAB = np.mean((A - muA) * (B - muB))

    C1 = 0.01 ** 2
    C2 = 0.03 ** 2

    numerator = (2 * muA * muB + C1) * (2 * sigmaAB + C2)
    denominator = (muA**2 + muB**2 + C1) * (sigmaA + sigmaB + C2)

    ssim = numerator / (denominator + eps)

    return float(max(0.0, min(1.0, ssim)))



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
    # Compute SSIM between current and previous frame
    ssim_val = similarity_ssim(img, _prev_frame)

    # per warning ssim
    global _low_ssim_active

    warn = (ssim_val <= _SSIM_WARN_THRESHOLD)

    if warn:
        # beep when in  "warning"
        if not _low_ssim_active:
            QtWidgets.QApplication.beep()
        _low_ssim_active = True
        _diff_win.lbl_stats.setStyleSheet("color: red; font-weight: bold;")
    else:
        _low_ssim_active = False
        _diff_win.lbl_stats.setStyleSheet("")

    stats = (
        f"Min: {diff.min():.1f}  Max: {diff.max():.1f}  Mean: {diff.mean():.1f}  "
        f"SSIM: {ssim_val:.4f}"
    )
    if warn:
        stats += f"   ⚠ SSIM ≤ {_SSIM_WARN_THRESHOLD:.4f}"
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
