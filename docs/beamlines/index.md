# Beamlines Plugin System

PyStream supports per-facility plugin packs. Each beamline lives in its
own subdirectory and provides one or more toolbar buttons.

## Selecting a beamline

Edit [src/pystream/beamline_config.py](../../src/pystream/beamline_config.py):

```python
ACTIVE_BEAMLINE = 'bl32ID'   # or 'bl19BM', or None to disable
```

See the [Configuration Guide](configuration.md).

## Toolbar layout

Plugins render as **dropdown menus** in the top toolbar, one menu per
group. A plugin's class attribute `GROUP = "Alignment"` (or `"Scans"`,
`"Tools"`, …) decides which menu it lands in. Order within a menu and
order of menus themselves comes from the beamline's `__all__` list.

Click a menu → pick a plugin → it opens (launcher-style) or shows its
dialog (singleton-style, per each plugin's `HANDLER_TYPE`).

## Using beamline tools

Click **Beamlines** in the top toolbar to show the beamlines bar, then
pick a plugin from any dropdown.

## Core features (present regardless of beamline)

- **AI Agent** — chat panel always docked at the bottom of the main
  window. Beamlines optionally contribute tools + prompt-body via
  `provide_agent_context()`. bl32ID contributes its full 32-ID tool
  catalog; bl19BM (empty scaffold) leaves the agent in pure-chat mode.
  See [Röntgen](txmbot.md).

## Built-in beamlines

- [bl32ID](bl32ID.md) — APS 32-ID TXM imaging + tomography. Full plugin
  suite: CoR, AlignPart, QGMax, XANES, XANES 2D, DataMap, aTomo, ...
- [bl19BM](bl19BM.md) — APS 19-BM. Empty scaffold; no plugins yet.

## Adding a new beamline

Fastest — use the built-in CLI:

```bash
pystream-new-beamline bl7BM --description "APS 7-BM tomography"
```

This creates `src/pystream/beamlines/bl7BM/__init__.py` with an empty
plugin list and no-op `start_background_services()`. See
[Adding a Beamline](adding_a_beamline.md) for the full flow (register
plugins, set ACTIVE_BEAMLINE, add a pip extra).

For launching standalone GUI scripts as separate processes, see the
[Launcher Guide](launcher_guide.md).

```{toctree}
:maxdepth: 2
:hidden:

configuration
bl32ID
bl19BM
adding_a_beamline
txmbot
launcher_guide
```
