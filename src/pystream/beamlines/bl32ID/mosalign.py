#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mosalign Launcher for bl32ID

Launches the standalone Mosalign tool when clicked.
"""

import subprocess
from PyQt5 import QtWidgets


class MotorScanDialog(QtWidgets.QDialog):
    """Launcher for Mosalign - no dialog shown."""

    BUTTON_TEXT = "Mosalign"
    HANDLER_TYPE = 'launcher'  # Execute immediately and close

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger

        # Launch immediately without showing dialog
        self._launch()

        # Reject immediately (don't show dialog)
        self.reject()

    def _launch(self):
        """Launch the Mosalign standalone application."""
        try:
            # Launch mosalign command
            subprocess.Popen(
                ['mosalign'],
                start_new_session=True
            )

            if self.logger:
                self.logger.info("Launched Mosalign standalone application")

        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Command Not Found",
                "Mosalign command not found.\n\n"
                "Please install mosalign:\n\n"
                "  cd /home/beams0/AMITTONE/Software/mosalign\n"
                "  pip install -e .\n"
            )
            if self.logger:
                self.logger.error("mosalign command not found")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch Mosalign:\n{str(e)}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
