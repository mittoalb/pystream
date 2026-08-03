"""
Autofocus Launcher for bl32ID.

Launches the standalone 3-motor autofocus GUI shipped with the
`autofocus` package (~/Software/autofocus/autofocus/gui.py). Same
subprocess-launch pattern as XANESGuiDialog / XANES2DGuiDialog.
"""

import os
import subprocess
import sys
from PyQt5 import QtWidgets


class AutofocusLauncherDialog(QtWidgets.QDialog):
    """Launcher for the standalone autofocus GUI — no dialog shown."""

    BUTTON_TEXT = "Autofocus"
    GROUP       = "Test"
    HANDLER_TYPE = 'launcher'

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self._launch()
        self.reject()

    def _launch(self):
        possible_paths = [
            "/home/beams/AMITTONE/Software/autofocus/autofocus/gui.py",
            "/home/beams0/AMITTONE/Software/autofocus/autofocus/gui.py",
            os.path.expanduser("~/Software/autofocus/autofocus/gui.py"),
        ]

        script_path = next((p for p in possible_paths if os.path.exists(p)), None)
        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                "Autofocus GUI script not found.\n\nTried:\n"
                + "\n".join(f"  - {p}" for p in possible_paths)
                + "\n\nExpected: autofocus/autofocus/gui.py"
            )
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True,
            )
            if self.logger:
                self.logger.info(f"Launched Autofocus GUI from {script_path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch Autofocus GUI:\n{e}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
