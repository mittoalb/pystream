"""
Example Plugin Template

This is a minimal template for creating beamline plugins.
Copy and customize this file to create your own plugins.
"""

import logging
from typing import Optional
from PyQt5 import QtWidgets


class ExamplePluginDialog(QtWidgets.QDialog):
    """
    Example plugin dialog.

    This demonstrates the minimum required structure for a beamline plugin.
    """

    # BUTTON_TEXT defines the text shown on the toolbar button
    # If not specified, the class name is used (e.g., "Example Plugin")
    BUTTON_TEXT = "Example"

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        """
        Initialize the plugin.

        Args:
            parent: Parent widget (usually the main PyStream window)
            logger: Logger instance for logging messages
        """
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Example Plugin")
        self.resize(400, 300)

        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QtWidgets.QVBoxLayout(self)

        # Title
        title = QtWidgets.QLabel("Example Plugin")
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)

        # Description
        desc = QtWidgets.QLabel(
            "This is an example plugin template.\n"
            "Replace this with your own functionality."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Example button
        btn = QtWidgets.QPushButton("Click Me")
        btn.clicked.connect(self._on_button_click)
        layout.addWidget(btn)

        # Close button
        layout.addStretch()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _on_button_click(self):
        """Handle button click."""
        QtWidgets.QMessageBox.information(
            self,
            "Example",
            "Button clicked! Replace this with your functionality."
        )

        if self.logger:
            self.logger.info("Example plugin button clicked")
