"""Rectangular slit / aperture defined at a distance from the source."""
from dataclasses import dataclass


@dataclass
class Slit:
    """Rectangular aperture.

    Parameters
    ----------
    distance_m : distance from source to slit (m)
    h_mm, v_mm : full slit width (H, mm) and height (V, mm)
    h_offset_mm, v_offset_mm : slit centre offset from the beam axis (mm)
    """
    distance_m: float = 30.0
    h_mm: float = 1.0
    v_mm: float = 1.0
    h_offset_mm: float = 0.0
    v_offset_mm: float = 0.0

    def h_accept_mrad(self) -> float:
        return self.h_mm / self.distance_m

    def v_accept_mrad(self) -> float:
        return self.v_mm / self.distance_m

    def solid_angle_mrad2(self) -> float:
        return self.h_accept_mrad() * self.v_accept_mrad()
