# Beamline Configuration for PyStream

PyStream now supports configurable beamline plugins, allowing users to personalize their installation without modifying PyStream's core code.

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
3. **Clean Separation**: Your beamline plugins are separate from PyStream's core code

## Configuration Options

### ACTIVE_BEAMLINE

Set this to your beamline folder name, or `None` to disable beamline plugins:

```python
# Options:
ACTIVE_BEAMLINE = 'bl32ID'      # Load bl32ID plugins
ACTIVE_BEAMLINE = 'bl6ID'       # Load bl6ID plugins (if you create it)
ACTIVE_BEAMLINE = None          # No beamline plugins
```

### ENABLED_PLUGINS (Optional)

Optionally filter which plugins to load from the active beamline:

```python
# Load all plugins (default)
ENABLED_PLUGINS = None

# Load only specific plugins
ENABLED_PLUGINS = ['SoftBPMDialog', 'DetectorControlDialog', 'QGMaxDialog']
```

## Creating Your Own Beamline

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
           # ... rest of your plugin code
   ```

4. **Configure PyStream** to use your beamline:
   ```python
   # In beamline_config.py
   ACTIVE_BEAMLINE = 'my_beamline'
   ```

5. **Add handler** (if needed) in `pystream.py`:
   ```python
   def _open_my_plugin(self, module):
       """Open My Plugin dialog"""
       if not hasattr(self, 'my_plugin_dialog') or self.my_plugin_dialog is None:
           self.my_plugin_dialog = module.MyPluginDialog(parent=self, logger=LOGGER)
       self.my_plugin_dialog.show()
       self.my_plugin_dialog.raise_()
       self.my_plugin_dialog.activateWindow()
   ```

   And register it in `_connect_beamline_button`:
   ```python
   handlers = {
       # ... existing handlers
       'MyPluginDialog': lambda: self._open_my_plugin(module),
   }
   ```

## Plugin Requirements

For a plugin to be properly loaded, it should:

1. **Be a QDialog subclass** with name ending in `Dialog`
2. **Export from `__init__.py`** in the `__all__` list
3. **Optionally define `BUTTON_TEXT`** class attribute for custom button text
4. **Accept `parent` and `logger` parameters** in `__init__`

## Examples

### Example 1: Default Configuration (bl32ID)

```python
# beamline_config.py
ACTIVE_BEAMLINE = 'bl32ID'
ENABLED_PLUGINS = None  # Load all plugins
```

**Result**: All bl32ID plugins appear in toolbar:
- bl32ID: [Mosalign] [SoftBPM] [Detector Control] [Rotation Axis] [XANES GUI] [Optics Calc] [QGMax]

### Example 2: Selective Plugins

```python
# beamline_config.py
ACTIVE_BEAMLINE = 'bl32ID'
ENABLED_PLUGINS = ['SoftBPMDialog', 'DetectorControlDialog', 'QGMaxDialog']
```

**Result**: Only selected plugins appear:
- bl32ID: [SoftBPM] [Detector Control] [QGMax]

### Example 3: No Beamline

```python
# beamline_config.py
ACTIVE_BEAMLINE = None
ENABLED_PLUGINS = None
```

**Result**: Toolbar shows:
- "No beamline configured (edit beamline_config.py)"

### Example 4: Multiple Beamline Support

Users at different beamlines can each have their own configuration:

```python
# User at bl32ID
ACTIVE_BEAMLINE = 'bl32ID'

# User at bl6ID
ACTIVE_BEAMLINE = 'bl6ID'

# User who doesn't need beamline plugins
ACTIVE_BEAMLINE = None
```

## Sharing Your Beamline

To share your beamline configuration with colleagues:

1. **Export your beamline folder**:
   ```bash
   tar -czf my_beamline.tar.gz src/pystream/beamlines/my_beamline/
   ```

2. **Share** the tarball and instructions:
   ```bash
   # Installation for colleagues
   cd /path/to/pystream
   tar -xzf my_beamline.tar.gz

   # Edit beamline_config.py
   ACTIVE_BEAMLINE = 'my_beamline'
   ```

## Migration from Old System

If you had plugins in the old system (where all beamlines were loaded), no migration is needed:

1. Your existing plugins in `src/pystream/beamlines/bl32ID/` still work
2. The new config defaults to `'bl32ID'` if config file is missing
3. Edit `beamline_config.py` to customize

## Troubleshooting

### "No beamline configured"
- Edit `beamline_config.py` and set `ACTIVE_BEAMLINE` to your beamline name

### "Beamline 'xxx' not found"
- Check that folder `src/pystream/beamlines/xxx/` exists
- Verify the folder name matches `ACTIVE_BEAMLINE`

### "No plugins in xxx"
- Check that `__init__.py` exists and exports dialog classes in `__all__`
- Verify plugin files don't start with underscore `_`

### "Handler not implemented"
- Add handler method in `pystream.py` (see "Add handler" section above)
- Register handler in `_connect_beamline_button` method

### Plugins not showing up
- Check `ENABLED_PLUGINS` filter - set to `None` to load all
- Verify dialog class names are in beamline's `__all__` list
- Check PyStream logs for import errors
