# Beamline Configuration

PyStream supports configurable beamline plugins, allowing users to personalize their installation without modifying PyStream's core code.

## Overview

The beamline configuration system allows you to:
- Load only the beamline plugins relevant to your facility
- Disable all beamline plugins if not needed
- Easily switch between different beamlines
- Create custom beamline plugins

## Quick Start

Edit `src/pystream/beamline_config.py` to configure which beamline to load:

```python
# Load bl32ID plugins
ACTIVE_BEAMLINE = 'bl32ID'

# Load no beamline plugins
ACTIVE_BEAMLINE = None

# Load custom beamline
ACTIVE_BEAMLINE = 'my_beamline'
```

## How It Works

1. **Configuration File**: `src/pystream/beamline_config.py` specifies which beamline to load
2. **Auto-Discovery**: PyStream automatically loads all plugins from the specified beamline
3. **Clean Separation**: Beamline plugins are separate from PyStream's core code
4. **Dynamic Loading**: Only the configured beamline's plugins are loaded

## Configuration Options

### ACTIVE_BEAMLINE

Set this to your beamline folder name, or `None` to disable beamline plugins:

```python
# Options:
ACTIVE_BEAMLINE = 'bl32ID'      # Load bl32ID plugins
ACTIVE_BEAMLINE = None          # No beamline plugins
ACTIVE_BEAMLINE = 'my_beamline' # Custom beamline
```

### ENABLED_PLUGINS

Optionally filter which plugins to load from the active beamline:

```python
# Load all plugins (default)
ENABLED_PLUGINS = None

# Load only specific plugins
ENABLED_PLUGINS = ['SoftBPMDialog', 'DetectorControlDialog', 'QGMaxDialog']
```

## Available Beamlines

### bl32ID

Beamline 32-ID plugins include:
- **SoftBPM**: Software beam position monitor
- **Detector Control**: Manage camera binning and ROI with crop-based system
- **Rotation Axis**: Detect rotation axis for tomography
- **QGMax**: Quantum Gain Maximizer for optimizing image quality
- **Mosalign**: 2D motor scanning and alignment
- **XANES GUI**: External launcher for XANES energy calibration
- **Optics Calc**: External launcher for TXM optics calculator

## Creating Custom Beamlines

See the [Launcher Guide](launcher_guide.md) for detailed instructions on creating custom beamline plugins.

### Basic Steps

1. **Create beamline folder**:
   ```bash
   mkdir src/pystream/beamlines/my_beamline
   ```

2. **Create `__init__.py`**:
   ```python
   """My beamline plugins."""

   from .my_plugin import MyPluginDialog

   __all__ = ['MyPluginDialog']
   ```

3. **Create plugin file** (e.g., `my_plugin.py`):
   ```python
   from PyQt5 import QtWidgets

   class MyPluginDialog(QtWidgets.QDialog):
       """My custom plugin."""

       BUTTON_TEXT = "My Plugin"  # Text shown on toolbar button

       def __init__(self, parent=None, logger=None):
           super().__init__(parent)
           self.setWindowTitle("My Plugin")
           # ... plugin implementation
   ```

4. **Configure PyStream**:
   ```python
   # In src/pystream/beamline_config.py
   ACTIVE_BEAMLINE = 'my_beamline'
   ```

## Plugin Requirements

For a plugin to be properly loaded:

1. Must be a `QDialog` subclass with name ending in `Dialog`
2. Must be exported in the beamline's `__init__.py` via `__all__`
3. Should define `BUTTON_TEXT` class attribute for custom button text
4. Must accept `parent` and `logger` parameters in `__init__`

## Examples

### Example 1: Default Configuration

```python
# src/pystream/beamline_config.py
ACTIVE_BEAMLINE = 'bl32ID'
ENABLED_PLUGINS = None  # Load all plugins
```

**Result**: All bl32ID plugins appear in toolbar

### Example 2: Selective Plugins

```python
# src/pystream/beamline_config.py
ACTIVE_BEAMLINE = 'bl32ID'
ENABLED_PLUGINS = ['SoftBPMDialog', 'DetectorControlDialog', 'QGMaxDialog']
```

**Result**: Only SoftBPM, Detector Control, and QGMax buttons appear

### Example 3: No Beamline Plugins

```python
# src/pystream/beamline_config.py
ACTIVE_BEAMLINE = None
```

**Result**: Clean interface with no beamline-specific buttons

## Sharing Beamlines

To share your beamline with colleagues:

```bash
# Export your beamline folder
tar -czf my_beamline.tar.gz src/pystream/beamlines/my_beamline/

# Colleagues can install with:
tar -xzf my_beamline.tar.gz
# Then edit beamline_config.py to set ACTIVE_BEAMLINE = 'my_beamline'
```

## Troubleshooting

### "No beamline configured"
Edit `src/pystream/beamline_config.py` and set `ACTIVE_BEAMLINE` to your beamline name.

### "Beamline 'xxx' not found"
Check that folder `src/pystream/beamlines/xxx/` exists and matches `ACTIVE_BEAMLINE`.

### "No plugins in xxx"
Verify that `__init__.py` exists and exports dialog classes in `__all__`.

### Plugins not showing up
- Check `ENABLED_PLUGINS` filter - set to `None` to load all
- Verify dialog class names are in beamline's `__all__` list
- Check PyStream logs for import errors

### "Handler not implemented"
The plugin class needs to be registered in PyStream's handler mapping. See the developer documentation for details.
