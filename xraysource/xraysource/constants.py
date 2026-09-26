"""Physical constants and unit helpers for synchrotron radiation formulas.

All formulas follow the conventions in:
  K.-J. Kim, "Characteristics of Synchrotron Radiation", AIP Conf. Proc. 184 (1989)
  X-ray Data Booklet (LBNL, rev. 3), section 2.
"""
import numpy as np

# Electron rest energy
E_REST_MEV = 0.5109989461
E_REST_GEV = E_REST_MEV * 1e-3
E_REST_EV  = E_REST_MEV * 1e6

# Planck * c
HC_EV_NM  = 1239.841984
HC_KEV_ANG = 12.39841984  # keV * angstrom


def gamma_from_energy(E_GeV: float) -> float:
    """Lorentz factor of the electron beam at energy `E_GeV` (GeV)."""
    return E_GeV / E_REST_GEV


def critical_energy_keV(E_GeV: float, B_T: float) -> float:
    """Critical photon energy of a bending magnet or wiggler pole.

    epsilon_c [keV] = 0.665 * E^2[GeV] * B[T]
    """
    return 0.665 * E_GeV * E_GeV * B_T


def K_from_B(B_T: float, period_mm: float) -> float:
    """Deflection parameter K = e B lambda_u / (2 pi m_e c) for a planar ID.

    Numerically K = 0.09337 * B[T] * lambda_u[mm]  (standard convention).
    """
    return 0.09337 * B_T * period_mm


def B_from_K(K: float, period_mm: float) -> float:
    """Inverse of `K_from_B`: field required to reach a given K at a given period."""
    return K / (0.09337 * period_mm)


def energy_to_wavelength_A(E_keV):
    """Photon energy (keV) -> wavelength (angstrom)."""
    E = np.asarray(E_keV, dtype=float)
    return HC_KEV_ANG / np.where(E > 0, E, np.nan)


def wavelength_to_energy_keV(lam_A):
    """Wavelength (angstrom) -> photon energy (keV)."""
    lam = np.asarray(lam_A, dtype=float)
    return HC_KEV_ANG / np.where(lam > 0, lam, np.nan)
