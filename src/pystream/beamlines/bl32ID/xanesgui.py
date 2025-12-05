"""
XANES GUI Launcher for bl32ID

Simple launcher for the standalone XANES Control GUI.
"""

import subprocess
import logging
import os
from typing import Optional
from PyQt5 import QtWidgets, QtCore


SCRIPT_PATH = "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui.py"
DIALOG_TITLE = "XANES GUI - bl32ID"
DIALOG_DESCRIPTION = """Launch XANES Control GUI.

Energy calibration and XANES scanning control for TXM optics.
"""


class XANESGuiDialog(QtWidgets.QDialog):
    """Launcher dialog for XANES GUI."""

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger if logger else logging.getLogger(__name__)
        self.setWindowTitle(DIALOG_TITLE)
        self.resize(400, 200)
        self.process = None
        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Description
        desc = QtWidgets.QLabel(DIALOG_DESCRIPTION)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Status
        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout()
        self.status_label = QtWidgets.QLabel("Status: Not running")
        self.status_label.setStyleSheet("font-weight: bold; color: gray;")
        status_layout.addWidget(self.status_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addStretch()

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.launch_button = QtWidgets.QPushButton("Launch XANES GUI")
        self.launch_button.clicked.connect(self._launch)
        button_layout.addWidget(self.launch_button)

        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        button_layout.addStretch()

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def _launch(self):
        """Launch the XANES GUI script."""
        if self.process is not None and self.process.poll() is None:
            QtWidgets.QMessageBox.warning(self, "Already Running", "XANES GUI is already running.")
            return

        # Try to find the script in common locations
        possible_paths = [
            "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui.py",
            "/home/beams0/AMITTONE/Software/xanes_gui/xanes_gui.py",
            os.path.expanduser("~/Software/xanes_gui/xanes_gui.py"),
        ]

        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break

        if not script_path:
            QtWidgets.QMessageBox.critical(
                self, "File Not Found",
                f"XANES GUI script not found in expected locations.\n\n"
                f"Tried:\n" + "\n".join(f"  - {p}" for p in possible_paths)
            )
            return

        try:
            self.process = subprocess.Popen(
                ["python3", script_path],
                cwd=os.path.dirname(script_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            self.status_label.setText("Status: Running")
            self.status_label.setStyleSheet("font-weight: bold; color: green;")
            self.launch_button.setEnabled(False)
            self.stop_button.setEnabled(True)

            if self.logger:
                self.logger.info(f"Launched XANES GUI from {script_path} (PID: {self.process.pid})")

            QtCore.QTimer.singleShot(1000, self._check_status)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Launch Failed", f"Failed to launch XANES GUI:\n{str(e)}")
            if self.logger:
                self.logger.error(f"Launch failed: {e}")

    def _stop(self):
        """Stop the XANES GUI process."""
        if self.process is None:
            return

        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

            self.status_label.setText("Status: Stopped")
            self.status_label.setStyleSheet("font-weight: bold; color: red;")
            self.launch_button.setEnabled(True)
            self.stop_button.setEnabled(False)

            if self.logger:
                self.logger.info("XANES GUI stopped")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error stopping XANES GUI: {e}")
        finally:
            self.process = None

    def _check_status(self):
        """Check if process is still running."""
        if self.process is not None:
            retcode = self.process.poll()
            if retcode is not None:
                self.status_label.setText(f"Status: Exited (code {retcode})")
                self.status_label.setStyleSheet("font-weight: bold; color: orange;")
                self.launch_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.process = None
                if self.logger:
                    self.logger.info(f"XANES GUI exited with code {retcode}")
            else:
                QtCore.QTimer.singleShot(2000, self._check_status)

    def closeEvent(self, event):
        """Handle dialog close."""
        if self.process is not None and self.process.poll() is None:
            reply = QtWidgets.QMessageBox.question(
                self, 'XANES GUI Running',
                'XANES GUI is still running. Stop it and close?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self._stop()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
