"""
Live Plot Viewer

Shows real-time plot of image statistics updated with each frame.
Window opens automatically when you execute this script.
"""

import numpy as np
from scipy.ndimage import sobel
from PyQt5 import QtWidgets
import pyqtgraph as pg

# Plot window
_plot_win = None

# Data buffers
_max_points = 500
_frame_count = 0
_data = {
    'mean': [],
    'max': [],
    'min': [],
    'std': [],
    'snr': [],   # SNR (dB)
    'cnr': [],   # CNR (unitless)
}

# Minimum size to consider a real frame (not test image)
_MIN_FRAME_SIZE = 100


class PlotWindow(QtWidgets.QWidget):
    """Real-time plot viewer window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Plot Viewer")
        self.setGeometry(100, 100, 1000, 750)

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

        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_clear.setToolTip("Clear all data")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()

        self.lbl_stats = QtWidgets.QLabel("Waiting for frames...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # --- Plot 1: basic stats ---
        self.plot_stats = pg.PlotWidget()
        self.plot_stats.setBackground('w')
        self.plot_stats.showGrid(x=True, y=True, alpha=0.3)
        self.plot_stats.setLabel('left', 'Value')
        self.plot_stats.setLabel('bottom', 'Frame')
        self.plot_stats.addLegend()

        self.line_mean = self.plot_stats.plot([], [], pen=pg.mkPen('b', width=2), name='Mean')
        self.line_max  = self.plot_stats.plot([], [], pen=pg.mkPen('r', width=1), name='Max')
        self.line_min  = self.plot_stats.plot([], [], pen=pg.mkPen('g', width=1), name='Min')
        self.line_std  = self.plot_stats.plot([], [], pen=pg.mkPen('m', width=1, style=2), name='Std')

        # --- Plot 2: SNR / CNR ---
        self.plot_qc = pg.PlotWidget()
        self.plot_qc.setBackground('w')
        self.plot_qc.showGrid(x=True, y=True, alpha=0.3)
        self.plot_qc.setLabel('left', 'Quality')
        self.plot_qc.setLabel('bottom', 'Frame')
        self.plot_qc.addLegend()

        # Link X axis (zoom/pan insieme)
        self.plot_qc.setXLink(self.plot_stats)

        self.line_snr = self.plot_qc.plot([], [], pen=pg.mkPen('c', width=2), name='SNR (dB)')
        self.line_cnr = self.plot_qc.plot([], [], pen=pg.mkPen('y', width=2), name='CNR')

        layout.addWidget(self.plot_stats, stretch=3)
        layout.addWidget(self.plot_qc, stretch=2)

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
        _data = {
            'mean': [],
            'max': [],
            'min': [],
            'std': [],
            'snr': [],
            'cnr': [],
        }

        self.line_mean.setData([], [])
        self.line_max.setData([], [])
        self.line_min.setData([], [])
        self.line_std.setData([], [])

        self.line_snr.setData([], [])
        self.line_cnr.setData([], [])

        self.lbl_stats.setText("Data cleared. Waiting for frames...")

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

        x = list(range(len(_data['mean'])))

        # Plot 1
        self.line_mean.setData(x, _data['mean'])
        self.line_max.setData(x, _data['max'])
        self.line_min.setData(x, _data['min'])
        self.line_std.setData(x, _data['std'])

        # Plot 2
        self.line_snr.setData(x, _data['snr'])
        self.line_cnr.setData(x, _data['cnr'])

        self.lbl_stats.setText(stats_text)


#-------------------------------------------------
# SNR reale (patch-based)
#-------------------------------------------------
def snr_real(img, patch_size=32):
    """
    SNR stimato in dB:
    - patch a bassa varianza -> rumore (std)
    - patch ad alta energia di gradiente -> segnale (mean)
    - SNR = 20 log10( signal_mean / noise_std )
    """
    if img.ndim > 2:
        img = img[..., 0]
    img = img.astype(np.float32, copy=False)

    H, W = img.shape
    patches = []

    for y in range(0, H - patch_size + 1, patch_size):
        for x in range(0, W - patch_size + 1, patch_size):
            patches.append(img[y:y + patch_size, x:x + patch_size])

    if len(patches) == 0:
        return 0.0

    patches = np.stack(patches, axis=0)

    variances = np.var(patches.reshape(len(patches), -1), axis=1)
    noise_thresh = np.percentile(variances, 20)
    noise_patches = patches[variances <= noise_thresh]
    if len(noise_patches) == 0:
        return 0.0

    noise_std = float(np.std(noise_patches))
    if noise_std <= 0:
        return 0.0

    grad_energies = []
    for p in patches:
        gx = sobel(p, axis=1)
        gy = sobel(p, axis=0)
        grad_energies.append(np.mean(gx**2 + gy**2))

    grad_energies = np.array(grad_energies, dtype=np.float32)
    signal_thresh = np.percentile(grad_energies, 70)
    signal_patches = patches[grad_energies >= signal_thresh]
    if len(signal_patches) == 0:
        return 0.0

    signal_mean = float(np.mean(signal_patches))

    snr_lin = signal_mean / noise_std
    return float(20.0 * np.log10(snr_lin + 1e-9))


#-------------------------------------------------
# CNR reale (patch-based)
#-------------------------------------------------
def cnr_patch_based(img, patch_size=32):
    """
    CNR:
    - patch piatte (bassa energia di gradiente) = background/rumore
    - patch strutturate (alta energia di gradiente) = segnale
    - CNR = (mean_signal - mean_background) / std_background
    """
    if img.ndim > 2:
        img = img[..., 0]
    img = img.astype(np.float32, copy=False)

    H, W = img.shape
    patches = []
    grad_energy = []

    for y in range(0, H - patch_size + 1, patch_size):
        for x in range(0, W - patch_size + 1, patch_size):
            p = img[y:y + patch_size, x:x + patch_size]
            patches.append(p)

            gx = sobel(p, axis=1)
            gy = sobel(p, axis=0)
            grad_energy.append(np.mean(gx**2 + gy**2))

    if len(patches) == 0:
        return 0.0

    patches = np.stack(patches, axis=0)
    grad_energy = np.array(grad_energy, dtype=np.float32)

    noise_thresh = np.percentile(grad_energy, 20)
    noise_patches = patches[grad_energy <= noise_thresh]
    if len(noise_patches) == 0:
        return 0.0

    noise_std = float(np.std(noise_patches))
    if noise_std <= 0:
        return 0.0

    background_mean = float(np.mean(noise_patches))

    signal_thresh = np.percentile(grad_energy, 70)
    signal_patches = patches[grad_energy >= signal_thresh]
    if len(signal_patches) == 0:
        return 0.0

    signal_mean = float(np.mean(signal_patches))

    cnr = (signal_mean - background_mean) / (noise_std + 1e-8)
    return float(cnr)


#-------------------------------------------------
# process
#-------------------------------------------------
def process(img):
    """Process each frame."""
    global _frame_count, _data, _plot_win

    if img.shape[0] < _MIN_FRAME_SIZE or img.shape[1] < _MIN_FRAME_SIZE:
        return img

    if _plot_win is None or not _plot_win.running or _plot_win.paused:
        return img

    img_mean = float(np.mean(img))
    img_max  = float(np.max(img))
    img_min  = float(np.min(img))
    img_std  = float(np.std(img))

    img_snr = snr_real(img, patch_size=32)
    img_cnr = cnr_patch_based(img, patch_size=32)

    _data['mean'].append(img_mean)
    _data['max'].append(img_max)
    _data['min'].append(img_min)
    _data['std'].append(img_std)
    _data['snr'].append(img_snr)
    _data['cnr'].append(img_cnr)

    if len(_data['mean']) > _max_points:
        for key in _data:
            _data[key] = _data[key][-_max_points:]

    _frame_count += 1

    stats = (
        f"Frame {_frame_count}: "
        f"Mean={img_mean:.1f} Max={img_max:.1f} Min={img_min:.1f} Std={img_std:.1f} "
        f"SNR={img_snr:.2f} dB CNR={img_cnr:.2f}"
    )
    _plot_win.update_plot(stats)

    return img


# Reset state and open window when script is executed
_frame_count = 0
_data = {'mean': [], 'max': [], 'min': [], 'std': [], 'snr': [], 'cnr': []}
_plot_win = PlotWindow()
_plot_win.show()
_plot_win.raise_()
print("Plot window opened. Plot1: mean/max/min/std. Plot2: SNR(dB)/CNR vs frame number.")
