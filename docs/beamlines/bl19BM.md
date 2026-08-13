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

## AI Agent on bl19BM

The **AI Agent panel still appears** at the bottom of the window —
pystream provides it as a core feature, not per-beamline. On bl19BM the
agent runs in pure-chat mode: no tool catalog, no beamline-specific
system-prompt body, but the model still answers general questions using
the configured LLM backend and the agent's default identity (Röntgen,
or whatever you rename it in ⚙ Settings). The system prompt still
substitutes `{beamline}` → `bl19BM`.

To give the agent 19-BM-specific tools, add a `provide_agent_context()`
function to `bl19BM/__init__.py` returning a dict of tool specs +
prompt addendum. See [Röntgen — Adding a new tool](txmbot.md#adding-a-new-tool)
for the exact shape, and [bl32ID/__init__.py](../../src/pystream/beamlines/bl32ID/__init__.py)
for a reference implementation.

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
