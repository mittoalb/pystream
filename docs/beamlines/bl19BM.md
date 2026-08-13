# bl19BM Beamline Plugins

APS beamline 19-BM. **Empty scaffold** — no plugins registered yet.

## Status

Only the package skeleton exists ([src/pystream/beamlines/bl19BM/__init__.py](../../src/pystream/beamlines/bl19BM/__init__.py)):

```python
__all__: list[str] = []


def start_background_services(parent_window):
    pass
```

Selecting `ACTIVE_BEAMLINE = 'bl19BM'` in
[beamline_config.py](../../src/pystream/beamline_config.py) shows the
beamline in the toolbar but with no menus (no plugins to group).

## Adding plugins

Same as bl32ID — drop a Python file in this folder with a `QDialog`
subclass declaring `BUTTON_TEXT`, `GROUP`, and `HANDLER_TYPE`, then
import + register in `__all__`. See [bl32ID](bl32ID.md) for a fully-
wired reference and [Adding a Beamline](adding_a_beamline.md) for the
full workflow (pip extras, `ACTIVE_BEAMLINE`, etc.).

## Pip extras

Declared in [pyproject.toml](../../pyproject.toml) under
`[project.optional-dependencies]` as an empty list — `pip install
".[bl19BM]"` installs the base package cleanly, no external deps yet.
Add plugin dependencies here as plugins are registered.
