#!/usr/bin/env python3
"""
Test script for mosalign plugin in offline mode

This script demonstrates how to test the mosalign functionality
without requiring real PVs or tomoscan installation.

Run from the project root:
    python test/test_mosalign.py

Or from the test directory:
    cd test && python test_mosalign.py
"""

import sys
import os

# Add parent directory to path so we can import pystream
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt5 import QtWidgets
from src.pystream.plugins.mosalign import MotorScanDialog

def main():
    """Run mosalign in test mode"""
    app = QtWidgets.QApplication(sys.argv)

    # Create the dialog
    dialog = MotorScanDialog()

    # Resize for smaller screens
    dialog.resize(400, 500)  # Smaller than default 1200x800

    # Auto-enable test mode
    dialog.test_mode_checkbox.setChecked(True)

    # Set some reasonable test parameters
    dialog.x_step_size.setValue(2)  # 2x2 grid for quick testing
    dialog.y_step_size.setValue(2)
    dialog.settle_time.setValue(0.5)  # Short settle time

    # Show instructions
    dialog._log("=" * 60)
    dialog._log("TEST MODE ENABLED - Offline Testing")
    dialog._log("=" * 60)
    dialog._log("")
    dialog._log("Instructions:")
    dialog._log("1. Test mode is already enabled (checkbox at top)")
    dialog._log("2. Click 'Start Scan' to run a mock scan")
    dialog._log("3. Watch the stitched preview build up with mock images")
    dialog._log("4. Enable 'Run tomoscan at each position' to test tomoscan logic")
    dialog._log("5. All motor movements and PV operations are mocked")
    dialog._log("")
    dialog._log("Parameters are pre-configured for quick testing:")
    dialog._log("- 2x2 grid (4 positions)")
    dialog._log("- 0.5s settle time")
    dialog._log("- Mock images will have position-dependent patterns")
    dialog._log("")
    dialog._log("Ready to test! Click 'Start Scan' when ready.")
    dialog._log("=" * 60)

    dialog.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
