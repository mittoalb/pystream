"""
Live Plot Viewer

Shows real-time plot of image statistics updated with each frame.
Window opens automatically when you execute this script.
"""

import numpy as np
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
}

# Minimum size to consider a real frame (not test image)
_MIN_FRAME_SIZE = 100


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

        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_clear.setToolTip("Clear all data")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()

        self.lbl_stats = QtWidgets.QLabel("Waiting for frames...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # Plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', 'Value')
        self.plot_widget.setLabel('bottom', 'Frame')
        self.plot_widget.addLegend()

        # Create plot lines
        self.line_mean = self.plot_widget.plot([], [], pen=pg.mkPen('b', width=2), name='Mean')
        self.line_max = self.plot_widget.plot([], [], pen=pg.mkPen('r', width=1), name='Max')
        self.line_min = self.plot_widget.plot([], [], pen=pg.mkPen('g', width=1), name='Min')
        self.line_std = self.plot_widget.plot([], [], pen=pg.mkPen('m', width=1, style=2), name='Std')

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
        _data = {'mean': [], 'max': [], 'min': [], 'std': []}
        self.line_mean.setData([], [])
        self.line_max.setData([], [])
        self.line_min.setData([], [])
        self.line_std.setData([], [])
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
        self.line_mean.setData(x, _data['mean'])
        self.line_max.setData(x, _data['max'])
        self.line_min.setData(x, _data['min'])
        self.line_std.setData(x, _data['std'])
        self.lbl_stats.setText(stats_text)


def process(img):
    """Process each frame."""
    global _frame_count, _data, _plot_win

    # Skip tiny test images from console
    if img.shape[0] < _MIN_FRAME_SIZE or img.shape[1] < _MIN_FRAME_SIZE:
        return img

    # Skip if window not running
    if _plot_win is None or not _plot_win.running or _plot_win.paused:
        return img

    # Compute statistics
    img_mean = float(np.mean(img))
    img_max = float(np.max(img))
    img_min = float(np.min(img))
    img_std = float(np.std(img))

    # Append to buffers
    _data['mean'].append(img_mean)
    _data['max'].append(img_max)
    _data['min'].append(img_min)
    _data['std'].append(img_std)

    # Trim to max points
    if len(_data['mean']) > _max_points:
        for key in _data:
            _data[key] = _data[key][-_max_points:]

    _frame_count += 1

    # Update plot
    stats = f"Frame {_frame_count}: Mean={img_mean:.1f} Max={img_max:.1f} Min={img_min:.1f} Std={img_std:.1f}"
    _plot_win.update_plot(stats)

    return img


# Reset state and open window when script is executed
_frame_count = 0
_data = {'mean': [], 'max': [], 'min': [], 'std': []}
_plot_win = PlotWindow()
_plot_win.show()
_plot_win.raise_()
print("Plot window opened. Showing mean/max/min/std vs frame number.")
