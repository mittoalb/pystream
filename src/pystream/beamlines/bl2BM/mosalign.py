"""
Mosalign Launcher for bl2BM

Launches the standalone Mosalign tool when clicked.
"""

import subprocess
import os
import sys
from PyQt5 import QtWidgets


class MotorScanDialog(QtWidgets.QDialog):
    """Launcher for Mosalign - no dialog shown."""

    BUTTON_TEXT = "Mosalign"
    HANDLER_TYPE = 'launcher'

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self._launch()
        self.reject()

    def _launch(self):
        possible_paths = [
            "/home/beams/AMITTONE/Software/mosalign/mosalign/gui.py",
            "/home/beams0/AMITTONE/Software/mosalign/mosalign/gui.py",
            os.path.expanduser("~/Software/mosalign/mosalign/gui.py"),
        ]

        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break

        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                "Mosalign script not found.\n\nTried:\n" +
                "\n".join(f"  - {p}" for p in possible_paths))
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True)
            if self.logger:
                self.logger.info(f"Launched Mosalign from {script_path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch Mosalign:\n{e}")
