"""
Live Difference Viewer & SSIM value + Live SSIM Plot

Shows real-time difference between adjacent frames (frame N vs frame N-1).
Window opens automatically when you execute this script and it shows the value of SSIM
it contains a warning when the value is under a threshold.
Also includes a live plot of SSIM vs time (0..1 on Y axis).
"""

import time
import numpy as np
from PyQt5 import QtWidgets
import pyqtgraph as pg

# Previous frame for comparison
_prev_frame = None

# Diff window
_diff_win = None

# Minimum size to consider a real frame (not test image)
_MIN_FRAME_SIZE = 100

# Warning SSIM
_SSIM_WARN_THRESHOLD = 0.8
_low_ssim_active = False


class DiffWindow(QtWidgets.QWidget):
    """Real-time difference viewer window + SSIM plot."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Difference Viewer (Adjacent Frames)")
        self.setGeometry(100, 100, 800, 900)

        self.running = True
        self.paused = False

        # SSIM time
        self._t0 = None
        self._t = []      # seconds since t0
        self._ssim = []   # values 0..1
        self._max_points = 6000  # keep last N points

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

        self.btn_clear = QtWidgets.QPushButton("Clear plot")
        self.btn_clear.clicked.connect(self._on_clear_plot)
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()

        self.lbl_stats = QtWidgets.QLabel("Waiting for frames...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # Image view
        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        layout.addWidget(self.image_view, stretch=3)

        # SSIM Plot
        self.plot = pg.PlotWidget()
        self.plot.setTitle("SSIM vs Time")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "SSIM (0..1)")
        self.plot.setYRange(0.0, 1.0, padding=0.0)
        self.plot.showGrid(x=True, y=True, alpha=0.2)

        # curve + warning threshold line
        self.curve = self.plot.plot([], [], pen=pg.mkPen(width=2))
        self.th_line = pg.InfiniteLine(
            pos=_SSIM_WARN_THRESHOLD, angle=0,
            pen=pg.mkPen(color='r', width=2, style=pg.QtCore.Qt.DashLine)
        )
        self.plot.addItem(self.th_line)

        layout.addWidget(self.plot, stretch=2)

        self._update_buttons()

    def _on_start(self):
        self.running = True
        self.paused = False
        self._update_buttons()

    def _on_pause(self):
        if self.running:
            self.paused = not self.paused
            self._update_buttons()

    def _on_clear_plot(self):
        self._t0 = None
        self._t.clear()
        self._ssim.clear()
        self.curve.setData([], [])

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

    def add_ssim_point(self, ssim_val: float):
        """Append SSIM point and refresh the plot."""
        if not self.running or self.paused:
            return

        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now

        t = now - self._t0
        self._t.append(t)
        self._ssim.append(float(ssim_val))

        # keep last N points
        if len(self._t) > self._max_points:
            self._t = self._t[-self._max_points:]
            self._ssim = self._ssim[-self._max_points:]

        self.curve.setData(self._t, self._ssim)


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
    global _prev_frame, _diff_win, _low_ssim_active

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
        _diff_win.lbl_stats.setText(
            f"First frame captured ({img.shape[1]}x{img.shape[0]}). Waiting for next..."
        )
        return img

    # Compute difference + SSIM
    diff = np.abs(img.astype(np.float32) - _prev_frame.astype(np.float32))
    ssim_val = similarity_ssim(img, _prev_frame)

    # ---- LIVE PLOT UPDATE ----
    _diff_win.add_ssim_point(ssim_val)

    warn = (ssim_val <= _SSIM_WARN_THRESHOLD)

    if warn:
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

    _prev_frame = img.copy()
    return img


# Reset state and open window when script is executed
_prev_frame = None
_diff_win = DiffWindow()
_diff_win.show()
_diff_win.raise_()
print("Diff window opened. Showing difference + SSIM plot vs time.")
