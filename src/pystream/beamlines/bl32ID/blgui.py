"""
bl_gui Launcher for bl32ID.

Launches `bl_gui bl32id.json` in its target conda env (defaults to
pystream's env; override via `BLGuiDialog.CONDA_ENV = "..."` if your
install has bl_gui in a dedicated env). bl_gui resolves the layout
file against its bundled `layouts/` directory automatically.
"""

import os
import shutil
import sys
from PyQt5 import QtWidgets

from ...launcher_utils import spawn_command_in_env


class BLGuiDialog(QtWidgets.QDialog):
    """Launcher: spawns bl_gui bl32id.json and closes without showing a UI."""

    BUTTON_TEXT = "BL GUI"
    GROUP       = "Tools"
    HANDLER_TYPE = 'launcher'

    LAYOUT_ARG = "bl32id.json"
    # Set to the conda env that has `bl_gui` installed. `None` = the
    # env pystream itself is running in (legacy behaviour).
    CONDA_ENV  = None

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self._launch()
        self.reject()

    def _launch(self):
        # If CONDA_ENV is None, resolve the binary against sys.executable
        # (pystream's env). If CONDA_ENV is set, `conda run -n <env>`
        # will resolve it on the env's PATH.
        if self.CONDA_ENV:
            cmd = f"bl_gui {self.LAYOUT_ARG}"
        else:
            bl_gui = shutil.which("bl_gui") or os.path.join(
                os.path.dirname(sys.executable), "bl_gui")
            if not os.path.isfile(bl_gui):
                QtWidgets.QMessageBox.critical(
                    self.parent(), "bl_gui not found",
                    f"Could not find `bl_gui` on PATH or in "
                    f"{os.path.dirname(sys.executable)}.\n"
                    f"Install with: pip install -e <path to bl_gui repo>\n"
                    f"OR set BLGuiDialog.CONDA_ENV to an env that has it."
                )
                return
            cmd = f"{bl_gui} {self.LAYOUT_ARG}"
        try:
            spawn_command_in_env(
                env=self.CONDA_ENV,
                command=cmd,
                logger=self.logger,
            )
            if self.logger:
                self.logger.info(f"Launched: {cmd} "
                                 f"(env={self.CONDA_ENV or 'host'})")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch failed",
                f"Failed to launch bl_gui:\n{e}"
            )
            if self.logger:
                self.logger.error(f"bl_gui launch failed: {e}")
