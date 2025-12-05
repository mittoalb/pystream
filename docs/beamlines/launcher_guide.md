# Quick Guide: Adding Standalone GUI Launchers

This guide shows you how to add simple launcher buttons for your standalone Python GUI scripts to PyStream's beamline toolbars.

## Quick Start (3 Steps)

### 1. Create Launcher File

Copy the template and customize it:

```bash
cd src/pystream/beamlines/bl32ID
cp launcher_template.py mygui.py
```

Edit `mygui.py` and update these 3 configuration variables at the top:

```python
# Path to your standalone GUI script
SCRIPT_PATH = "/home/beams/AMITTONE/Software/mygui/mygui.py"

# Dialog title
DIALOG_TITLE = "My GUI"

# Description
DIALOG_DESCRIPTION = """Launch My Custom GUI.

Brief description of what your GUI does.
"""
```

Change the class name from `LauncherDialog` to something unique (e.g., `MyGuiDialog`):

```python
class MyGuiDialog(QtWidgets.QDialog):
    """Simple launcher dialog for My GUI."""
```

### 2. Add to __init__.py

Edit `__init__.py` in your beamline directory and add your launcher:

```python
from .mosalign import MotorScanDialog
from .softbpm import SoftBPMDialog
from .detectorcontrol import DetectorControlDialog
from .mygui import MyGuiDialog  # Add this line

__all__ = ['MotorScanDialog', 'SoftBPMDialog', 'DetectorControlDialog', 'MyGuiDialog']
```

### 3. Restart PyStream

That's it! Your GUI will now appear as a button in the beamlines toolbar:
```
PyStream → Beamlines → bl32ID → My GUI
```

## What the Template Provides

The launcher template automatically handles:

- **Subprocess Management**: Launches your GUI as a separate process (no Qt/Tkinter conflicts)
- **Status Monitoring**: Shows running/stopped/exited status
- **Start/Stop Controls**: Simple buttons to launch and terminate
- **Clean Shutdown**: Properly terminates processes on close
- **Error Handling**: Shows helpful error messages
- **Logging Integration**: Logs events to PyStream logger

## Example: XANES GUI Launcher

Here's a minimal example for launching the XANES GUI:

**File: `xanesgui.py`**
```python
import subprocess
import logging
import os
from typing import Optional
from PyQt5 import QtWidgets, QtCore

SCRIPT_PATH = "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui.py"
DIALOG_TITLE = "XANES GUI"
DIALOG_DESCRIPTION = "Launch XANES Control GUI for energy calibration."

class XANESGuiDialog(QtWidgets.QDialog):
    # ... (copy the rest from launcher_template.py)
```

## Multiple GUI Launchers

You can add as many launchers as needed:

```
bl32ID/
├── mosalign.py          # Built-in PyQt tool
├── softbpm.py           # Built-in PyQt tool
├── detectorcontrol.py   # Built-in PyQt tool
├── xanesgui.py          # Launcher for XANES GUI
├── alignment_gui.py     # Launcher for Alignment GUI
├── energy_gui.py        # Launcher for Energy GUI
├── launcher_template.py # Template for creating new launchers
└── __init__.py          # Export all dialogs
```

In `__init__.py`:
```python
from .mosalign import MotorScanDialog
from .softbpm import SoftBPMDialog
from .detectorcontrol import DetectorControlDialog
from .xanesgui import XANESGuiDialog
from .alignment_gui import AlignmentGuiDialog
from .energy_gui import EnergyGuiDialog

__all__ = [
    'MotorScanDialog',
    'SoftBPMDialog',
    'DetectorControlDialog',
    'XANESGuiDialog',
    'AlignmentGuiDialog',
    'EnergyGuiDialog'
]
```

## Advanced: Auto-Detect Script Path

To try multiple possible script locations:

```python
def _launch(self):
    # Try multiple possible locations
    possible_paths = [
        "/home/beams/AMITTONE/Software/mygui/mygui.py",
        "/home/beams0/AMITTONE/Software/mygui/mygui.py",
        os.path.expanduser("~/Software/mygui/mygui.py"),
    ]

    script_path = None
    for path in possible_paths:
        if os.path.exists(path):
            script_path = path
            break

    if not script_path:
        QtWidgets.QMessageBox.critical(
            self, "File Not Found",
            "Could not find GUI script.\n\nTried:\n" +
            "\n".join(f"  - {p}" for p in possible_paths)
        )
        return

    # Continue with launch...
```

## Troubleshooting

**GUI doesn't appear in toolbar:**
- Check that you added the dialog class to `__init__.py`
- Verify the class name is in the `__all__` list
- Restart PyStream completely
- Check PyStream log for import errors

**"File Not Found" error:**
- Verify `SCRIPT_PATH` is correct and absolute (not relative)
- Test the path: `ls -la /path/to/your/script.py`
- Make sure the file is executable or Python can read it

**GUI crashes immediately on launch:**
- Test your GUI runs standalone: `python3 /path/to/script.py`
- Check all dependencies are installed
- Look for errors in PyStream log (stderr is captured)

**Want to run multiple instances:**
- The template prevents multiple instances by default
- To allow multiple instances, remove the running check in `_launch()`
- Each different launcher can run simultaneously (they're independent)

## Template Location

The launcher template is located at:
```
src/pystream/beamlines/bl32ID/launcher_template.py
```

Copy and customize it for each new GUI you want to add.
