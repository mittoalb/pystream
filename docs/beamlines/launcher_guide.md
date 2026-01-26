# Quick Guide: Adding Standalone GUI Launchers

This guide shows you how to add simple launcher buttons for your standalone Python GUI scripts to PyStream's beamline toolbars.

## Overview

The launcher system allows PyStream users to optionally install and use external GUI tools for their beamline. These are **separate packages** that users can choose to install based on their needs. The launcher buttons appear in PyStream's beamline toolbar, but the actual GUI applications run as independent processes.

### Key Benefits

- **Optional Installation**: Users decide which external tools to install
- **No Dependency Conflicts**: External GUIs run as separate processes (Tkinter, PyQt, etc. won't interfere)
- **Easy Integration**: 3-step process to add launcher buttons
- **Simple Deployment**: External packages are installed independently from PyStream

## For PyStream Users: Installing External Tools

External GUI tools for your beamline are **optional packages** installed separately from PyStream.

### How It Works

1. **PyStream includes launcher buttons** for all available tools in the beamlines toolbar
2. **Buttons are always visible**, but external packages may not be installed
3. **When you click a button**:
   - If the package is installed → GUI launches immediately
   - If not installed → Error message shows installation instructions

### Installing Optional Tools

**You only install the tools you need.** Each tool is a separate package:

```bash
# Example: Install XANES GUI (optional)
cd ~/Software
git clone https://github.com/your-beamline/xanes_gui.git
cd xanes_gui
pip install -e .

# Example: Install Optics Calculator (optional)
cd ~/Software
git clone https://github.com/your-beamline/txm_calc.git
cd txm_calc
pip install -e .
```

### Workflow

1. **Launch PyStream** - All launcher buttons appear in toolbar
2. **Click a tool button** to try it
3. **If you see "File Not Found"** - The tool isn't installed yet
4. **Follow the installation instructions** in the error dialog
5. **Click the button again** - Tool launches

You decide which tools to install based on your needs. Unused tools can be ignored - they're just buttons in the toolbar.

## For Developers: Adding Launcher Buttons

### Quick Start (3 Steps)

### 1. Create Launcher File

Copy the template and customize it:

```bash
cd src/pystream/beamlines/bl32ID
cp _launcher_template.py mygui.py
```

Edit `mygui.py` and update these configuration variables at the top:

```python
# Path to your standalone GUI script (can specify multiple possible locations)
SCRIPT_PATH = "/home/beams/AMITTONE/Software/mygui/mygui.py"

# Dialog title
DIALOG_TITLE = "My GUI"

# Description
DIALOG_DESCRIPTION = """Launch My Custom GUI.

Brief description of what your GUI does.

Installation:
    git clone https://github.com/your-org/mygui.git ~/Software/mygui
    cd ~/Software/mygui
    pip install -e .
"""
```

**Important**: Add installation instructions in the description so users know how to install the optional package.

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

The launcher template is ultra-simple - it just runs your Python script when the button is clicked:

- **One-Click Launch**: Click the button → GUI opens immediately
- **Background Process**: Runs as independent process (detached from PyStream)
- **Auto-Detection**: Tries multiple possible installation locations
- **Error Messages**: Shows helpful messages if script not found
- **No Monitoring**: The GUI runs independently - no status tracking needed
- **Logging Integration**: Logs launch events to PyStream logger

## Example: XANES GUI Launcher

Here's the complete XANES GUI launcher - it's only ~70 lines:

**File: `xanesgui.py`**
```python
import subprocess
import os
import sys
from PyQt5 import QtWidgets

SCRIPT_PATH = "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui.py"
BUTTON_TEXT = "XANES GUI"

class XANESGuiDialog(QtWidgets.QDialog):
    """Simple launcher for XANES GUI - no dialog shown."""

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger

        # Launch immediately without showing dialog
        self._launch()

        # Reject immediately (don't show dialog)
        self.reject()

    def _launch(self):
        """Launch the XANES GUI script."""
        # Try multiple possible locations
        possible_paths = [
            "/home/beams/AMITTONE/Software/xanes_gui/xanes_gui.py",
            "/home/beams0/AMITTONE/Software/xanes_gui/xanes_gui.py",
            os.path.expanduser("~/Software/xanes_gui/xanes_gui.py"),
        ]

        script_path = None
        for path in possible_paths:
            if os.path.exists(path):
                script_path = path
                break

        if not script_path:
            QtWidgets.QMessageBox.critical(
                self.parent(), "File Not Found",
                "XANES GUI script not found.\n\nTried:\n" +
                "\n".join(f"  - {p}" for p in possible_paths) +
                "\n\nPlease install:\n" +
                "  cd ~/Software\n" +
                "  git clone <xanes-gui-repo>\n"
            )
            return

        try:
            subprocess.Popen(
                [sys.executable, script_path],  # Use same Python as PyStream
                cwd=os.path.dirname(script_path),
                start_new_session=True  # Detach from PyStream
            )

            if self.logger:
                self.logger.info(f"Launched XANES GUI from {script_path}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.parent(), "Launch Failed",
                f"Failed to launch XANES GUI:\n{str(e)}"
            )
            if self.logger:
                self.logger.error(f"Launch failed: {e}")
```

**Key features:**
- Click button → GUI opens immediately (no launcher dialog visible)
- Uses `sys.executable` to run with same conda environment as PyStream
- Auto-detects script location from multiple paths
- Shows installation instructions if not found

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

## Best Practice: Auto-Detect Script Path

Since external tools are optional and users may install them in different locations, it's recommended to auto-detect the script path from multiple possible locations:

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
            "\n".join(f"  - {p}" for p in possible_paths) +
            "\n\nPlease install the package:\n" +
            "  git clone https://github.com/your-org/mygui.git ~/Software/mygui\n" +
            "  cd ~/Software/mygui\n" +
            "  pip install -e ."
        )
        return

    # Continue with launch...
