"""Bending magnet spectral flux (Kim / Schwinger).

Reference formulas (K.-J. Kim, "Characteristics of Synchrotron Radiation",
AIP Conf. Proc. 184 (1989), and X-ray Data Booklet, section 2.1):

  epsilon_c[keV] = 0.665 * E^2[GeV] * B[T]
  y              = epsilon / epsilon_c

  Horizontally-integrated (i.e. vertical-angle-integrated) flux per
  unit horizontal angle:
      dF/dtheta = 2.457e13 * E[GeV] * I[A] * G1(y)   [ph/s/mrad/0.1%BW]

  On-axis flux per unit solid angle:
      d^2F/(dtheta d psi)|_{psi=0}
                = 1.327e13 * E^2[GeV] * I[A] * H2(y) [ph/s/mrad^2/0.1%BW]

  Off-axis angular distribution (vertical angle psi):
      d^2F/(dtheta d psi)
          = 1.327e13 * E^2[GeV] * I[A] * y^2 * (S_sigma + S_pi)
      with S_sigma, S_pi as defined in `_specfuncs.bending_magnet_S_functions`.
"""
import numpy as np

from .constants import (
    critical_energy_keV, gamma_from_energy,
)
from .sources import Source
from . import _specfuncs as sf


class BendingMagnet(Source):
    """Bending magnet source.

    Parameters
    ----------
    E_GeV : storage ring electron energy (GeV)
    current_A : stored current (A)
    B_T : magnetic field (T). Either B_T or radius_m must be given.
    radius_m : bending radius (m); B = beta*p/eR ~ E/(cR).
    hdiv_mrad : horizontal fan collected (mrad). Only used by
        `total_angular_flux()`; the per-angle methods are always
        differential.
    """

    kind = "bending_magnet"

    def __init__(self, E_GeV=7.0, current_A=0.1, B_T=None, radius_m=None,
                 hdiv_mrad=None):
        if B_T is None and radius_m is None:
            raise ValueError("Provide either B_T or radius_m")
        if B_T is None:
            # E[GeV]/B[T] = 0.2998 * R[m]  --> B = E/(0.2998*R)
            B_T = E_GeV / (0.2998 * radius_m)
        if radius_m is None:
            radius_m = E_GeV / (0.2998 * B_T)
        self.E_GeV = float(E_GeV)
        self.current_A = float(current_A)
        self.B_T = float(B_T)
        self.radius_m = float(radius_m)
        self.hdiv_mrad = None if hdiv_mrad is None else float(hdiv_mrad)
        self.gamma = gamma_from_energy(self.E_GeV)
        self.epsilon_c_keV = critical_energy_keV(self.E_GeV, self.B_T)

    # ------------------------------------------------------------------
    def y(self, E_keV):
        E = np.asarray(E_keV, dtype=float)
        return E / self.epsilon_c_keV

    def angular_flux(self, E_keV, theta_v_mrad=0.0):
        """dF/dtheta_h in ph/s/mrad/0.1%BW.

        theta_v_mrad is ignored (the flux is integrated over psi already).
        """
        y = self.y(E_keV)
        return 2.457e13 * self.E_GeV * self.current_A * sf.G1(y)

    def flux_density(self, E_keV, theta_h_mrad=0.0, theta_v_mrad=0.0):
        """d^2F/(dtheta_h dtheta_v) in ph/s/mrad^2/0.1%BW.

        For an ideal BM the flux depends only on the vertical angle psi
        (theta_h_mrad is ignored; the field is uniform along the fan).
        """
        E = np.asarray(E_keV, dtype=float)
        y = self.y(E)
        psi_rad = np.asarray(theta_v_mrad, dtype=float) * 1e-3
        X = self.gamma * psi_rad
        S_sigma, S_pi = sf.bending_magnet_S_functions(y, X)
        return (1.327e13 * self.E_GeV**2 * self.current_A
                * y * y * (S_sigma + S_pi))

    def total_angular_flux(self, E_keV):
        """Convenience: dF/dtheta integrated over the fan `hdiv_mrad`.

        Returns ph/s/0.1%BW. Requires `hdiv_mrad` to be set.
        """
        if self.hdiv_mrad is None:
            raise ValueError("Set hdiv_mrad to compute total angular flux")
        return self.angular_flux(E_keV) * self.hdiv_mrad
