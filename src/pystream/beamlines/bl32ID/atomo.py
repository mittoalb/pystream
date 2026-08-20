"""
atomo Launcher for bl32ID.

Launches the standalone `atomo` adaptive-exposure tomography GUI
(~/Software/atomo/atomo/gui.py) in its OWN conda env (`atomo`) so
its heavy CUDA / torch deps don't need to be in pystream's env.
Same subprocess-launch pattern as XANESGuiDialog / etc., but goes
through `pystream.launcher_utils.spawn_python_in_env`.
"""

import os
from PyQt5 import QtWidgets

from ...launcher_utils import spawn_python_in_env


class AtomoLauncherDialog(QtWidgets.QDialog):
    """Launcher for the standalone atomo GUI — no dialog shown."""

    BUTTON_TEXT = "aTomo"
    GROUP       = "Scans"
    HANDLER_TYPE = 'launcher'
    # Conda env atomo's GUI runs in. Change if your install differs.
    # None → uses pystream's env (legacy fallback).
    CONDA_ENV   = "atomo"

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self._launch()
        self.reject()

    def _launch(self):
        possible_paths = [
            "/home/beams/AMITTONE/Software/atomo/atomo/gui.py",
            "/home/beams0/AMITTONE/Software/atomo/atomo/gui.py",
            os.path.expanduser("~/Software/atomo/atomo/gui.py"),
        ]

        script_path = next((p for p in possible_paths if os.path.exists(p)), None)
        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                "atomo GUI script not found.\n\nTried:\n"
                + "\n".join(f"  - {p}" for p in possible_paths)
                + "\n\nExpected: atomo/atomo/gui.py"
            )
            return

        try:
            spawn_python_in_env(
                env=self.CONDA_ENV,
                script_path=script_path,
                cwd=os.path.dirname(script_path),
                logger=self.logger,
            )
            if self.logger:
                self.logger.info(f"Launched atomo GUI from {script_path} "
                                 f"in conda env {self.CONDA_ENV!r}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch atomo GUI:\n{e}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
