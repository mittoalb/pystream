# Beamline Configuration

Configure which beamline plugins to load by editing `src/pystream/beamline_config.py`:

```python
# Load bl32ID plugins
ACTIVE_BEAMLINE = 'bl32ID'

# Load no beamline plugins
ACTIVE_BEAMLINE = None

# Filter specific plugins (optional)
ENABLED_PLUGINS = ['SoftBPMDialog', 'QGMaxDialog']  # or None for all
```

## Creating Custom Beamlines

1. **Create folder**: `src/pystream/beamlines/my_beamline/`
2. **Create `__init__.py`**:
   ```python
   from .my_plugin import MyPluginDialog
   __all__ = ['MyPluginDialog']
   ```
3. **Create plugin** (`my_plugin.py`):
   ```python
   from PyQt5 import QtWidgets

   class MyPluginDialog(QtWidgets.QDialog):
       BUTTON_TEXT = "My Plugin"
       HANDLER_TYPE = 'singleton'  # 'singleton', 'launcher', or 'multi-instance'

       def __init__(self, parent=None, logger=None):
           super().__init__(parent)
           # ... implementation
   ```
4. **Activate**: Set `ACTIVE_BEAMLINE = 'my_beamline'` in config file

## Handler Types

- **singleton**: Single instance, show/hide on click (most plugins)
- **launcher**: Execute external script, no dialog (for standalone tools)
- **multi-instance**: New instance each click (rarely needed)
