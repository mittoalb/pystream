"""
Simple Launcher Template for Standalone Python GUI Scripts

This template provides a launcher that runs an external Python script
when clicked. No dialog is shown - just click and run.

Usage:
1. Copy this file and rename it (e.g., mygui.py)
2. Update SCRIPT_PATH to point to your Python script
3. Update the class name (e.g., MyGuiDialog)
4. Add to __init__.py: from .mygui import MyGuiDialog
5. Add 'MyGuiDialog' to __all__ list
"""

import subprocess
import os
import sys
from PyQt5 import QtWidgets


# ============================================================================
# CONFIGURATION - UPDATE THESE VALUES
# ============================================================================

# Path to your Python script
SCRIPT_PATH = "/home/beams/AMITTONE/Software/your_gui/your_gui.py"

# Button text that appears in PyStream toolbar
BUTTON_TEXT = "Your GUI"


# ============================================================================
# LAUNCHER DIALOG
# ============================================================================

class LauncherDialog(QtWidgets.QDialog):
    """Simple launcher - no dialog shown, just runs the script."""

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger

        # Launch immediately without showing dialog
        self._launch()

        # Reject immediately (don't show dialog)
        self.reject()

    def _launch(self):
        """Launch the Python script."""
        # Try multiple possible locations
        possible_paths = [
            SCRIPT_PATH,
            SCRIPT_PATH.replace("/home/beams/", "/home/beams0/"),
            os.path.expanduser(f"~/Software/{os.path.basename(os.path.dirname(SCRIPT_PATH))}/{os.path.basename(SCRIPT_PATH)}"),
        ]

        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break

        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                f"Script not found.\n\nTried:\n" + "\n".join(f"  - {p}" for p in possible_paths)
            )
            return

        try:
            # Launch the script as a background process using the same Python interpreter
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=os.path.dirname(script_path),
                start_new_session=True  # Detach from parent
            )

            if self.logger:
                self.logger.info(f"Launched {BUTTON_TEXT} from {script_path}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch {BUTTON_TEXT}:\n{str(e)}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
