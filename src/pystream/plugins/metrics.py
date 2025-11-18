#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Image Information Metrics Plugin for PyStream Viewer
-----------------------------------------------------
Real-time monitoring of image information content metrics:
- Shannon entropy (bits/pixel)
- Normalized entropy (0..1)
- Zlib compressibility (bytes/pixel)
- Laplacian variance (focus/texture)
- Spectral entropy (power spectrum)
- Mutual information vs reference (optional)
"""

import os
import time
import threading
import queue
from typing import Optional, Tuple
import logging

import numpy as np
import pvaccess as pva

from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

try:
    from scipy.signal import convolve2d as conv2
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

try:
    from scipy.fft import fft2
except ImportError:
    from numpy.fft import fft2


# -------------------------
# Image Information Metrics
# -------------------------

def to_gray_float01(arr: np.ndarray) -> np.ndarray:
    """Convert image array to grayscale float32 in [0,1]."""
    if arr.ndim == 3 and arr.shape[-1] in (3, 4):
        # RGB/RGBA to grayscale
        if arr.shape[-1] == 4:
            arr = arr[..., :3]
        if arr.dtype.kind in "ui":
            arrf = arr.astype(np.float32) / 255.0
        else:
            arrf = arr.astype(np.float32)
        g = 0.2126 * arrf[..., 0] + 0.7152 * arrf[..., 1] + 0.0722 * arrf[..., 2]
    else:
        # Single channel
        g = arr.astype(np.float32)
        if arr.dtype.kind in "ui":
            info = np.iinfo(arr.dtype)
            g = g / float(info.max)
    
    g = np.clip(g, 0.0, 1.0)
    g = np.nan_to_num(g, nan=0.0, posinf=1.0, neginf=0.0)
    return g


def shannon_entropy_bits(img: np.ndarray, bins: int = 256) -> float:
    """Shannon entropy H = -sum p log2 p."""
    hist, _ = np.histogram(img, bins=bins, range=(0.0, 1.0), density=False)
    total = hist.sum()
    if total == 0:
        return 0.0
    p = hist.astype(np.float64) / float(total)
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def normalized_entropy(img: np.ndarray, bins: int = 256) -> float:
    """Entropy normalized by log2(bins) -> [0,1]."""
    H = shannon_entropy_bits(img, bins=bins)
    Hmax = np.log2(bins)
    return float(H / Hmax) if Hmax > 0 else 0.0


def zlib_compressibility(img: np.ndarray, bins: int = 256) -> float:
    """Zlib compressed bytes per pixel."""
    import zlib
    q = np.clip((img * (bins - 1)).round().astype(np.uint16), 0, bins - 1)
    by = q.tobytes(order="C")
    comp = zlib.compress(by, level=9)
    return float(len(comp) / img.size)


def laplacian_variance(img: np.ndarray) -> float:
    """Variance of Laplacian (focus/texture measure)."""
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    
    if _HAS_SCIPY:
        L = conv2(img, k, mode='same', boundary='symm')
    else:
        # Fallback without scipy
        pad = np.pad(img, 1, mode='edge')
        L = (pad[1:-1, 2:] + pad[1:-1, :-2] + 
             pad[2:, 1:-1] + pad[:-2, 1:-1] - 4 * pad[1:-1, 1:-1])
    
    return float(np.var(L, dtype=np.float64))


def spectral_entropy(img: np.ndarray, eps: float = 1e-12) -> float:
    """Entropy of normalized power spectrum."""
    h, w = img.shape
    
    # Apply Hann window
    wy = np.hanning(h)[:, None]
    wx = np.hanning(w)[None, :]
    win = wy * wx
    
    F = fft2(img * win)
    P = np.abs(F) ** 2
    P[0, 0] = 0.0  # Remove DC
    
    S = P / (P.sum() + eps)
    S = S[S > 0]
    
    return float(-np.sum(S * np.log2(S + eps)))


def spectral_centroid(img: np.ndarray) -> float:
    """Spectral centroid - center of mass of frequency spectrum (normalized 0-1)."""
    h, w = img.shape
    
    # Apply Hann window
    wy = np.hanning(h)[:, None]
    wx = np.hanning(w)[None, :]
    win = wy * wx
    
    F = fft2(img * win)
    P = np.abs(F) ** 2
    P[0, 0] = 0.0  # Remove DC
    
    # Frequency coordinates
    fy = np.fft.fftfreq(h)
    fx = np.fft.fftfreq(w)
    
    # Distance from DC (0,0) for each frequency
    FY, FX = np.meshgrid(fy, fx, indexing='ij')
    freq_dist = np.sqrt(FY**2 + FX**2)
    
    # Weighted average frequency
    total_power = P.sum()
    if total_power > 0:
        centroid = np.sum(freq_dist * P) / total_power
    else:
        centroid = 0.0
    
    # Normalize to 0-1 (max frequency is ~0.707 for Nyquist)
    return float(centroid / 0.707)


def high_frequency_energy(img: np.ndarray, threshold: float = 0.3) -> float:
    """Ratio of high-frequency energy to total energy (sharpness indicator)."""
    h, w = img.shape
    
    # Apply Hann window
    wy = np.hanning(h)[:, None]
    wx = np.hanning(w)[None, :]
    win = wy * wx
    
    F = fft2(img * win)
    P = np.abs(F) ** 2
    P[0, 0] = 0.0  # Remove DC
    
    # Frequency coordinates
    fy = np.fft.fftfreq(h)
    fx = np.fft.fftfreq(w)
    FY, FX = np.meshgrid(fy, fx, indexing='ij')
    freq_dist = np.sqrt(FY**2 + FX**2)
    
    # High frequency mask (beyond threshold)
    high_freq_mask = freq_dist > threshold
    
    total_energy = P.sum()
    if total_energy > 0:
        high_freq_energy = P[high_freq_mask].sum()
        ratio = high_freq_energy / total_energy
    else:
        ratio = 0.0
    
    return float(ratio)


def gradient_magnitude(img: np.ndarray) -> float:
    """Mean gradient magnitude (edge/detail content)."""
    # Compute gradients
    gy, gx = np.gradient(img)
    
    # Magnitude
    mag = np.sqrt(gx**2 + gy**2)
    
    return float(np.mean(mag))


def spectral_flatness(img: np.ndarray, eps: float = 1e-12) -> float:
    """Spectral flatness (Wiener entropy) - ratio of geometric to arithmetic mean.
    Close to 1 = noise-like (flat spectrum), close to 0 = tonal (peaked spectrum)."""
    h, w = img.shape
    
    # Apply Hann window
    wy = np.hanning(h)[:, None]
    wx = np.hanning(w)[None, :]
    win = wy * wx
    
    F = fft2(img * win)
    P = np.abs(F) ** 2
    P[0, 0] = 0.0  # Remove DC
    P = P.ravel()
    P = P[P > eps]  # Non-zero values
    
    if len(P) == 0:
        return 0.0
    
    # Geometric mean
    log_P = np.log(P + eps)
    geom_mean = np.exp(np.mean(log_P))
    
    # Arithmetic mean
    arith_mean = np.mean(P)
    
    flatness = geom_mean / (arith_mean + eps)
    
    return float(flatness)


def mutual_information(img_a: np.ndarray, img_b: np.ndarray, bins: int = 64) -> float:
    """Mutual information I(A;B) in bits."""
    ha, _ = np.histogram(img_a, bins=bins, range=(0.0, 1.0))
    hb, _ = np.histogram(img_b, bins=bins, range=(0.0, 1.0))
    jab, _, _ = np.histogram2d(img_a.ravel(), img_b.ravel(), 
                               bins=bins, range=[[0, 1], [0, 1]])
    
    pa = ha / ha.sum() if ha.sum() > 0 else np.zeros_like(ha, dtype=float)
    pb = hb / hb.sum() if hb.sum() > 0 else np.zeros_like(hb, dtype=float)
    pab = jab / jab.sum() if jab.sum() > 0 else np.zeros_like(jab, dtype=float)
    
    def H(p):
        p = p[p > 0]
        return -np.sum(p * np.log2(p))
    
    Ha = H(pa)
    Hb = H(pb)
    Hab = H(pab.ravel())
    
    return float(Ha + Hb - Hab)


def compute_all_metrics(img: np.ndarray, bins: int = 256, 
                       ref: Optional[np.ndarray] = None) -> dict:
    """Compute all information metrics for an image."""
    img_gray = to_gray_float01(img)
    
    metrics = {
        'shannon_entropy': shannon_entropy_bits(img_gray, bins),
        'normalized_entropy': normalized_entropy(img_gray, bins),
        'zlib_compressibility': zlib_compressibility(img_gray, bins),
        'laplacian_variance': laplacian_variance(img_gray),
        'spectral_entropy': spectral_entropy(img_gray),
        'spectral_centroid': spectral_centroid(img_gray),
        'high_frequency_energy': high_frequency_energy(img_gray),
        'gradient_magnitude': gradient_magnitude(img_gray),
        'spectral_flatness': spectral_flatness(img_gray),
    }
    
    if ref is not None:
        ref_gray = to_gray_float01(ref)
        if ref_gray.shape == img_gray.shape:
            metrics['mutual_information'] = mutual_information(
                img_gray, ref_gray, bins=min(64, bins // 2))
        else:
            metrics['mutual_information'] = 0.0
    
    # Compute interest score (0-1 scale, higher = more interesting)
    # Combines multiple metrics weighted by importance
    interest = 0.0
    interest += metrics['normalized_entropy'] * 0.25  # Information content
    interest += metrics['laplacian_variance'] / 500.0 * 0.25  # Focus/sharpness (normalized)
    interest += metrics['spectral_entropy'] / 15.0 * 0.20  # Frequency richness
    interest += metrics['high_frequency_energy'] * 0.15  # Detail content
    interest += metrics['gradient_magnitude'] * 2.0 * 0.15  # Edge content
    
    metrics['interest_score'] = min(1.0, max(0.0, float(interest)))
    
    return metrics


# -------------------------
# PVA Subscriber
# -------------------------

def pva_get_ndarray(det_pv):
    """Fetch NTNDArray via pvaccess and return numpy array."""
    ch = pva.Channel(det_pv)
    st = ch.get()
    val = st['value'][0]
    
    for key in ('ushortValue', 'shortValue', 'intValue', 'floatValue',
                'doubleValue', 'ubyteValue', 'byteValue'):
        if key in val:
            flat = np.asarray(val[key])
            break
    else:
        raise RuntimeError("Unsupported NTNDArray type")
    
    # Try to get dimensions from PVA structure
    dims = []
    try:
        if 'dimension' in st:
            dims = st['dimension']
    except Exception:
        pass
    
    # Validate dimensions match array size
    if len(dims) >= 2:
        try:
            h = int(dims[0]['size'])
            w = int(dims[1]['size'])
            if h * w == flat.size:
                return flat.reshape(h, w)
        except Exception:
            pass
    
    # Fallback: try common image dimensions
    size = flat.size
    
    # Try to find two factors close to square
    # Common camera resolutions
    common_shapes = [
        (480, 640), (640, 480),  # VGA
        (600, 800), (800, 600),  # SVGA
        (768, 1024), (1024, 768),  # XGA
        (1080, 1920), (1920, 1080),  # HD
        (1200, 1600), (1600, 1200),  # UXGA
    ]
    
    for h, w in common_shapes:
        if h * w == size:
            return flat.reshape(h, w)
    
    # Last resort: square or closest to square
    side = int(np.sqrt(size))
    if side * side == size:
        return flat.reshape(side, side)
    
    # Find closest factors
    for i in range(side, 0, -1):
        if size % i == 0:
            h = i
            w = size // i
            return flat.reshape(h, w)
    
    # Give up, return 1D
    raise RuntimeError(f"Cannot determine shape for array of size {size}")


# -------------------------
# Information Monitor Dialog
# -------------------------

class ImageInfoDialog(QtWidgets.QDialog):
    """Real-time image information metrics monitor"""
    
    metrics_updated = QtCore.pyqtSignal(dict, float)  # metrics, timestamp
    
    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Image Information Metrics")
        self.setGeometry(100, 100, 1200, 800)
        
        # State
        self._running = False
        self._worker_thread = None
        self._reference_frame = None
        self._frame_count = 0
        self._start_time = None
        
        # Data storage
        self.max_points = 1000
        self.times = []
        self.data = {
            'shannon_entropy': [],
            'normalized_entropy': [],
            'zlib_compressibility': [],
            'laplacian_variance': [],
            'spectral_entropy': [],
            'spectral_centroid': [],
            'high_frequency_energy': [],
            'gradient_magnitude': [],
            'spectral_flatness': [],
            'mutual_information': [],
            'interest_score': [],
        }
        
        # Track best frame
        self.best_frame_idx = -1
        self.best_interest_score = 0.0
        
        # Track ALL interesting frames (above threshold)
        self.interesting_frames = []  # List of (frame_idx, time, interest_score, metrics_dict)
        self.interest_threshold = 0.6  # Configurable threshold
        
        # Tomography mode
        self.tomography_mode = False
        self.start_angle = 0.0  # degrees
        self.angular_spacing = 0.5  # degrees per frame
        
        # Tomography angular projection tracking
        self.tomography_enabled = False
        self.angle_start = 0.0
        self.angle_end = 360.0
        self.angular_spacing = 0.5  # degrees per frame
        
        self._build_ui()
        self.metrics_updated.connect(self._on_metrics_update)
        
    def _build_ui(self):
        """Build the UI with dark theme"""
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                color: #d4d4d4;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                min-width: 70px;
                padding: 6px 12px;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #2d2d2d;
                color: #d4d4d4;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                border: 1px solid #777777;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
            QPushButton:disabled {
                background-color: #1e1e1e;
                color: #666666;
            }
            QLineEdit {
                background-color: #2d2d2d;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 4px;
                color: #d4d4d4;
            }
            QLabel {
                color: #d4d4d4;
            }
            QSpinBox {
                background-color: #2d2d2d;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 4px;
                color: #d4d4d4;
            }
        """)
        
        main_layout = QtWidgets.QVBoxLayout(self)
        
        # === TOP CONTROLS ===
        controls_group = QtWidgets.QGroupBox("Controls")
        controls_layout = QtWidgets.QHBoxLayout()
        
        # PV input
        controls_layout.addWidget(QtWidgets.QLabel("Detector PV:"))
        self.pv_input = QtWidgets.QLineEdit("32idbSP1:Pva1:Image")
        self.pv_input.setMinimumWidth(200)
        controls_layout.addWidget(self.pv_input)
        
        # Bins
        controls_layout.addWidget(QtWidgets.QLabel("Bins:"))
        self.bins_spin = QtWidgets.QSpinBox()
        self.bins_spin.setRange(16, 512)
        self.bins_spin.setValue(256)
        controls_layout.addWidget(self.bins_spin)
        
        # Interest threshold
        controls_layout.addWidget(QtWidgets.QLabel("Interest Threshold:"))
        self.threshold_spin = QtWidgets.QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.6)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.valueChanged.connect(self._on_threshold_changed)
        controls_layout.addWidget(self.threshold_spin)
        
        # Tomography mode
        self.chk_tomo = QtWidgets.QCheckBox("Tomography Mode")
        self.chk_tomo.stateChanged.connect(self._on_tomo_mode_changed)
        controls_layout.addWidget(self.chk_tomo)
        
        # Start angle
        #controls_layout.addWidget(QtWidgets.QLabel("Start Angle (°):"))
        #self.start_angle_spin = QtWidgets.QDoubleSpinBox()
        #self.start_angle_spin.setRange(-360.0, 360.0)
        #self.start_angle_spin.setSingleStep(1.0)
       #self.start_angle_spin.setValue(0.0)
        #self.start_angle_spin.setDecimals(2)
       # self.start_angle_spin.setEnabled(False)
       # controls_layout.addWidget(self.start_angle_spin)
        
        # Angular spacing
       # controls_layout.addWidget(QtWidgets.QLabel("Spacing (°/frame):"))
       # self.angular_spacing_spin = QtWidgets.QDoubleSpinBox()
        #self.angular_spacing_spin.setRange(0.001, 180.0)
       # self.angular_spacing_spin.setSingleStep(0.1)
       # self.angular_spacing_spin.setValue(0.5)
       # self.angular_spacing_spin.setDecimals(3)
       # self.angular_spacing_spin.setEnabled(False)
       # controls_layout.addWidget(self.angular_spacing_spin)
        
        # Start/Stop buttons
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.clicked.connect(self._start_monitoring)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #2d5016;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #3d6026; }
        """)
        controls_layout.addWidget(self.btn_start)
        
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.clicked.connect(self._stop_monitoring)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #5d1616;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #6d2626; }
        """)
        controls_layout.addWidget(self.btn_stop)
        
        # Capture reference
        self.btn_capture_ref = QtWidgets.QPushButton("Capture Reference")
        self.btn_capture_ref.clicked.connect(self._capture_reference)
        controls_layout.addWidget(self.btn_capture_ref)
        
        # Clear reference
        self.btn_clear_ref = QtWidgets.QPushButton("Clear Reference")
        self.btn_clear_ref.clicked.connect(self._clear_reference)
        controls_layout.addWidget(self.btn_clear_ref)
        
        controls_layout.addStretch()
        
        # Frame count
        self.lbl_frame_count = QtWidgets.QLabel("Frames: 0")
        self.lbl_frame_count.setStyleSheet("font-weight: bold;")
        controls_layout.addWidget(self.lbl_frame_count)
        
        controls_group.setLayout(controls_layout)
        main_layout.addWidget(controls_group)
        
        # === TOMOGRAPHY SETTINGS ===
        tomo_group = QtWidgets.QGroupBox("Tomography Angular Projection")
        tomo_layout = QtWidgets.QHBoxLayout()
        
        self.chk_tomography = QtWidgets.QCheckBox("Enable")
        self.chk_tomography.stateChanged.connect(self._on_tomography_toggled)
        tomo_layout.addWidget(self.chk_tomography)
        
        tomo_layout.addWidget(QtWidgets.QLabel("Start Angle (°):"))
        self.angle_start_spin = QtWidgets.QDoubleSpinBox()
        self.angle_start_spin.setRange(-360, 360)
        self.angle_start_spin.setValue(0.0)
        self.angle_start_spin.setDecimals(2)
        self.angle_start_spin.valueChanged.connect(self._on_angle_params_changed)
        tomo_layout.addWidget(self.angle_start_spin)
        
        tomo_layout.addWidget(QtWidgets.QLabel("End Angle (°):"))
        self.angle_end_spin = QtWidgets.QDoubleSpinBox()
        self.angle_end_spin.setRange(-360, 720)
        self.angle_end_spin.setValue(360.0)
        self.angle_end_spin.setDecimals(2)
        self.angle_end_spin.valueChanged.connect(self._on_angle_params_changed)
        tomo_layout.addWidget(self.angle_end_spin)
        
        tomo_layout.addWidget(QtWidgets.QLabel("Angular Spacing (°/frame):"))
        self.angular_spacing_spin = QtWidgets.QDoubleSpinBox()
        self.angular_spacing_spin.setRange(0.001, 90.0)
        self.angular_spacing_spin.setValue(0.5)
        self.angular_spacing_spin.setDecimals(3)
        self.angular_spacing_spin.setSingleStep(0.1)
        self.angular_spacing_spin.valueChanged.connect(self._on_angle_params_changed)
        tomo_layout.addWidget(self.angular_spacing_spin)
        
        # Total projections label
        self.lbl_total_projections = QtWidgets.QLabel("Total: 720 projections")
        self.lbl_total_projections.setStyleSheet("font-weight: bold; color: #FFD700;")
        tomo_layout.addWidget(self.lbl_total_projections)
        
        tomo_layout.addStretch()
        
        tomo_group.setLayout(tomo_layout)
        main_layout.addWidget(tomo_group)
        
        # Disable tomography controls initially
        self._update_tomography_controls()
        
        # === PLOTS ===
        plots_widget = QtWidgets.QWidget()
        plots_layout = QtWidgets.QGridLayout(plots_widget)
        
        # Create 10 plots (4 rows x 3 cols, last 2 empty)
        self.plots = {}
        metrics_config = [
            # Row 0
            ('interest_score', 'Interest Score ⭐', '0-1', '#FFD700'),
            ('shannon_entropy', 'Shannon Entropy', 'bits/pixel', '#00FF00'),
            ('normalized_entropy', 'Normalized Entropy', '0-1', '#00FFFF'),
            # Row 1
            ('laplacian_variance', 'Laplacian Variance', 'variance', '#FF00FF'),
            ('gradient_magnitude', 'Gradient Magnitude', 'mean', '#FFA500'),
            ('spectral_entropy', 'Spectral Entropy', 'bits', '#FFFF00'),
            # Row 2
            ('spectral_centroid', 'Spectral Centroid', '0-1', '#00FF7F'),
            ('high_frequency_energy', 'High Freq Energy', 'ratio', '#FF69B4'),
            ('spectral_flatness', 'Spectral Flatness', '0-1', '#87CEEB'),
            # Row 3
            ('zlib_compressibility', 'Zlib Compressibility', 'bytes/pixel', '#FFA500'),
            ('mutual_information', 'Mutual Information', 'bits', '#FF0000'),
        ]
        
        for idx, (key, title, ylabel, color) in enumerate(metrics_config):
            row = idx // 3
            col = idx % 3
            
            plot = pg.PlotWidget()
            plot.setBackground('#1e1e1e')
            plot.setTitle(title, color='#d4d4d4', size='10pt')
            plot.setLabel('left', ylabel, color='#d4d4d4', size='9pt')
            plot.setLabel('bottom', 'Time (s)', color='#d4d4d4', size='9pt')
            plot.showGrid(x=True, y=True, alpha=0.3)
            
            # Style axes
            axis_pen = pg.mkPen(color='#888888', width=1)
            plot.getPlotItem().getAxis('bottom').setPen(axis_pen)
            plot.getPlotItem().getAxis('left').setPen(axis_pen)
            plot.getPlotItem().getAxis('bottom').setTextPen('#d4d4d4')
            plot.getPlotItem().getAxis('left').setTextPen('#d4d4d4')
            
            # Create curve
            pen_width = 3 if key == 'interest_score' else 2
            curve = plot.plot([], [], pen=pg.mkPen(color=color, width=pen_width))
            
            # Add markers for interesting frames on interest score plot
            if key == 'interest_score':
                # Single best marker (gold star)
                self.best_marker = pg.ScatterPlotItem(
                    size=15, pen=pg.mkPen('w', width=2), 
                    brush=pg.mkBrush('#FFD700'), symbol='star')
                plot.addItem(self.best_marker)
                
                # All interesting frames markers (green circles)
                self.interesting_markers = pg.ScatterPlotItem(
                    size=10, pen=pg.mkPen('#00FF00', width=2), 
                    brush=pg.mkBrush(0, 255, 0, 100), symbol='o')
                plot.addItem(self.interesting_markers)
                
                # Threshold line
                self.threshold_line = pg.InfiniteLine(
                    pos=0.6, angle=0, pen=pg.mkPen('#FF6600', width=2, style=QtCore.Qt.DashLine),
                    label='Threshold', labelOpts={'position': 0.95, 'color': '#FF6600'})
                plot.addItem(self.threshold_line)
            
            self.plots[key] = {
                'widget': plot,
                'curve': curve,
                'color': color
            }
            
            plots_layout.addWidget(plot, row, col)
        
        main_layout.addWidget(plots_widget, stretch=1)
        
        # === BOTTOM CONTROLS ===
        bottom_layout = QtWidgets.QHBoxLayout()
        
        btn_clear = QtWidgets.QPushButton("Clear Data")
        btn_clear.clicked.connect(self._clear_data)
        bottom_layout.addWidget(btn_clear)
        
        btn_save = QtWidgets.QPushButton("Save Data...")
        btn_save.clicked.connect(self._save_data)
        bottom_layout.addWidget(btn_save)
        
        btn_best_frame = QtWidgets.QPushButton("Show Best Frame")
        btn_best_frame.clicked.connect(self._show_best_frame_info)
        btn_best_frame.setStyleSheet("""
            QPushButton {
                background-color: #3d3d00;
                color: #FFD700;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4d4d00; }
        """)
        bottom_layout.addWidget(btn_best_frame)
        
        btn_all_interesting = QtWidgets.QPushButton("Show All Interesting Frames")
        btn_all_interesting.clicked.connect(self._show_all_interesting_frames)
        btn_all_interesting.setStyleSheet("""
            QPushButton {
                background-color: #003d00;
                color: #00FF00;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #004d00; }
        """)
        bottom_layout.addWidget(btn_all_interesting)
        
        btn_export_interesting = QtWidgets.QPushButton("Export Interesting Frames...")
        btn_export_interesting.clicked.connect(self._export_interesting_frames)
        bottom_layout.addWidget(btn_export_interesting)
        
        bottom_layout.addStretch()
        
        # Show count of interesting frames
        self.lbl_interesting_count = QtWidgets.QLabel("Interesting: 0")
        self.lbl_interesting_count.setStyleSheet("font-weight: bold; color: #00FF00;")
        bottom_layout.addWidget(self.lbl_interesting_count)
        
        main_layout.addLayout(bottom_layout)
        
    def _start_monitoring(self):
        """Start monitoring PV"""
        pv_name = self.pv_input.text().strip()
        if not pv_name:
            QtWidgets.QMessageBox.warning(self, "No PV", "Please enter a PV name")
            return
        
        self._running = True
        self._frame_count = 0
        self._start_time = time.time()
        
        # Update axis labels based on tomography mode
        self._update_axis_labels()
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.pv_input.setEnabled(False)
        
        # Start worker thread
        self._worker_thread = threading.Thread(
            target=self._monitor_worker,
            args=(pv_name, self.bins_spin.value()),
            daemon=True
        )
        self._worker_thread.start()
        
        self._log("Started monitoring")
        
    def _stop_monitoring(self):
        """Stop monitoring"""
        self._running = False
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.pv_input.setEnabled(True)
        
        self._log("Stopped monitoring")
        
    def _monitor_worker(self, pv_name: str, bins: int):
        """Worker thread to fetch frames and compute metrics"""
        try:
            while self._running:
                try:
                    # Fetch frame
                    img = pva_get_ndarray(pv_name)
                    
                    # Compute metrics
                    metrics = compute_all_metrics(
                        img, bins=bins, ref=self._reference_frame)
                    
                    # Emit signal
                    elapsed = time.time() - self._start_time
                    self.metrics_updated.emit(metrics, elapsed)
                    
                    # Brief sleep to avoid hammering
                    time.sleep(0.05)
                    
                except Exception as ex:
                    if self._running:
                        self._log(f"ERROR: {ex}")
                    time.sleep(0.5)
                    
        except Exception as ex:
            self._log(f"Worker thread error: {ex}")
            
    @QtCore.pyqtSlot(dict, float)
    def _on_metrics_update(self, metrics: dict, elapsed: float):
        """Update plots with new metrics"""
        self._frame_count += 1
        self.lbl_frame_count.setText(f"Frames: {self._frame_count}")
        
        # Get interest score
        interest = metrics.get('interest_score', 0.0)
        
        # Track best frame
        if interest > self.best_interest_score:
            self.best_interest_score = interest
            self.best_frame_idx = self._frame_count - 1
            self._log(f"New best frame #{self.best_frame_idx + 1} (interest: {interest:.3f})")
        
        # Track interesting frames above threshold
        if interest >= self.interest_threshold:
            angle = self._frame_to_angle(self._frame_count - 1)
            frame_info = {
                'frame_idx': self._frame_count - 1,
                'time': elapsed,
                'angle': angle,
                'interest_score': interest,
                'metrics': metrics.copy()
            }
            self.interesting_frames.append(frame_info)
            
            if self.tomography_mode:
                if angle is not None:
                    self._log(f"Interesting projection #{self._frame_count} @ {angle:.2f}° (interest: {interest:.3f})")
                else:
                    self._log(f"Interesting frame #{self._frame_count} (interest: {interest:.3f})")
            else:
                self._log(f"Interesting frame #{self._frame_count} (interest: {interest:.3f})")
        
        # Update interesting count
        self.lbl_interesting_count.setText(f"Interesting: {len(self.interesting_frames)}")
        
        # Add data - use angle for x-axis if tomography mode, otherwise time
        if self.tomography_enabled:
            angle = self._frame_to_angle(self._frame_count - 1)
            self.times.append(angle)
        else:
            self.times.append(elapsed)
        for key in self.data.keys():
            value = metrics.get(key, 0.0)
            self.data[key].append(value)
        
        # Trim if too long
        if len(self.times) > self.max_points:
            self.times = self.times[-self.max_points:]
            for key in self.data.keys():
                self.data[key] = self.data[key][-self.max_points:]
            
            # Also trim interesting_frames to match window
            offset = self._frame_count - self.max_points
            self.interesting_frames = [f for f in self.interesting_frames 
                                      if f['frame_idx'] >= offset]
        
        # Update plots
        times_array = np.array(self.times)
        for key, plot_info in self.plots.items():
            if self.data[key]:  # Has data
                data_array = np.array(self.data[key])
                plot_info['curve'].setData(times_array, data_array)
        
        # Update best frame marker on interest score plot
        if self.best_frame_idx >= 0 and len(self.times) > 0:
            offset = max(0, self._frame_count - self.max_points)
            window_idx = self.best_frame_idx - offset
            
            if 0 <= window_idx < len(self.times):
                best_time = self.times[window_idx]
                best_interest = self.data['interest_score'][window_idx]
                self.best_marker.setData([best_time], [best_interest])
        
        # Update interesting frames markers
        if self.interesting_frames:
            offset = max(0, self._frame_count - self.max_points)
            interesting_times = []
            interesting_scores = []
            
            for frame_info in self.interesting_frames:
                window_idx = frame_info['frame_idx'] - offset
                if 0 <= window_idx < len(self.times):
                    interesting_times.append(self.times[window_idx])
                    interesting_scores.append(self.data['interest_score'][window_idx])
            
            if interesting_times:
                self.interesting_markers.setData(interesting_times, interesting_scores)
    
    def _capture_reference(self):
        """Capture current frame as reference"""
        pv_name = self.pv_input.text().strip()
        if not pv_name:
            QtWidgets.QMessageBox.warning(self, "No PV", "Please enter a PV name")
            return
        
        try:
            self._reference_frame = pva_get_ndarray(pv_name)
            self._log(f"Captured reference frame: {self._reference_frame.shape}")
            QtWidgets.QMessageBox.information(
                self, "Reference Captured",
                f"Reference frame captured\nShape: {self._reference_frame.shape}")
        except Exception as ex:
            QtWidgets.QMessageBox.critical(
                self, "Capture Error", f"Failed to capture reference:\n{ex}")
            self._log(f"ERROR capturing reference: {ex}")
    
    def _clear_reference(self):
        """Clear reference frame"""
        self._reference_frame = None
        self._log("Reference frame cleared")
        QtWidgets.QMessageBox.information(self, "Reference Cleared", 
                                         "Reference frame cleared")
    
    def _clear_data(self):
        """Clear all data"""
        self.times = []
        for key in self.data.keys():
            self.data[key] = []
        
        for plot_info in self.plots.values():
            plot_info['curve'].setData([], [])
        
        self.best_marker.setData([], [])
        self.interesting_markers.setData([], [])
        self.best_frame_idx = -1
        self.best_interest_score = 0.0
        self.interesting_frames = []
        
        self._frame_count = 0
        self.lbl_frame_count.setText("Frames: 0")
        self.lbl_interesting_count.setText("Interesting: 0")
        self._log("Data cleared")
    
    def _save_data(self):
        """Save data to file"""
        if not self.times:
            QtWidgets.QMessageBox.information(self, "No Data", 
                                             "No data to save")
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Data", "", "CSV (*.csv);;NumPy (*.npz);;All Files (*)")
        
        if not path:
            return
        
        try:
            if path.endswith('.npz'):
                # Save as numpy archive
                save_dict = {'times': np.array(self.times)}
                for key, values in self.data.items():
                    if values:
                        save_dict[key] = np.array(values)
                np.savez(path, **save_dict)
                
            else:  # CSV
                import csv
                with open(path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    
                    # Header
                    header = ['time'] + list(self.data.keys())
                    writer.writerow(header)
                    
                    # Data rows
                    for i, t in enumerate(self.times):
                        row = [t]
                        for key in self.data.keys():
                            row.append(self.data[key][i] if i < len(self.data[key]) else 0.0)
                        writer.writerow(row)
            
            self._log(f"Saved data to: {path}")
            QtWidgets.QMessageBox.information(self, "Data Saved", 
                                             f"Data saved to:\n{path}")
            
        except Exception as ex:
            QtWidgets.QMessageBox.critical(self, "Save Error", 
                                          f"Failed to save:\n{ex}")
            self._log(f"ERROR saving data: {ex}")
    
    def _show_best_frame_info(self):
        """Show information about the best frame"""
        if self.best_frame_idx < 0:
            QtWidgets.QMessageBox.information(
                self, "No Best Frame",
                "No frames captured yet or all have zero interest score.")
            return
        
        # Find best frame in current data
        offset = max(0, self._frame_count - self.max_points)
        window_idx = self.best_frame_idx - offset
        
        if window_idx < 0 or window_idx >= len(self.times):
            QtWidgets.QMessageBox.information(
                self, "Best Frame Lost",
                f"Best frame #{self.best_frame_idx + 1} is no longer in the current window.\n"
                f"It had an interest score of {self.best_interest_score:.3f}")
            return
        
        # Get all metrics for best frame
        if self.tomography_enabled:
            time_or_angle_label = f"Angle: {self.times[window_idx]:.2f}°"
        else:
            time_or_angle_label = f"Time: {self.times[window_idx]:.2f} seconds"
        
        info_lines = [
            f"Best Frame: #{self.best_frame_idx + 1}",
            time_or_angle_label,
            "",
            "=== Metrics ===",
            f"Interest Score: {self.data['interest_score'][window_idx]:.4f} ⭐",
            "",
            f"Shannon Entropy: {self.data['shannon_entropy'][window_idx]:.4f} bits/pixel",
            f"Normalized Entropy: {self.data['normalized_entropy'][window_idx]:.4f}",
            f"Laplacian Variance: {self.data['laplacian_variance'][window_idx]:.2f}",
            f"Gradient Magnitude: {self.data['gradient_magnitude'][window_idx]:.4f}",
            "",
            f"Spectral Entropy: {self.data['spectral_entropy'][window_idx]:.4f} bits",
            f"Spectral Centroid: {self.data['spectral_centroid'][window_idx]:.4f}",
            f"High Freq Energy: {self.data['high_frequency_energy'][window_idx]:.4f}",
            f"Spectral Flatness: {self.data['spectral_flatness'][window_idx]:.4f}",
            "",
            f"Zlib Compress: {self.data['zlib_compressibility'][window_idx]:.4f} bytes/px",
        ]
        
        if self._reference_frame is not None:
            info_lines.append(f"Mutual Info: {self.data['mutual_information'][window_idx]:.4f} bits")
        
        info_text = "\n".join(info_lines)
        
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Best Frame Information")
        msg.setText(info_text)
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
        
        # Make it wider
        msg.setStyleSheet("QLabel{min-width: 400px; font-family: monospace;}")
        
        msg.exec_()
        
        self._log(f"Displayed info for best frame #{self.best_frame_idx + 1}")
    
    def _on_threshold_changed(self, value):
        """Handle threshold change"""
        self.interest_threshold = value
        self.threshold_line.setValue(value)
        self._log(f"Interest threshold changed to {value:.2f}")
        
        # Re-evaluate all existing frames
        if self.times:
            self.interesting_frames = []
            offset = max(0, self._frame_count - self.max_points)
            
            for i, interest in enumerate(self.data['interest_score']):
                if interest >= self.interest_threshold:
                    frame_idx = offset + i
                    angle = self._frame_to_angle(frame_idx)
                    
                    # Get all metrics for this frame
                    metrics = {key: self.data[key][i] for key in self.data.keys()}
                    
                    frame_info = {
                        'frame_idx': frame_idx,
                        'time': self.times[i],
                        'angle': angle,
                        'interest_score': interest,
                        'metrics': metrics
                    }
                    self.interesting_frames.append(frame_info)
            
            # Update markers
            if self.interesting_frames:
                interesting_times = [f['time'] for f in self.interesting_frames]
                interesting_scores = [f['interest_score'] for f in self.interesting_frames]
                self.interesting_markers.setData(interesting_times, interesting_scores)
            else:
                self.interesting_markers.setData([], [])
            
            self.lbl_interesting_count.setText(f"Interesting: {len(self.interesting_frames)}")
            self._log(f"Re-evaluated: {len(self.interesting_frames)} interesting frames")
    
    def _on_tomo_mode_changed(self, state):
        """Handle tomography mode toggle"""
        self.tomography_mode = (state == QtCore.Qt.Checked)
        self.start_angle_spin.setEnabled(self.tomography_mode)
        self.angular_spacing_spin.setEnabled(self.tomography_mode)
        
        if self.tomography_mode:
            self.start_angle = self.start_angle_spin.value()
            self.angular_spacing = self.angular_spacing_spin.value()
            self._log(f"Tomography mode enabled: {self.start_angle:.2f}° start, "
                     f"{self.angular_spacing:.3f}°/frame")
        else:
            self._log("Tomography mode disabled")
        
        # Update existing interesting frames with angles
        if self.interesting_frames:
            for frame_info in self.interesting_frames:
                frame_info['angle'] = self._frame_to_angle(frame_info['frame_idx'])
    
    def _frame_to_angle(self, frame_idx):
        """Calculate angle for a given frame index in tomography mode"""
        if not self.tomography_mode:
            return None
        
        # Update current values from spinners
        self.start_angle = self.start_angle_spin.value()
        self.angular_spacing = self.angular_spacing_spin.value()
        
        angle = self.start_angle + (frame_idx * self.angular_spacing)
        
        # Normalize to 0-360 range
        angle = angle % 360.0
        
        return angle
    
    def _show_all_interesting_frames(self):
        """Show list of all interesting frames"""
        if not self.interesting_frames:
            QtWidgets.QMessageBox.information(
                self, "No Interesting Frames",
                f"No frames above threshold {self.interest_threshold:.2f} yet.")
            return
        
        # Create dialog with table
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Interesting Frames (threshold ≥ {self.interest_threshold:.2f})")
        dialog.setGeometry(100, 100, 1400, 600)
        dialog.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # Table
        table = QtWidgets.QTableWidget()
        table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                color: #d4d4d4;
                gridline-color: #555555;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #d4d4d4;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #555555;
            }
        """)
        
        # Sort by interest score descending
        sorted_frames = sorted(self.interesting_frames, 
                              key=lambda x: x['interest_score'], reverse=True)
        
        # Determine columns based on tomography mode and reference frame
        table.setRowCount(len(sorted_frames))
        has_mi = self._reference_frame is not None
        
        if self.tomography_mode:
            num_cols = 12 if has_mi else 11
            table.setColumnCount(num_cols)
            headers = ['Frame #', 'Angle (°)', 'Interest', 
                      'Shannon Ent', 'Norm Ent', 'Laplacian Var',
                      'Gradient Mag', 'Spectral Ent', 'Spectral Cent',
                      'HF Energy', 'Spectral Flat', 'Zlib Compress']
            if has_mi:
                headers.append('Mutual Info')
            table.setHorizontalHeaderLabels(headers)
        else:
            num_cols = 12 if has_mi else 11
            table.setColumnCount(num_cols)
            headers = ['Frame #', 'Time (s)', 'Interest', 
                      'Shannon Ent', 'Norm Ent', 'Laplacian Var',
                      'Gradient Mag', 'Spectral Ent', 'Spectral Cent',
                      'HF Energy', 'Spectral Flat', 'Zlib Compress']
            if has_mi:
                headers.append('Mutual Info')
            table.setHorizontalHeaderLabels(headers)
        
        for row, frame_info in enumerate(sorted_frames):
            col = 0
            metrics = frame_info['metrics']
            
            # Frame number
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{frame_info['frame_idx'] + 1}"))
            col += 1
            
            # Angle (if tomography mode) OR Time (if not)
            if self.tomography_mode:
                angle = frame_info.get('angle')
                if angle is not None:
                    table.setItem(row, col, QtWidgets.QTableWidgetItem(
                        f"{angle:.2f}"))
                else:
                    table.setItem(row, col, QtWidgets.QTableWidgetItem("N/A"))
                col += 1
            else:
                # Show time when not in tomography mode
                table.setItem(row, col, QtWidgets.QTableWidgetItem(
                    f"{frame_info['time']:.2f}"))
                col += 1
            
            # Interest score
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{frame_info['interest_score']:.4f}"))
            col += 1
            
            # Shannon entropy
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('shannon_entropy', 0):.3f}"))
            col += 1
            
            # Normalized entropy
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('normalized_entropy', 0):.3f}"))
            col += 1
            
            # Laplacian variance
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('laplacian_variance', 0):.2f}"))
            col += 1
            
            # Gradient magnitude
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('gradient_magnitude', 0):.4f}"))
            col += 1
            
            # Spectral entropy
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('spectral_entropy', 0):.3f}"))
            col += 1
            
            # Spectral centroid
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('spectral_centroid', 0):.3f}"))
            col += 1
            
            # High frequency energy
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('high_frequency_energy', 0):.3f}"))
            col += 1
            
            # Spectral flatness
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('spectral_flatness', 0):.3f}"))
            col += 1
            
            # Zlib compressibility
            table.setItem(row, col, QtWidgets.QTableWidgetItem(
                f"{metrics.get('zlib_compressibility', 0):.3f}"))
            col += 1
            
            # Mutual information (if reference frame set)
            if has_mi:
                table.setItem(row, col, QtWidgets.QTableWidgetItem(
                    f"{metrics.get('mutual_information', 0):.3f}"))
        
        table.resizeColumnsToContents()
        layout.addWidget(table)
        
        # Info label
        info_label = QtWidgets.QLabel(
            f"Total: {len(sorted_frames)} interesting frames\n"
            f"Sorted by interest score (highest first)")
        info_label.setStyleSheet("font-weight: bold; padding: 10px;")
        layout.addWidget(info_label)
        
        # Close button
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(dialog.close)
        layout.addWidget(btn_close)
        
        dialog.exec_()
    
    def _export_interesting_frames(self):
        """Export list of interesting frames to CSV"""
        if not self.interesting_frames:
            QtWidgets.QMessageBox.information(
                self, "No Interesting Frames",
                f"No frames above threshold {self.interest_threshold:.2f} to export.")
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Interesting Frames", "", "CSV (*.csv);;All Files (*)")
        
        if not path:
            return
        
        try:
            import csv
            
            # Sort by frame index
            sorted_frames = sorted(self.interesting_frames, 
                                  key=lambda x: x['frame_idx'])
            
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Header - all metrics
                if self.tomography_mode:
                    header = ['frame_number', 'angle_degrees', 'time_seconds', 'interest_score',
                             'shannon_entropy', 'normalized_entropy', 'laplacian_variance',
                             'gradient_magnitude', 'spectral_entropy', 'spectral_centroid',
                             'high_frequency_energy', 'spectral_flatness', 'zlib_compressibility']
                else:
                    header = ['frame_number', 'time_seconds', 'interest_score',
                             'shannon_entropy', 'normalized_entropy', 'laplacian_variance',
                             'gradient_magnitude', 'spectral_entropy', 'spectral_centroid',
                             'high_frequency_energy', 'spectral_flatness', 'zlib_compressibility']
                
                if self._reference_frame is not None:
                    header.append('mutual_information')
                
                writer.writerow(header)
                
                # Data rows
                for frame_info in sorted_frames:
                    metrics = frame_info['metrics']
                    
                    if self.tomography_mode:
                        angle = frame_info.get('angle')
                        row = [
                            frame_info['frame_idx'] + 1,  # 1-indexed
                            f"{angle:.3f}" if angle is not None else "N/A",
                            f"{frame_info['time']:.3f}",
                            f"{frame_info['interest_score']:.4f}",
                            f"{metrics.get('shannon_entropy', 0):.4f}",
                            f"{metrics.get('normalized_entropy', 0):.4f}",
                            f"{metrics.get('laplacian_variance', 0):.2f}",
                            f"{metrics.get('gradient_magnitude', 0):.4f}",
                            f"{metrics.get('spectral_entropy', 0):.4f}",
                            f"{metrics.get('spectral_centroid', 0):.4f}",
                            f"{metrics.get('high_frequency_energy', 0):.4f}",
                            f"{metrics.get('spectral_flatness', 0):.4f}",
                            f"{metrics.get('zlib_compressibility', 0):.4f}",
                        ]
                    else:
                        row = [
                            frame_info['frame_idx'] + 1,  # 1-indexed
                            f"{frame_info['time']:.3f}",
                            f"{frame_info['interest_score']:.4f}",
                            f"{metrics.get('shannon_entropy', 0):.4f}",
                            f"{metrics.get('normalized_entropy', 0):.4f}",
                            f"{metrics.get('laplacian_variance', 0):.2f}",
                            f"{metrics.get('gradient_magnitude', 0):.4f}",
                            f"{metrics.get('spectral_entropy', 0):.4f}",
                            f"{metrics.get('spectral_centroid', 0):.4f}",
                            f"{metrics.get('high_frequency_energy', 0):.4f}",
                            f"{metrics.get('spectral_flatness', 0):.4f}",
                            f"{metrics.get('zlib_compressibility', 0):.4f}",
                        ]
                    
                    if self._reference_frame is not None:
                        row.append(f"{metrics.get('mutual_information', 0):.4f}")
                    
                    writer.writerow(row)
            
            self._log(f"Exported {len(sorted_frames)} interesting frames to: {path}")
            QtWidgets.QMessageBox.information(
                self, "Export Complete",
                f"Exported {len(sorted_frames)} interesting frames to:\n{path}")
            
        except Exception as ex:
            QtWidgets.QMessageBox.critical(
                self, "Export Error", f"Failed to export:\n{ex}")
            self._log(f"ERROR exporting interesting frames: {ex}")
    
    def _log(self, message: str):
        """Log message"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
        if self.logger:
            self.logger.info(f"[ImageInfo] {message}")
    
    def _update_axis_labels(self):
        """Update plot axis labels based on tomography mode"""
        label = 'Angle (°)' if self.tomography_enabled else 'Time (s)'
        for key, plot_info in self.plots.items():
            plot_info['widget'].setLabel('bottom', label, color='#d4d4d4', size='9pt')
    
    def _frame_to_angle(self, frame_idx: int) -> float:
        """Convert frame index to rotation angle, normalized to 0-360°"""
        if not self.tomography_enabled:
            return 0.0
        angle = self.angle_start + frame_idx * self.angular_spacing
        # Normalize to 0-360° range
        angle = angle % 360.0
        return angle
    
    def _update_tomography_controls(self):
        """Enable/disable tomography controls based on checkbox"""
        enabled = self.chk_tomography.isChecked()
        self.angle_start_spin.setEnabled(enabled)
        self.angle_end_spin.setEnabled(enabled)
        self.angular_spacing_spin.setEnabled(enabled)
        
        if enabled:
            self._calculate_total_projections()
    
    def _on_tomography_toggled(self, state):
        """Handle tomography mode toggle"""
        self.tomography_enabled = (state == QtCore.Qt.Checked)
        self._update_tomography_controls()
        
        if self.tomography_enabled:
            self._log("Tomography mode enabled")
        else:
            self._log("Tomography mode disabled")
    
    def _on_angle_params_changed(self):
        """Handle angle parameter changes"""
        self.angle_start = self.angle_start_spin.value()
        self.angle_end = self.angle_end_spin.value()
        self.angular_spacing = self.angular_spacing_spin.value()
        self._calculate_total_projections()
    
    def _calculate_total_projections(self):
        """Calculate and display total number of projections"""
        if self.angular_spacing > 0:
            angle_range = abs(self.angle_end - self.angle_start)
            total = int(angle_range / self.angular_spacing)
            self.lbl_total_projections.setText(f"Total: {total} projections")
        else:
            self.lbl_total_projections.setText("Total: — projections")
    
    def closeEvent(self, event):
        """Handle close event"""
        if self._running:
            reply = QtWidgets.QMessageBox.question(
                self, "Monitoring Active",
                "Monitoring is active. Stop and close?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.No:
                event.ignore()
                return
            
            self._stop_monitoring()
        
        event.accept()


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    dialog = ImageInfoDialog()
    dialog.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()