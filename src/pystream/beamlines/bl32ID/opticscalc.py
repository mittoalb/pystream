"""
Optics Calculator Launcher for bl32ID

Launches the TXM Optics Calculator when clicked.
"""

import subprocess
import os
import sys
from PyQt5 import QtWidgets


SCRIPT_PATH = "/home/beams/USERTXM/Software/txm_calc/optics_calc.py"


class OpticsCalcDialog(QtWidgets.QDialog):
    """Simple launcher for Optics Calculator - no dialog shown."""

    BUTTON_TEXT = "TXM Optics"
    HANDLER_TYPE = 'launcher'  # Execute immediately and close

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger

        # Launch immediately without showing dialog
        self._launch()

        # Reject immediately (don't show dialog)
        self.reject()

    def _launch(self):
        """Launch the Optics Calculator script."""
        # Try multiple possible locations
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
                self.parent(), "File Not Found",
                "Optics Calculator script not found.\n\nTried:\n" +
                "\n".join(f"  - {p}" for p in possible_paths) +
                "\n\nPlease install:\n" +
                "  cd ~/Software\n" +
                "  git clone <txm-calc-repo>\n"
            )
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True
            )

            if self.logger:
                self.logger.info(f"Launched TXM Optics Calculator from {script_path}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch TXM Optics Calculator:\n{str(e)}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
