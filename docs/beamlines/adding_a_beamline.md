# Adding a Beamline

Two paths — the one-command scaffold or the manual steps.

## Fast path: `pystream-new-beamline`

```bash
pystream-new-beamline bl7BM
pystream-new-beamline bl22ID --description "APS 22-ID microdiffraction"
pystream-new-beamline bl2BM --dry-run          # print without writing
pystream-new-beamline bl19BM --overwrite       # replace an existing scaffold
```

The CLI creates `src/pystream/beamlines/<name>/__init__.py` with an
empty plugin list and a no-op `start_background_services()` hook, then
prints the next steps: add a pip extra, set `ACTIVE_BEAMLINE`, restart
pystream.

Registered as a console script in
[pyproject.toml](../../pyproject.toml) `[project.scripts]`. Source at
[src/pystream/tools/new_beamline.py](../../src/pystream/tools/new_beamline.py).

**Guards**:
- Rejects names that aren't valid Python identifiers (`19bl`, `bl-19`,
  `bl 19` all fail — must be letters/digits/underscore, no leading digit).
- Refuses to overwrite an existing beamline package unless
  `--overwrite` is passed.
- `--dry-run` prints what would be written without touching the
  filesystem.

## Manual path

If you'd rather do it by hand:

1. **Create the package**:
   ```bash
   mkdir -p src/pystream/beamlines/bl<ID>/
   cat > src/pystream/beamlines/bl<ID>/__init__.py <<'EOF'
   """bl<ID> beamline plugins."""
   __all__: list[str] = []
   def start_background_services(parent_window): pass
   EOF
   ```

2. **Add a pip extra** (optional but recommended). In
   [pyproject.toml](../../pyproject.toml) under
   `[project.optional-dependencies]`:
   ```toml
   bl<ID> = [
     # git+URL or PyPI deps for tools this beamline needs
   ]
   ```

3. **Register plugins** as you add them. Each plugin is a `QDialog` or
   `QWidget` with class attributes:
   ```python
   class MyPluginDialog(QtWidgets.QDialog):
       BUTTON_TEXT  = "MyPlugin"          # shown in the menu
       GROUP        = "Alignment"          # dropdown menu name
       HANDLER_TYPE = 'singleton'          # or 'launcher' / 'multi-instance'
       def __init__(self, parent=None, logger=None):
           ...
   ```
   Import + append to `__all__` in the beamline's `__init__.py`.

4. **Activate**: edit
   [src/pystream/beamline_config.py](../../src/pystream/beamline_config.py):
   ```python
   ACTIVE_BEAMLINE = 'bl<ID>'
   ```

5. **Install with extras + restart pystream**:
   ```bash
   pip install -e ".[bl<ID>]"
   pystream --pv YOUR:PV
   ```

## Groups

`GROUP` values are free-form strings. Group order in the toolbar comes
from the first-appearance of each value in `__all__`. Standard groups
used by bl32ID:

- `"Alignment"` — motor-move tools (CoR, AlignPart, QGMax, Mosalign)
- `"Scans"` — scan launchers (XANES, XANES 2D, DataMap, aTomo)
- `"Detector"` — detector setup
- `"Viewers"` — offline data viewers
- `"Calculators"` — reference calculators
- `"Tools"` — misc (BL GUI)
- `"Test"` — under-development plugins

The **AI Agent** does not use `GROUP` — it's a core bottom-panel widget,
not a beamline plugin. Beamlines contribute tools + prompt body to it
through the optional `provide_agent_context()` hook (see below).

`HANDLER_TYPE`:

- `'singleton'` — one instance kept alive; toolbar button shows/hides it
- `'launcher'` — instantiate + close each time (for fire-and-forget
  subprocess spawners)
- `'multi-instance'` — new instance each click

## Optional beamline hooks

Beamline `__init__.py` can expose these at module level; pystream calls
them if present, otherwise silently skips:

| Hook | When called | What it does |
|---|---|---|
| `start_background_services(parent_window)` | Once, after main window is built | Start watchers, seed knowledge bases, etc. bl32ID uses it for QGMax's request-file listener and the agent knowledge-base bootstrap. |
| `provide_agent_context()` | On every AI Send | Return a dict of tool specs, dispatcher, write-tool set, destructive-command classifier, and prompt-body addendum. Omit for pure-chat AI on this beamline. See [Röntgen](txmbot.md#beamline-specific-tools-and-prompt). |
