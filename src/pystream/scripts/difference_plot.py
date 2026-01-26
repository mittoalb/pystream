"""
Live Difference Plot

Shows real-time plot of difference statistics between current frame and reference.
Window opens automatically when you execute this script.
"""

import numpy as np
from PyQt5 import QtWidgets
import pyqtgraph as pg

# Reference frame
_ref_frame = None

# Plot window
_plot_win = None

# Data buffers
_max_points = 500
_frame_count = 0
_data = {
    'mean': [],
    'max': [],
    'std': [],
}

# Minimum size to consider a real frame (not test image)
_MIN_FRAME_SIZE = 100


class DiffPlotWindow(QtWidgets.QWidget):
    """Real-time difference plot window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Difference Plot")
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

        self.btn_reset = QtWidgets.QPushButton("Reset Ref")
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_reset.setToolTip("Capture new reference frame")
        btn_layout.addWidget(self.btn_reset)

        self.btn_clear = QtWidgets.QPushButton("Clear Plot")
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_clear.setToolTip("Clear plot data")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()

        self.lbl_stats = QtWidgets.QLabel("Waiting for reference frame...")
        btn_layout.addWidget(self.lbl_stats)

        layout.addLayout(btn_layout)

        # Plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', 'Difference Value')
        self.plot_widget.setLabel('bottom', 'Frame')
        self.plot_widget.setTitle('Difference from Reference Frame')
        self.plot_widget.addLegend()

        # Create plot lines
        self.line_mean = self.plot_widget.plot([], [], pen=pg.mkPen('b', width=2), name='Mean Diff')
        self.line_max = self.plot_widget.plot([], [], pen=pg.mkPen('r', width=1), name='Max Diff')
        self.line_std = self.plot_widget.plot([], [], pen=pg.mkPen('g', width=1, style=2), name='Std Diff')

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

    def _on_reset(self):
        global _ref_frame
        _ref_frame = None
        self.lbl_stats.setText("Reference reset. Next frame will be new reference...")

    def _on_clear(self):
        global _frame_count, _data
        _frame_count = 0
        _data = {'mean': [], 'max': [], 'std': []}
        self.line_mean.setData([], [])
        self.line_max.setData([], [])
        self.line_std.setData([], [])
        self.lbl_stats.setText("Plot cleared.")

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
        self.line_std.setData(x, _data['std'])
        self.lbl_stats.setText(stats_text)


def process(img):
    """Process each frame."""
    global _ref_frame, _frame_count, _data, _plot_win

    # Skip tiny test images from console
    if img.shape[0] < _MIN_FRAME_SIZE or img.shape[1] < _MIN_FRAME_SIZE:
        return img

    # Skip if window not running
    if _plot_win is None or not _plot_win.running or _plot_win.paused:
        return img

    # Capture first real frame as reference
    if _ref_frame is None:
        _ref_frame = img.copy()
        if _plot_win is not None:
            _plot_win.lbl_stats.setText(f"Reference captured ({img.shape[1]}x{img.shape[0]}). Plotting difference...")
        return img

    # Compute difference
    diff = np.abs(img.astype(np.float32) - _ref_frame.astype(np.float32))

    # Compute statistics
    diff_mean = float(np.mean(diff))
    diff_max = float(np.max(diff))
    diff_std = float(np.std(diff))

    # Append to buffers
    _data['mean'].append(diff_mean)
    _data['max'].append(diff_max)
    _data['std'].append(diff_std)

    # Trim to max points
    if len(_data['mean']) > _max_points:
        for key in _data:
            _data[key] = _data[key][-_max_points:]

    _frame_count += 1

    # Update plot
    stats = f"Frame {_frame_count}: Mean={diff_mean:.1f} Max={diff_max:.1f} Std={diff_std:.1f}"
    _plot_win.update_plot(stats)

    return img


# Reset state and open window when script is executed
_ref_frame = None
_frame_count = 0
_data = {'mean': [], 'max': [], 'std': []}
_plot_win = DiffPlotWindow()
_plot_win.show()
_plot_win.raise_()
print("Difference plot window opened. First frame will be reference.")
