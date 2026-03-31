"""
Optics Calculator Launcher for bl32ID

Launches the TXM Optics Calculator and allows setting the effective
pixel size PV (32id:TXMOptics:ImagePixelSize).
"""

import subprocess
import os
import sys
import logging
from typing import Optional
from PyQt5 import QtWidgets


SCRIPT_PATH = "/home/beams/USERTXM/Software/txm_calc/optics_calc.py"
PIXEL_SIZE_PV = "32id:TXMOptics:ImagePixelSize"


class OpticsCalcDialog(QtWidgets.QDialog):
    """Launcher for Optics Calculator + effective pixel size PV setter."""

    BUTTON_TEXT = "TXM Optics"
    HANDLER_TYPE = 'singleton'

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("TXM Optics - bl32ID")
        self.resize(400, 200)
        self._init_ui()
        self._read_pv()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Launch calculator
        launch_btn = QtWidgets.QPushButton("Open TXM Optics Calculator")
        launch_btn.clicked.connect(self._launch)
        layout.addWidget(launch_btn)

        # Effective pixel size
        pv_group = QtWidgets.QGroupBox("Effective Pixel Size")
        fl = QtWidgets.QFormLayout()

        self.pixel_spin = QtWidgets.QDoubleSpinBox()
        self.pixel_spin.setRange(0.001, 10000)
        self.pixel_spin.setDecimals(3)
        self.pixel_spin.setSuffix(" nm")
        self.pixel_spin.setValue(766.0)
        fl.addRow("Pixel size:", self.pixel_spin)

        self.pv_label = QtWidgets.QLabel(PIXEL_SIZE_PV)
        self.pv_label.setStyleSheet("color: gray;")
        fl.addRow("PV:", self.pv_label)

        btn_row = QtWidgets.QHBoxLayout()
        set_btn = QtWidgets.QPushButton("Set PV")
        set_btn.clicked.connect(self._set_pv)
        btn_row.addWidget(set_btn)

        read_btn = QtWidgets.QPushButton("Read PV")
        read_btn.clicked.connect(self._read_pv)
        btn_row.addWidget(read_btn)

        fl.addRow(btn_row)

        self.status_label = QtWidgets.QLabel("")
        fl.addRow(self.status_label)

        pv_group.setLayout(fl)
        layout.addWidget(pv_group)

        layout.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _launch(self):
        """Launch the Optics Calculator script."""
        possible_paths = [
            "/home/beams/USERTXM/Software/txm_calc/optics_calc.py",
            "/home/beams0/USERTXM/Software/txm_calc/optics_calc.py",
            os.path.expanduser("~/Software/txm_calc/optics_calc.py"),
        ]

        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break

        if not script_path:
            QtWidgets.QMessageBox.critical(
                self, "File Not Found",
                "Optics Calculator script not found.\n\nTried:\n" +
                "\n".join(f"  - {p}" for p in possible_paths))
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True)
            self.status_label.setText("Calculator launched")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Launch Failed", f"Failed to launch:\n{e}")

    def _set_pv(self):
        val = self.pixel_spin.value()
        try:
            r = subprocess.run(
                ['caput', '-c', PIXEL_SIZE_PV, str(val)],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                self.status_label.setText(f"Set {PIXEL_SIZE_PV} = {val} nm")
                self.status_label.setStyleSheet("color: green;")
            else:
                self.status_label.setText(f"Failed: {r.stderr.strip()}")
                self.status_label.setStyleSheet("color: red;")
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            self.status_label.setStyleSheet("color: red;")

    def _read_pv(self):
        try:
            r = subprocess.run(
                ['caget', '-t', PIXEL_SIZE_PV],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                val = float(r.stdout.strip())
                self.pixel_spin.setValue(val)
                self.status_label.setText(f"Current: {val} nm")
                self.status_label.setStyleSheet("color: gray;")
        except Exception:
            pass
