"""bl32ID beamline plugins."""

from .mosalign import MotorScanDialog
from .cor import CenterOfRotationDialog
from .particle_align import ParticleAlignDialog
from .detectorcontrol import DetectorControlDialog
from .xanesgui import XANESGuiDialog
from .xanes2dgui import XANES2DGuiDialog
from .xanes2dviewer import XANES2DViewerDialog
from .opticscalc import OpticsCalcDialog
from .rotationaxis import RotationAxisDialog
from .qgmax import QGMaxDialog, ensure_qgmax_background_watcher
from .autocenter import AutoCenterDialog
from .blgui import BLGuiDialog
# NOTE: AgentDialog is not imported at package level. The AI Agent
# now lives in the separate `beamline-agent` package (mounted by
# pystream when installed), so bl32ID no longer exposes an agent
# widget of its own — the chat is always the bottom panel.
from .datamap import DataMapDialog
from .xraytools import XRayToolsDialog
from .autofocus import AutofocusLauncherDialog
from .atomo import AtomoLauncherDialog

# AgentDialog is not part of pystream any more — it moved to
# `beamline_agent.chat.AgentDialog` (imported by beamline-agent's
# mount()). The chat still surfaces at the bottom of the pystream
# window when beamline-agent is installed.
__all__ = ['MotorScanDialog', 'CenterOfRotationDialog', 'ParticleAlignDialog', 'DetectorControlDialog', 'XANESGuiDialog', 'XANES2DGuiDialog', 'XANES2DViewerDialog', 'OpticsCalcDialog', 'RotationAxisDialog', 'QGMaxDialog', 'AutoCenterDialog', 'BLGuiDialog', 'DataMapDialog', 'XRayToolsDialog', 'AutofocusLauncherDialog', 'AtomoLauncherDialog']


def start_background_services(parent_window):
    """Invoked by pystream.py after the main window is built. Two things:
    (1) QGMax request-file listener (runs regardless of QGMax dialog open).
    (2) One-time bootstrap of the 32-ID AI-agent knowledge base
        (~/.pystream/docs symlinks, ioc_scripts.json, status_pages.json).
    Both are idempotent."""
    try:
        ensure_qgmax_background_watcher(parent_window)
    except Exception:
        pass
    try:
        from .agent_tools import bootstrap_knowledge_base
        bootstrap_knowledge_base()
    except Exception:
        pass


def provide_task_templates():
    """{task_display_name: {"motors": [{"label","pv"}, ...],
                             "context": <str>}}
    consumed by pystream's Task Recorder. Task list + motor PVs +
    curated context strings live in bl32ID/task_templates.py, mirroring
    the beamline's txmOptics.substitutions file. Returns {} on any
    import failure so the recorder cleanly falls back to free-text
    mode."""
    try:
        from .task_templates import task_template_map
        return task_template_map()
    except Exception:
        return {}


def provide_agent_context():
    """Beamline-specific tools + prompt-body appended to the core agent
    prompt in beamline_agent.chat. Queried by beamline-agent at every
    Send. Returning None or an empty dict here would make the agent
    tool-less on this beamline (falling back to pure chat)."""
    try:
        from .agent_tools import (
            anthropic_tool_specs, openai_tool_specs, get_tool,
            WRITE_TOOLS, _bash_is_destructive, SYSTEM_PROMPT_ADDENDUM,
        )
        return {
            "tool_specs_anthropic":     anthropic_tool_specs(),
            "tool_specs_openai":        openai_tool_specs(),
            "get_tool":                 get_tool,
            "write_tools":              WRITE_TOOLS,
            "is_destructive":           _bash_is_destructive,
            "system_prompt_addendum":   SYSTEM_PROMPT_ADDENDUM,
        }
    except Exception:
        return {}
