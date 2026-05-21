"""bl32ID beamline plugins."""

from .mosalign import MotorScanDialog
from .softbpm import SoftBPMDialog
from .detectorcontrol import DetectorControlDialog
from .xanesgui import XANESGuiDialog
from .xanes2dgui import XANES2DGuiDialog
from .opticscalc import OpticsCalcDialog
from .rotationaxis import RotationAxisDialog
from .qgmax import QGMaxDialog, ensure_qgmax_background_watcher
from .autocenter import AutoCenterDialog
from .blgui import BLGuiDialog
from .agent import AgentDialog
from .datamap import DataMapDialog

__all__ = ['MotorScanDialog', 'SoftBPMDialog', 'DetectorControlDialog', 'XANESGuiDialog', 'XANES2DGuiDialog', 'OpticsCalcDialog', 'RotationAxisDialog', 'QGMaxDialog', 'AutoCenterDialog', 'BLGuiDialog', 'AgentDialog', 'DataMapDialog']


def start_background_services(parent_window):
    """Invoked by pystream.py after the main window is built. Starts any
    long-running watchers that should be active whether or not the user has
    opened the corresponding dialog — currently just the QGMax request-file
    listener."""
    try:
        ensure_qgmax_background_watcher(parent_window)
    except Exception:
        pass
