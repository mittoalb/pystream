"""
Live Plot Viewer

Shows real-time plot of image statistics updated with each frame.
Window opens automatically when you execute this script.
"""

import numpy as np
from PyQt5 import QtWidgets
import pyqtgraph as pg
from scipy.ndimage import sobel, gaussian_filter

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
    'snr': [],
    'cnr': [],
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
      
        self.line_snr = self.plot_widget.plot([], [], pen=pg.mkPen('c', width=1), name='Min')
        self.line_cnr = self.plot_widget.plot([], [], pen=pg.mkPen('y', width=1), name='Min')

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
      
        self.line_snr.setData([], [])
        self.line_cnr.setData([], [])
        

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

        self.line_snr.setData(x, _data['std'])
        self.line_cnr.setData(x, _data['std'])

         # end class






#-------------------------------------------------
# SNR reale
#-------------------------------------------------

def snr_real(img, patch_size=32):
 
    H, W = img.shape
    patches = []
# estrae patch in modo  sequenziale su tutta l'immagine e valuta srn localmente
    for y in range(0, H - patch_size, patch_size):
        for x in range(0, W - patch_size, patch_size):
            patches.append(img[y:y+patch_size, x:x+patch_size])

    patches = np.array(patches)
    if len(patches) == 0:      # controlla se non ci sono patch
        return 0.0

    ''' Noise: valuta varianza per ogni patch e prende il 20% più basso  
    var bass - quasi solo rumore
    var alta - dettagli

  '''
    variances = np.var(patches.reshape(len(patches), -1), axis=1)
    noise_thresh = np.percentile(variances, 20)           # percentile = valore che divide la distribuzione
    noise_patches = patches[variances <= noise_thresh]    # seleziono immagini a bassa var 

    if len(noise_patches) == 0:         # vedo se esistono patch di noise , altrimenti 0 
        return 0.0

    noise_std = np.std(noise_patches)

    # gradiente: gx gy e bordi 
  ''' uno mi calcola il gradiente orizzontale l'altro verticale 
  se ci sono bordi verticali, dendriti, cellule-> gx è alto
  se la patch è uniforme -> gx circa 0
  la somma dei quadrati  mi fornisce la media sel segnale

  Analysis of focus measure operators in shape‑from‑focus (Said Pertuz, Puig, García, Pattern Recognition, 2013)
  '''
    grad_energies = []
    for p in patches:
        gx = sobel(p, axis=1)
        gy = sobel(p, axis=0)
        grad_energies.append(np.mean(gx**2 + gy**2))  #energia del bordo e media , per valori alti segnale biologixo      

    grad_energies = np.array(grad_energies)
    signal_thresh = np.percentile(grad_energies, 70)      # valuto percentile, al di sopra del range sono più segnale
    signal_patches = patches[grad_energies >= signal_thresh]  # considera solo quelle al di sorpa della soglia 

    if len(signal_patches) == 0:         # controllo per immagine vuota
        return 0.0

    signal_mean = np.mean(signal_patches)   # livello medio del segnale : la media di intensità nelle patch ad alta struttura

    if noise_std == 0:
        return 0.0

    snr = signal_mean / noise_std                # formula reale
    return float(20 * np.log10(snr + 1e-9))      # conversione in bd

        # process
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

    img_snr = float(np.std(img))
    img_cnr = float(np.std(img))

    # Append to buffers
    _data['mean'].append(img_mean)
    _data['max'].append(img_max)
    _data['min'].append(img_min)
    _data['std'].append(img_std)
  
    _data['snr'].append(img_std)
    _data['scnr'].append(img_std)

    

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
_data = {'mean': [], 'max': [], 'min': [], 'std': [], 'snr': [], 'cnr': []}
_plot_win = PlotWindow()
_plot_win.show()
_plot_win.raise_()
print("Plot window opened. Showing mean/max/min/std/snr/cnr vs frame number.")

