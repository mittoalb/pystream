"""
XANES GUI Launcher for bl32ID

Launches the standalone XANES Control GUI when clicked.
"""

import subprocess
import os
import sys
from PyQt5 import QtWidgets


SCRIPT_PATH = "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui/gui.py"


class XANESGuiDialog(QtWidgets.QDialog):
    """Launcher for XANES GUI - no dialog shown."""

    BUTTON_TEXT = "XANES GUI"
    HANDLER_TYPE = 'launcher'  # Execute immediately and close

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger

        # Launch immediately without showing dialog
        self._launch()

        # Reject immediately (don't show dialog)
        self.reject()

    def _launch(self):
        """Launch the XANES GUI script."""
        # Try multiple possible locations
        possible_paths = [
            "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui/gui.py",
            "/home/beams0/AMITTONE/Software/xanes_gui/xanes_gui/gui.py",
            os.path.expanduser("~/Software/xanes_gui/xanes_gui/gui.py"),
        ]

        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break

        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                "XANES GUI script not found.\n\nTried:\n" +
                "\n".join(f"  - {p}" for p in possible_paths) +
                "\n\nPlease install:\n" +
                "  cd ~/Software\n" +
                "  git clone <xanes-gui-repo>\n"
            )
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True
            )

            if self.logger:
                self.logger.info(f"Launched XANES GUI from {script_path}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch XANES GUI:\n{str(e)}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
