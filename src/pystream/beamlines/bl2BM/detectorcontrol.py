"""
Detector Control Plugin for bl2BM

Controls detector binning and ROI by setting BinX/BinY and CropLeft/Right/Top/Bottom PVs.
"""

import subprocess
import logging
from typing import Optional
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore


class DetectorControlDialog(QtWidgets.QDialog):
    """Dialog for controlling detector binning and ROI."""

    BUTTON_TEXT = "Detector"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Detector Control - bl2BM")
        self.resize(500, 500)

        self.roi = None
        self.roi_enabled = False
        self._max_sizex = None
        self._max_sizey = None

        self._init_ui()
        self._load_current_values()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("Detector Control")
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(title)

        # PV Prefix
        prefix_group = QtWidgets.QGroupBox("PV Configuration")
        prefix_layout = QtWidgets.QFormLayout()
        self.pv_prefix_input = QtWidgets.QLineEdit("2bmbSP1:cam1")
        prefix_layout.addRow("Camera PV Prefix:", self.pv_prefix_input)
        prefix_group.setLayout(prefix_layout)
        layout.addWidget(prefix_group)

        # Binning
        binning_group = QtWidgets.QGroupBox("Binning Control")
        binning_layout = QtWidgets.QFormLayout()

        self.binx_spin = QtWidgets.QSpinBox()
        self.binx_spin.setRange(1, 16)
        self.binx_spin.setValue(1)
        binning_layout.addRow("BinX:", self.binx_spin)

        self.biny_spin = QtWidgets.QSpinBox()
        self.biny_spin.setRange(1, 16)
        self.biny_spin.setValue(1)
        binning_layout.addRow("BinY:", self.biny_spin)

        self.sizex_spin = QtWidgets.QSpinBox()
        self.sizex_spin.setRange(1, 8192)
        self.sizex_spin.setReadOnly(True)
        binning_layout.addRow("SizeX (computed):", self.sizex_spin)

        self.sizey_spin = QtWidgets.QSpinBox()
        self.sizey_spin.setRange(1, 8192)
        self.sizey_spin.setReadOnly(True)
        binning_layout.addRow("SizeY (computed):", self.sizey_spin)

        self.binx_spin.valueChanged.connect(self._refresh_computed_sizes)
        self.biny_spin.valueChanged.connect(self._refresh_computed_sizes)

        btn_layout = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton("Apply Binning")
        self.apply_btn.clicked.connect(self._apply_binning)
        btn_layout.addWidget(self.apply_btn)

        self.read_btn = QtWidgets.QPushButton("Read Current")
        self.read_btn.clicked.connect(self._read_binning)
        btn_layout.addWidget(self.read_btn)

        binning_layout.addRow(btn_layout)
        binning_group.setLayout(binning_layout)
        layout.addWidget(binning_group)

        # Log
        log_group = QtWidgets.QGroupBox("Activity Log")
        log_layout = QtWidgets.QVBoxLayout()
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Close
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _log_message(self, msg):
        import time
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _get_pv_value(self, pv):
        try:
            r = subprocess.run(['caget', '-t', pv],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception as e:
            self._log_message(f"caget {pv}: {e}")
        return None

    def _set_pv_value(self, pv, val):
        try:
            r = subprocess.run(['caput', '-c', pv, str(val)],
                               capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except Exception as e:
            self._log_message(f"caput {pv}: {e}")
            return False

    def _load_current_values(self):
        self._read_binning()

    def _read_binning(self):
        prefix = self.pv_prefix_input.text()
        binx = self._get_pv_value(f"{prefix}:BinX")
        biny = self._get_pv_value(f"{prefix}:BinY")
        max_x = self._get_pv_value(f"{prefix}:MaxSizeX_RBV")
        max_y = self._get_pv_value(f"{prefix}:MaxSizeY_RBV")

        if binx:
            self.binx_spin.setValue(int(binx))
        if biny:
            self.biny_spin.setValue(int(biny))
        if max_x:
            self._max_sizex = int(max_x)
        if max_y:
            self._max_sizey = int(max_y)

        self._refresh_computed_sizes()
        self._log_message(f"Read: BinX={binx}, BinY={biny}, MaxX={max_x}, MaxY={max_y}")

    def _refresh_computed_sizes(self):
        if self._max_sizex is None or self._max_sizey is None:
            return
        self.sizex_spin.setValue(self._max_sizex // self.binx_spin.value())
        self.sizey_spin.setValue(self._max_sizey // self.biny_spin.value())

    def _apply_binning(self):
        prefix = self.pv_prefix_input.text()
        binx = self.binx_spin.value()
        biny = self.biny_spin.value()

        if self._max_sizex is None or self._max_sizey is None:
            QtWidgets.QMessageBox.warning(self, "Error",
                "Max sensor size unknown. Click 'Read Current' first.")
            return

        sizex = self._max_sizex // binx
        sizey = self._max_sizey // biny

        ok = True
        for pv, val in [(f"{prefix}:BinX", binx), (f"{prefix}:BinY", biny),
                        (f"{prefix}:SizeX", sizex), (f"{prefix}:SizeY", sizey)]:
            if not self._set_pv_value(pv, val):
                ok = False

        if ok:
            self.sizex_spin.setValue(sizex)
            self.sizey_spin.setValue(sizey)
            self._log_message(f"Applied: BinX={binx}, BinY={biny}, SizeX={sizex}, SizeY={sizey}")
        else:
            QtWidgets.QMessageBox.warning(self, "Error", "Failed to apply. Check log.")
