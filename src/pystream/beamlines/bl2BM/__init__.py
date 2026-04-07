"""bl2BM beamline plugins."""

from .detectorcontrol import DetectorControlDialog
from .mosalign import MotorScanDialog

__all__ = ['DetectorControlDialog', 'MotorScanDialog']
