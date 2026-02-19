"""
Live Plot Viewer (no SciPy) - SNR, CNR (robust)

- Works even if img arrives as (H,W,1) or (1,H,W)
- Patch extraction includes last patch start (+1)
- Uses robust selection (top/bottom-k) instead of percentiles that can yield empty sets
- Avoids sigma==0 early-return traps
"""

import numpy as np
from PyQt5 import QtWidgets
import pyqtgraph as pg

# Plot window
_plot_win = None

# Data buffers
_max_points = 500
_frame_count = 0
_data = {"snr": [], "cnr": []}

# Minimum size to consider a real frame (not test image)
_MIN_FRAME_SIZE = 100


# -------------------------------------------------
# Robust helpers

# -------------------------------------------------
def _ensure_2d(img: np.ndarray):
    """Force image to 2D float32. Returns None if cannot."""
    img = np.asarray(img)
    img = np.squeeze(img)
    if img.ndim == 3:
        img = img[..., 0]
    if img.ndim != 2:
        return None
    return img.astype(np.float32, copy=False)


def _extract_patches(img2d: np.ndarray, patch_size=32) -> np.ndarray:
    """Extract non-overlapping patches; includes last possible patch start."""
    H, W = img2d.shape
    if H < patch_size or W < patch_size:
        return np.empty((0, patch_size, patch_size), dtype=np.float32)

    patches = []
    for y in range(0, H - patch_size + 1, patch_size):
        for x in range(0, W - patch_size + 1, patch_size):
            patches.append(img2d[y: y + patch_size, x: x + patch_size])

    if not patches:
        return np.empty((0, patch_size, patch_size), dtype=np.float32)

    return np.stack(patches, axis=0).astype(np.float32, copy=False)


def grad_energy(patch: np.ndarray) -> float:
    """Mean gradient energy of a patch using numpy.gradient (no SciPy)."""
    gy, gx = np.gradient(patch.astype(np.float32, copy=False))
    return float(np.mean(gx * gx + gy * gy))


# -------------------------------------------------
# SNR reale (patch-based, robust)
# -------------------------------------------------
def snr_real(img, patch_size=32):
    img2d = _ensure_2d(img)
    if img2d is None:
        return 0.0

    patches = _extract_patches(img2d, patch_size=patch_size)
    n = len(patches)
    if n == 0:
        return 0.0

    flat = patches.reshape(n, -1)

    # Noise: k lowest-variance patches
    variances = np.var(flat, axis=1)
    k_noise = max(1, int(0.2 * n))
    noise_idx = np.argpartition(variances, k_noise - 1)[:k_noise]
    noise_patches = patches[noise_idx]
    noise_std = float(np.std(noise_patches)) + 1e-12  # avoid zero

    # Signal: k highest gradient-energy patches
    energies = np.array([grad_energy(p) for p in patches], dtype=np.float32)
    k_sig = max(1, int(0.3 * n))
    sig_idx = np.argpartition(-energies, k_sig - 1)[:k_sig]
    signal_patches = patches[sig_idx]
    signal_mean = float(np.mean(signal_patches))

    snr_lin = signal_mean / noise_std
    return float(20.0 * np.log10(snr_lin + 1e-9))


# -------------------------------------------------
# CNR auto (proxy, robust): |mu_sig - mu_bg| / sigma_bg
# -------------------------------------------------
def cnr_auto(img, patch_size=32):
    img2d = _ensure_2d(img)
    if img2d is None:
        return 0.0

    patches = _extract_patches(img2d, patch_size=patch_size)
    n = len(patches)
    if n == 0:
        return 0.0

    flat = patches.reshape(n, -1)
    variances = np.var(flat, axis=1)

    # Background: k lowest variance patches
    k_bg = max(1, int(0.2 * n))
    bg_idx = np.argpartition(variances, k_bg - 1)[:k_bg]
    bg = patches[bg_idx]
    mu_bg = float(np.mean(bg))
    sigma_bg = float(np.std(bg)) + 1e-12  # avoid zero

    # Signal: k highest gradient energy patches
    energies = np.array([grad_energy(p) for p in patches], dtype=np.float32)
    k_sig = max(1, int(0.3 * n))
    sig_idx = np.argpartition(-energies, k_sig - 1)[:k_sig]
    sig = patches[sig_idx]
    mu_sig = float(np.mean(sig))

    return float(abs(mu_sig - mu_bg) / sigma_bg)


class PlotWindow(QtWidgets.QWidget):
    """Real-time plot viewer window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Plot Viewer")
        self.setGeometry(100, 100, 900, 600)

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

        self.btn_clear = QtWidgets.QPushButton("Clear Plot")
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_clear.setToolTip("Clear plot data")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()

        self.lbl_stats = QtWidgets.QLabel("Waiting for frames...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # Plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("left", "Value")
        self.plot_widget.setLabel("bottom", "Frame")
        self.plot_widget.setTitle("Live Image Statistics")
        self.plot_widget.addLegend()

        # Lines: SNR blue, CNR red
        self.line_snr = self.plot_widget.plot([], [], pen=pg.mkPen("b", width=2), name="SNR (dB)")
        self.line_cnr = self.plot_widget.plot([], [], pen=pg.mkPen("r", width=2), name="CNR")

        layout.addWidget(self.plot_widget)
        self._update_buttons()

    def _on_start(self):
        self.running = True
        self.paused = False
        self._update_buttons()

    def _on_pause(self):
        if self.running:
            self.paused = not self.paused
            self._update_buttons()

    def _on_clear(self):
        global _frame_count, _data
        _frame_count = 0
        _data = {"snr": [], "cnr": []}

        self.line_snr.setData([], [])
        self.line_cnr.setData([], [])

        self.lbl_stats.setText("Plot cleared. Waiting for frames...")

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

    def update_plot(self, stats_text):
        if not self.running or self.paused:
            return

        x = list(range(len(_data["snr"])))
        self.line_snr.setData(x, _data["snr"])
        self.line_cnr.setData(x, _data["cnr"])
        self.lbl_stats.setText(stats_text)


def process(img):
    """Process each frame."""
    global _frame_count, _data, _plot_win

    img2d = _ensure_2d(img)
    if img2d is None:
        return img

    if img2d.shape[0] < _MIN_FRAME_SIZE or img2d.shape[1] < _MIN_FRAME_SIZE:
        return img

    if _plot_win is None or not _plot_win.running or _plot_win.paused:
        return img

    img_snr = float(snr_real(img2d))
    img_cnr = float(cnr_auto(img2d))

    _data["snr"].append(img_snr)
    _data["cnr"].append(img_cnr)

    if len(_data["snr"]) > _max_points:
        for key in _data:
            _data[key] = _data[key][-_max_points:]

    _frame_count += 1

    stats = f"Frame {_frame_count}: SNR={img_snr:.2f} dB | CNR={img_cnr:.2f}"
    _plot_win.update_plot(stats)

    return img


# Reset state and open window when script is executed
_frame_count = 0
_data = {"snr": [], "cnr": []}

_plot_win = PlotWindow()
_plot_win.show()
_plot_win.raise_()

print("Plot window opened. Showing SNR/CNR vs frame number.")