```

This approach:
- Checks multiple common installation locations
- Shows clear installation instructions if the package isn't found
- Allows users to install in their preferred location

## Making Launchers Truly Optional (For Developers)

By default, launcher buttons are **always visible** in the toolbar, even if the external package isn't installed. If you want to **hide launchers** for tools that aren't installed:

### Option 1: Keep Launchers Simple (Recommended)

- Launcher buttons are always visible
- Users see "File Not Found" error when clicking if not installed
- Error dialog shows installation instructions
- Simple and user-friendly

### Option 2: Hide Launchers When Not Installed

If you want buttons to only appear when the tool is installed, you can:

1. **Don't add the launcher to `__init__.py` by default**
2. **Provide installation script** that adds the launcher:

```bash
# In your tool's installation (e.g., xanes_gui/install.sh)
#!/bin/bash

# Install the tool
pip install -e .

# Add launcher to PyStream
LAUNCHER_PATH="/path/to/pystream/src/pystream/beamlines/bl32ID"
cp xanesgui_launcher.py "$LAUNCHER_PATH/xanesgui.py"

# Update __init__.py to include the launcher
# (Add logic to append import and __all__ entry)
```

This approach requires users to run an installation script, which adds complexity.

**Recommendation**: Keep it simple - include launchers in PyStream by default. Users can ignore buttons for tools they don't need.

## Deployment Workflow

### For Beamline Developers

1. **Develop the external GUI** in its own repository (e.g., `xanes_gui`)
2. **Create the launcher** in PyStream's beamline directory (e.g., `xanesgui.py`)
3. **Add to `__init__.py`** to export the launcher dialog
4. **Update PyStream's main code** to handle the new dialog type (add to `pystream.py`)
5. **Document the installation** in the launcher's description and README
6. **Decide**: Include launchers in PyStream (buttons always visible) or make them truly optional (requires installation script)

### For End Users

1. **Install PyStream** (includes launcher buttons)
2. **Optionally install external tools** as needed:
   ```bash
   cd ~/Software
   git clone <tool-repo-url>
   cd <tool-dir>
   pip install -e .
   ```
3. **Launch tools from PyStream** toolbar

### Benefits of This Approach

- **Modularity**: External tools are independent packages
- **Optional Dependencies**: Users install only what they need
- **Version Control**: Each tool has its own repository and versioning
- **No Bloat**: PyStream stays lightweight with minimal dependencies
- **Easy Updates**: Tools can be updated independently from PyStream

## Troubleshooting

**GUI doesn't appear in toolbar:**
- Check that you added the dialog class to `__init__.py`
- Verify the class name is in the `__all__` list
- Verify you added the dialog handler to `pystream.py` (see existing examples like `_open_xanes_gui`)
- Restart PyStream completely
- Check PyStream log for import errors

**"File Not Found" error:**
- The external package is not installed - follow installation instructions
- Verify path auto-detection includes the correct locations
- Test the path: `ls -la /path/to/your/script.py`
- Use the auto-detect pattern to support multiple installation locations

**GUI crashes immediately on launch:**
- Test your GUI runs standalone: `python3 /path/to/script.py`
- Check all dependencies for the external tool are installed
- Look for errors in PyStream log (stderr is captured)
- Verify the external tool's installation was successful

**Want to run multiple instances:**
- The template prevents multiple instances by default
- To allow multiple instances, remove the running check in `_launch()`
- Each different launcher can run simultaneously (they're independent)

## Adding PyStream Handler for New Dialog Types

When you create a new launcher dialog class, you must also update PyStream's main code to recognize it:

### Step 1: Add Dialog Check

In `src/pystream/pystream.py`, find the `_create_beamlines_bar()` method and add your dialog check:

```python
# Around line 605
elif hasattr(module, 'YourDialogName'):
    btn.clicked.connect(lambda _, m=module: self._open_your_tool(m))
```

### Step 2: Create Handler Method

Add a handler method in the same file:

```python
# Around line 1660
def _open_your_tool(self, module):
    """Launch Your Tool (runs immediately, no dialog)"""
    # Create launcher - it executes immediately and closes itself
    module.YourDialogName(parent=self, logger=LOGGER)
```

**Example**: See existing implementations like `_open_xanes_gui()` or `_open_optics_calc()` in `pystream.py`.

**Note**: The handler simply creates the dialog - it doesn't call `.show()` because the launcher executes immediately and calls `.reject()` to stay invisible.

## Template Location

The launcher template is located at:
```
src/pystream/beamlines/bl32ID/_launcher_template.py
```

Copy and customize it for each new GUI you want to add.
