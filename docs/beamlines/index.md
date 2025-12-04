# Beamlines Plugin System

PyStream includes an extensible beamlines plugin system that automatically discovers and loads beamline-specific tools.

## Overview

The beamlines system allows each beamline facility to have its own set of specialized tools that appear in a dedicated toolbar. This enables customization for different experimental setups without modifying the core PyStream application.

## Features

- **Automatic Discovery**: PyStream automatically scans the `beamlines/` directory and discovers all available beamline plugins
- **Dynamic Loading**: Plugins are loaded on-demand when the user clicks the corresponding toolbar button
- **Modular Architecture**: Each beamline has its own isolated directory with independent tools
- **Horizontal Toolbar**: Beamline tools appear in a collapsible horizontal toolbar below the main toolbar

## Directory Structure

```
src/pystream/beamlines/
├── bl32ID/
│   ├── __init__.py
│   ├── mosalign.py
│   └── mosaic.sh
├── bl02BM/
│   └── ... (beamline-specific tools)
└── ... (additional beamlines)
```

Each beamline directory must:
1. Be a valid Python package (contain `__init__.py`)
2. Export its tools for auto-discovery

## Usage

### Accessing Beamline Tools

1. Click the **"Beamlines"** button in the top toolbar
2. A horizontal toolbar appears showing all discovered beamlines
3. Click a beamline button (e.g., "bl32ID") to see its tools
4. Select a tool from the dropdown menu to launch it

### For Users

The beamlines toolbar automatically discovers plugins from the installation's beamlines directory. No configuration is needed - simply install PyStream and all available beamline tools will be accessible.

### For Beamline Scientists

To add your own beamline-specific tools:

1. **Create a beamline directory**:
   ```bash
   mkdir src/pystream/beamlines/bl<YOUR_BEAMLINE_ID>
   cd src/pystream/beamlines/bl<YOUR_BEAMLINE_ID>
   ```

2. **Create the package file**:
   ```python
   # __init__.py
   from .your_tool import YourTool

   __all__ = ['YourTool']
   ```

3. **Create your tool**:
   ```python
   # your_tool.py
   from PyQt5 import QtWidgets

   class YourTool(QtWidgets.QDialog):
       def __init__(self, parent=None):
           super().__init__(parent)
           self.setWindowTitle("Your Tool")
           # Add your tool's UI and logic here
   ```

4. **Your tool will automatically appear** in the Beamlines toolbar next time PyStream starts

## Current Beamlines

### bl32ID

Advanced Photon Source beamline 32-ID with the following tools:

- **Mosalign**: 2D motor scanning with image stitching and tomoscan integration
  - See [Mosalign Documentation](../plugins/mosalign.md) for details

## Auto-Discovery Mechanism

The beamlines system uses Python's `importlib` to dynamically discover plugins:

1. Scans `src/pystream/beamlines/` directory
2. Identifies all subdirectories (excluding `__pycache__`)
3. Attempts to import each directory as a Python module
4. Extracts beamline ID from directory name
5. Creates toolbar buttons for each valid beamline
6. Loads available tools from each beamline module

This approach ensures:
- No hardcoded beamline lists
- Easy addition of new beamlines
- Isolated plugin environments
- Graceful handling of import errors

## Plugin Development Guidelines

### Naming Conventions

- Beamline directories should follow the pattern: `bl<ID>` (e.g., `bl32ID`, `bl02BM`)
- Tool classes should be descriptive and follow PascalCase (e.g., `MosalignDialog`, `ScanController`)
- Tool files should use snake_case (e.g., `mosalign.py`, `scan_control.py`)

### Best Practices

1. **Isolation**: Keep beamline-specific code within the beamline directory
2. **Documentation**: Add docstrings to all classes and methods
3. **Error Handling**: Implement proper exception handling for EPICS PV access and file operations
4. **User Feedback**: Provide clear status messages and progress indicators
5. **Configuration**: Store settings in user config directory (`~/.pystream/`)

### Integration with PyStream

Beamline tools can access PyStream's core functionality:

```python
from PyQt5 import QtWidgets
from pystream.logger import get_logger

class YourTool(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # Access parent's image viewer if needed
        if hasattr(parent, 'image_view'):
            self.image_view = parent.image_view
```

## Technical Details

### Plugin Loading

Plugins are loaded using lazy importing to minimize startup time:

```python
# Only imports when user clicks the beamline button
def _toggle_beamlines_bar(self):
    if self.beamlines_bar.isVisible():
        self.beamlines_bar.hide()
    else:
        self.beamlines_bar.show()
```

### Error Handling

If a beamline plugin fails to import:
- The error is logged but doesn't crash PyStream
- The beamline still appears in the toolbar (for visibility)
- User sees an informative error message if they try to use it

### Memory Management

Beamline tools are instantiated on-demand and cleaned up when closed, minimizing memory footprint.

## Future Enhancements

Potential future improvements to the beamlines system:

- Plugin metadata (version, author, description)
- Plugin dependencies and requirements checking
- Configuration UI for plugin settings
- Plugin marketplace/repository
- Hot-reloading for plugin development

## Troubleshooting

### Beamline not appearing in toolbar

1. Check directory is in `src/pystream/beamlines/`
2. Verify `__init__.py` exists
3. Check for import errors in the log
4. Ensure directory name starts with valid Python identifier

### Tool fails to load

1. Check tool class is properly imported in `__init__.py`
2. Verify all dependencies are installed
3. Check PyStream log for detailed error messages
4. Ensure tool class inherits from appropriate Qt widget

### EPICS connectivity issues

1. Verify EPICS environment variables are set
2. Test PV access with `caget` command
3. Check network connectivity to IOCs
4. Verify PV names in tool configuration
