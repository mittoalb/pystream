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
# NOTE: AgentDialog is NOT imported at package level. It's still available
# via `from pystream.beamlines.bl32ID.agent import AgentDialog` and is
# opened on demand by the AI Agent panel's ⚙ Settings button. Toolbar
# registration would be redundant (chat is always visible at the bottom).
from .datamap import DataMapDialog
from .xraytools import XRayToolsDialog
from .autofocus import AutofocusLauncherDialog
from .atomo import AtomoLauncherDialog

# AgentDialog is intentionally NOT in __all__ — the AI Agent is
# available as a permanent bottom panel (via `provide_bottom_panels`
# below) with its own ⚙ Settings button that opens the full dialog on
# demand. A toolbar button would be redundant. The class is still
# importable (for the Settings button to instantiate it) via
# `from pystream.beamlines.bl32ID.agent import AgentDialog`.
__all__ = ['MotorScanDialog', 'CenterOfRotationDialog', 'ParticleAlignDialog', 'DetectorControlDialog', 'XANESGuiDialog', 'XANES2DGuiDialog', 'XANES2DViewerDialog', 'OpticsCalcDialog', 'RotationAxisDialog', 'QGMaxDialog', 'AutoCenterDialog', 'BLGuiDialog', 'DataMapDialog', 'XRayToolsDialog', 'AutofocusLauncherDialog', 'AtomoLauncherDialog']


def start_background_services(parent_window):
    """Invoked by pystream.py after the main window is built. Starts any
    long-running watchers that should be active whether or not the user has
    opened the corresponding dialog — currently just the QGMax request-file
    listener."""
    try:
        ensure_qgmax_background_watcher(parent_window)
    except Exception:
        pass


def provide_bottom_panels(parent_window):
    """Invoked by pystream.py after the main window + background services
    are up. Returns a list of (QWidget, title_str) pairs that pystream
    inserts into its central vertical splitter beneath the viewer.

    Panels are real children of the central widget (not floating
    QDockWidgets) — user can resize via the splitter handle, hide via
    the View menu, but not drag/detach.

    Currently: the AI Agent chat panel."""
    try:
        from .agent import build_agent_panel
        return [(build_agent_panel(parent_window), "AI Agent")]
    except Exception:
        return []
