"""X-ray source spectrum calculator.

Provides:
- BendingMagnet, Wiggler, Undulator classes with spectral flux methods
- FilterStack for material attenuation (via xraylib)
- Slit for angular acceptance geometry
- Beamline that composes source + slit + filters
"""

from .constants import (
    E_REST_MEV, E_REST_GEV, HC_KEV_ANG, HC_EV_NM,
    gamma_from_energy, critical_energy_keV, K_from_B,
)
from .bending_magnet import BendingMagnet
from .wiggler import Wiggler
from .undulator import Undulator
from .filters import Filter, FilterStack
from .slits import Slit
from .beamline import Beamline
from .logger import get_logger, configure_logging
from . import materials_store

__version__ = "0.1.0"
__all__ = [
    "BendingMagnet", "Wiggler", "Undulator",
    "Filter", "FilterStack", "Slit", "Beamline",
    "gamma_from_energy", "critical_energy_keV", "K_from_B",
    "E_REST_MEV", "E_REST_GEV", "HC_KEV_ANG", "HC_EV_NM",
    "get_logger", "configure_logging", "materials_store",
]
