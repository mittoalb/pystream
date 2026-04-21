"""
bl_gui Launcher for bl32ID.

Launches `bl_gui bl32id.json` as a subprocess in the current Python
environment. bl_gui resolves the layout file against its bundled
`layouts/` directory automatically.
"""

import os
import shutil
import subprocess
import sys
from PyQt5 import QtWidgets


class BLGuiDialog(QtWidgets.QDialog):
    """Launcher: spawns bl_gui bl32id.json and closes without showing a UI."""

    BUTTON_TEXT = "BL GUI"
    HANDLER_TYPE = 'launcher'

    LAYOUT_ARG = "bl32id.json"

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self._launch()
        self.reject()

    def _launch(self):
        bl_gui = shutil.which("bl_gui") or os.path.join(
            os.path.dirname(sys.executable), "bl_gui")
        if not os.path.isfile(bl_gui):
            QtWidgets.QMessageBox.critical(
                self.parent(), "bl_gui not found",
                f"Could not find `bl_gui` on PATH or in {os.path.dirname(sys.executable)}.\n"
                f"Install with: pip install -e <path to bl_gui repo>"
            )
            return
        try:
            subprocess.Popen(
                [bl_gui, self.LAYOUT_ARG],
                start_new_session=True,
            )
            if self.logger:
                self.logger.info(f"Launched {bl_gui} {self.LAYOUT_ARG}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch failed",
                f"Failed to launch bl_gui:\n{e}"
            )
            if self.logger:
                self.logger.error(f"bl_gui launch failed: {e}")
