"""bl19BM beamline plugins.

Empty scaffold — no plugins registered yet. Add one by:

    1. Create `plugin_name.py` in this folder with a class:
           class MyPluginDialog(QtWidgets.QDialog):
               BUTTON_TEXT  = "MyPlugin"
               GROUP        = "Alignment"      # or "Scans", "Tools", …
               HANDLER_TYPE = 'singleton'      # or 'launcher' / 'multi-instance'
               def __init__(self, parent=None, logger=None): ...
    2. Import + add to __all__ below.

pystream's toolbar builder discovers plugins by iterating this module's
`__all__` and grouping by each class's `GROUP` attribute.

Select this beamline via ~/.pystream/beamline_config (or whichever
config file pystream reads) — see beamline_config.py at the pystream
package root for the mechanism.
"""

__all__: list[str] = []


def start_background_services(parent_window):
    """Hook for long-running watchers that should be active regardless
    of whether the user has opened the corresponding dialog. No services
    yet for bl19BM."""
    pass


# Note: the AI Agent panel comes from the separate `beamline-agent`
# package (mounted by pystream when installed), not from any beamline
# hook. bl19BM doesn't provide `provide_agent_context()` yet, so the
# agent runs as a pure chat here — no tools, no beamline-specific
# system prompt body. Add `provide_agent_context()` when 19-BM gets
# its own tool catalog (see bl32ID's agent_tools.py for a template).
