# Launcher Guide

A launcher is a beamline button that runs an external Python GUI as a
separate process. Use it when you want to surface an existing standalone
tool from the PyStream toolbar without pulling its dependencies into
PyStream itself.

## Adding a launcher

1. Copy [src/pystream/beamlines/bl32ID/_launcher_template.py](../../src/pystream/beamlines/bl32ID/_launcher_template.py)
   to a new file in your beamline directory (e.g. `mygui.py`).
2. Edit `SCRIPT_PATH` (or the list of candidate paths), `BUTTON_TEXT`,
   and the class name (e.g. `MyGuiDialog`).
3. Import the class in the beamline's `__init__.py` and add it to
   `__all__`.
4. In [src/pystream/pystream.py](../../src/pystream/pystream.py)
   `_create_beamlines_bar()`, add a `hasattr(module, 'MyGuiDialog')`
   branch wired to a small `_open_my_gui()` handler that instantiates
   the dialog. See `_open_xanes_gui()` for a working example.
5. Restart PyStream.

The launcher spawns the script with `sys.executable` and
`start_new_session=True` so it survives PyStream exit. If the script
isn't found, the user gets a dialog with the candidate paths and any
installation hint you put in the description.
