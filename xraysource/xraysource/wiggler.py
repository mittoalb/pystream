"""Multi-pole wiggler (large K, incoherent superposition of BM poles).

For a planar wiggler with N periods (2N poles) and peak field B_peak the
critical energy is evaluated with B = B_peak (each pole radiates as a
BM). For K >> 1 the horizontal fan sweeps +/- K/gamma and interference
between poles washes out; the total flux is 2N times a single BM pole.

References: Kim (1989); Wiedemann, "Synchrotron Radiation" (2003) ch. 24.
"""
import numpy as np

from .constants import (
    K_from_B, B_from_K, gamma_from_energy, critical_energy_keV,
)
from .bending_magnet import BendingMagnet
from .sources import Source
from . import _specfuncs as sf


class Wiggler(Source):
    """Planar wiggler.

    Parameters
    ----------
    E_GeV : storage ring electron energy (GeV)
    current_A : stored current (A)
    period_mm : magnetic period lambda_u (mm)
    N_periods : number of full periods
    B_T : peak field (T), or
    K : deflection parameter (K = 0.09337 * B[T] * lambda_u[mm]).

    Exactly one of B_T or K must be given.
    """

    kind = "wiggler"

    def __init__(self, E_GeV=7.0, current_A=0.1, period_mm=85.0,
                 N_periods=28, B_T=None, K=None):
        if (B_T is None) == (K is None):
            raise ValueError("Provide exactly one of B_T or K")
        if B_T is None:
            B_T = B_from_K(K, period_mm)
        if K is None:
            K = K_from_B(B_T, period_mm)

        self.E_GeV = float(E_GeV)
        self.current_A = float(current_A)
        self.period_mm = float(period_mm)
        self.N_periods = int(N_periods)
        self.B_T = float(B_T)
        self.K = float(K)
        self.gamma = gamma_from_energy(self.E_GeV)
        self.epsilon_c_keV = critical_energy_keV(self.E_GeV, self.B_T)
        # Full sweep angle (mrad)
        self.hsweep_mrad = 2.0 * self.K / self.gamma * 1e3

    # ------------------------------------------------------------------
    def y(self, E_keV):
        return np.asarray(E_keV, dtype=float) / self.epsilon_c_keV

    def angular_flux(self, E_keV, theta_v_mrad=0.0):
        """dF/dtheta_h in ph/s/mrad/0.1%BW.

        Approximation valid for K >> 1 (flat fan): 2N times the BM
        vertical-integrated formula.
        """
        y = self.y(E_keV)
        return (2 * self.N_periods) * 2.457e13 * self.E_GeV * self.current_A * sf.G1(y)

    def flux_density(self, E_keV, theta_h_mrad=0.0, theta_v_mrad=0.0):
        """d^2F/(dtheta_h dtheta_v) in ph/s/mrad^2/0.1%BW.

        For |theta_h| <= K/gamma the flux equals the single-pole BM flux
        density times 2N. Outside the sweep it drops rapidly; we model
        this with a smooth erfc cutoff over 1/gamma to keep the integral
        well-behaved. This is exact in the flat-fan (K>>1) limit.
        """
        E = np.asarray(E_keV, dtype=float)
        y = self.y(E)
        psi_rad = np.asarray(theta_v_mrad, dtype=float) * 1e-3
        X = self.gamma * psi_rad
        S_sigma, S_pi = sf.bending_magnet_S_functions(y, X)
        base = (1.327e13 * self.E_GeV**2 * self.current_A
                * y * y * (S_sigma + S_pi))

        # Horizontal window: flat inside +/- K/gamma, erfc taper of
        # width ~1/gamma at the edges.
        th = np.asarray(theta_h_mrad, dtype=float) * 1e-3
        half = self.K / self.gamma
        edge = 1.0 / self.gamma
        from scipy.special import erfc
        gate = 0.5 * (erfc((np.abs(th) - half) / (edge + 1e-30)))
        return (2 * self.N_periods) * base * gate

    # ------------------------------------------------------------------
    def total_angular_flux(self, E_keV):
        """Full-sweep vertical-integrated flux: dF/dtheta * 2K/gamma."""
        return self.angular_flux(E_keV) * self.hsweep_mrad
