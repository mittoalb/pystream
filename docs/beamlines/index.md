# Beamlines Plugin System

PyStream supports per-facility plugin packs. Each beamline lives in its
own subdirectory and provides one or more toolbar buttons.

## Selecting a beamline

Edit [src/pystream/beamline_config.py](../../src/pystream/beamline_config.py):

```python
ACTIVE_BEAMLINE = 'bl32ID'   # or None to disable
```

See the [Configuration Guide](configuration.md).

## Using beamline tools

Click **Beamlines** in the top toolbar to show the beamlines bar, pick a
beamline, then select a tool.

## Built-in beamlines

- [bl32ID](bl32ID.md) — APS 32-ID TXM imaging and tomography tools.

## Adding a new beamline

1. Create `src/pystream/beamlines/bl<ID>/` with an `__init__.py`.
2. In `__init__.py`, import each plugin class and list them in `__all__`:
   ```python
   from .my_tool import MyToolDialog
   __all__ = ['MyToolDialog']
   ```
3. Each plugin class is a `QDialog` (or `QWidget`) with class attributes
   `BUTTON_TEXT = "..."` and `HANDLER_TYPE = 'singleton'`.
4. Set `ACTIVE_BEAMLINE = 'bl<ID>'` in `beamline_config.py` and restart.

For launching standalone GUI scripts as separate processes, see the
[Launcher Guide](launcher_guide.md).

```{toctree}
:maxdepth: 2
:hidden:

configuration
bl32ID
txmbot
launcher_guide
```
