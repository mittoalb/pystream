"""Base Source ABC and shared spectral utilities.

Spectral quantities returned throughout the package:
  - flux_density(E, ...)  : d^2N / dtheta_h dtheta_v  [ph/s/mrad^2/0.1%BW] (on-axis)
  - angular_flux(E, ...)  : dN / dtheta_h            [ph/s/mrad/0.1%BW]  (vertical-integrated)
  - flux_through_slit(E, distance, hslit, vslit) : [ph/s/0.1%BW]

Units convention: E is photon energy in keV. Machine/ID parameters use
the units named in the class docstring.
"""
from abc import ABC, abstractmethod
import numpy as np


class Source(ABC):
    """Common interface for all x-ray sources."""

    kind: str = "source"

    # ---- required per-source ---------------------------------------------
    @abstractmethod
    def angular_flux(self, E_keV, theta_v_mrad=0.0):
        """Flux per unit horizontal angle at photon energy E, integrated over
        the vertical (or evaluated at vertical angle `theta_v_mrad`).

        Returns array in ph/s/mrad/0.1%BW with the same shape as `E_keV`.
        """

    @abstractmethod
    def flux_density(self, E_keV, theta_h_mrad=0.0, theta_v_mrad=0.0):
        """Flux per unit solid angle in ph/s/mrad^2/0.1%BW."""

    # ---- shared -----------------------------------------------------------
    def flux_through_slit(self, E_keV, distance_m, hslit_mm, vslit_mm,
                          hoffset_mm=0.0, voffset_mm=0.0, n_theta=25):
        """Photon flux transmitted by a rectangular aperture.

        distance_m : source-to-slit distance (m)
        hslit_mm, vslit_mm : total slit opening (mm)
        hoffset_mm, voffset_mm : slit center offset from beam axis (mm)
        n_theta : integration samples per axis (odd -> includes centre)

        Returns array in ph/s/0.1%BW with same shape as `E_keV`.
        """
        E = np.atleast_1d(np.asarray(E_keV, dtype=float))
        # Angular half-widths in mrad
        h_half = (hslit_mm * 0.5) / distance_m  # mrad
        v_half = (vslit_mm * 0.5) / distance_m
        h_c = hoffset_mm / distance_m
        v_c = voffset_mm / distance_m

        th_h = np.linspace(h_c - h_half, h_c + h_half, n_theta)
        th_v = np.linspace(v_c - v_half, v_c + v_half, n_theta)
        dth_h = (th_h[-1] - th_h[0]) / max(n_theta - 1, 1)
        dth_v = (th_v[-1] - th_v[0]) / max(n_theta - 1, 1)

        # Sum flux_density on the (n_theta x n_theta) grid, times cell area.
        # Loop over grid to keep memory small for wide E arrays.
        out = np.zeros_like(E)
        for tv in th_v:
            for th in th_h:
                out += self.flux_density(E, theta_h_mrad=th, theta_v_mrad=tv)
        out *= dth_h * dth_v
        if out.shape == () or out.size == 1 and np.ndim(E_keV) == 0:
            return float(out.ravel()[0])
        return out

    # ---- pretty ----------------------------------------------------------
    def describe(self) -> str:
        parts = [f"{self.__class__.__name__}"]
        for k in ("E_GeV", "current_A", "B_T", "period_mm", "N_periods", "K"):
            if hasattr(self, k):
                parts.append(f"{k}={getattr(self, k)!r}")
        return "  ".join(parts)
