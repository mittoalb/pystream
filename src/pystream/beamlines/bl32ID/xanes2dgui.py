"""
XANES 2D GUI Launcher for bl32ID.

Launches the 2D XANES / ZP focus-calibration GUI (gui_2d.py) living in the
xanes_gui package, same way XANESGuiDialog launches the 1D GUI.
"""

import os
import subprocess
import sys
from PyQt5 import QtWidgets


class XANES2DGuiDialog(QtWidgets.QDialog):
    """Launcher for the XANES 2D GUI — no dialog shown."""

    BUTTON_TEXT = "XANES 2D"
    HANDLER_TYPE = 'launcher'

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self._launch()
        self.reject()

    def _launch(self):
        possible_paths = [
            "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui/gui_2d.py",
            "/home/beams0/AMITTONE/Software/xanes_gui/xanes_gui/gui_2d.py",
            os.path.expanduser("~/Software/xanes_gui/xanes_gui/gui_2d.py"),
        ]

        script_path = next((p for p in possible_paths if os.path.exists(p)), None)
        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                "XANES 2D GUI script not found.\n\nTried:\n"
                + "\n".join(f"  - {p}" for p in possible_paths)
                + "\n\nExpected: xanes_gui/xanes_gui/gui_2d.py"
            )
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True,
            )
            if self.logger:
                self.logger.info(f"Launched XANES 2D GUI from {script_path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch XANES 2D GUI:\n{e}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
