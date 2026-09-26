"""Planar undulator spectrum.

References
----------
K.-J. Kim, "Characteristics of Synchrotron Radiation", AIP Conf. Proc. 184 (1989)
X-ray Data Booklet (LBNL, rev. 3), section 2.1
Elleaume, in "Undulators, Wigglers and their Applications" (2003)

Resonance (on-axis):
    E_n(0)[keV] = 0.9496 * n * E^2[GeV] / (lambda_u[cm] * (1 + K^2/2))

Off-axis red-shift:
    E_n(theta) = E_n(0) / (1 + gamma^2 theta^2 / (1 + K^2/2))

Planar-undulator function (odd n only on-axis):
    F_n(K) = (n K / (1 + K^2/2))^2 * [J_{(n-1)/2}(Y) - J_{(n+1)/2}(Y)]^2
    with Y = n K^2 / (4 + 2 K^2)

Peak on-axis flux density (at E = E_n):
    d^2F/dOmega [ph/s/mrad^2/0.1%BW]
       = 1.744e14 * N^2 * E^2[GeV] * I[A] * F_n(K)

Spectral shape of the n-th harmonic is sinc^2(N pi (E-E_n)/E_n)
(natural bandwidth DeltaE/E ~ 1/(nN) FWHM).

Central-cone integrated flux (odd n):
    F_n [ph/s/0.1%BW] = 1.431e14 * N * I[A] * Q_n(K)
    Q_n(K) = (1 + K^2/2) F_n(K) / n

Central-cone divergence:
    sigma_r' = (1/gamma) * sqrt((1 + K^2/2) / (2 n N))
"""
import numpy as np
from scipy.special import jv

from .constants import (
    K_from_B, B_from_K, gamma_from_energy,
)
from .sources import Source


def _sinc2(x):
    """(sin(pi x)/(pi x))^2, safe at x=0."""
    x = np.asarray(x, dtype=float)
    out = np.ones_like(x)
    m = np.abs(x) > 1e-12
    xm = x[m]
    out[m] = (np.sin(np.pi * xm) / (np.pi * xm)) ** 2
    return out


def F_n_planar(n, K):
    """F_n(K) for a planar undulator (odd n only)."""
    n = int(n)
    K = float(K)
    if n % 2 == 0:
        return 0.0
    denom = 1.0 + K * K / 2.0
    Y = n * K * K / (4.0 + 2.0 * K * K)
    p = (n - 1) // 2
    bess = jv(p, Y) - jv(p + 1, Y)
    return (n * K / denom) ** 2 * bess * bess


def Q_n_planar(n, K):
    """Q_n(K) = (1 + K^2/2) F_n(K) / n."""
    if n % 2 == 0:
        return 0.0
    return (1.0 + K * K / 2.0) * F_n_planar(n, K) / n


class Undulator(Source):
    """Planar undulator source.

    Parameters
    ----------
    E_GeV : storage ring electron energy (GeV)
    current_A : stored current (A)
    period_mm : magnetic period lambda_u (mm)
    N_periods : number of full periods
    B_T : peak field (T), or
    K : deflection parameter (K = 0.09337 * B[T] * lambda_u[mm]).
    energy_spread : relative rms energy spread of the electron beam
        (dimensionless). Broadens each harmonic by n*N*sigma_E/E.
        Default 1e-3 (typical of modern storage rings).
    max_harmonic : max harmonic index summed in the spectrum.
    """

    kind = "undulator"

    def __init__(self, E_GeV=7.0, current_A=0.1, period_mm=33.0,
                 N_periods=72, B_T=None, K=None,
                 energy_spread=1.0e-3, max_harmonic=15):
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
        self.energy_spread = float(energy_spread)
        self.max_harmonic = int(max_harmonic)

        # Derived
        self.length_m = self.period_mm * 1e-3 * self.N_periods
        # Fundamental on-axis (keV)
        self.E1_keV = self._resonance_keV(1, theta=0.0)

    # ---- resonance geometry ------------------------------------------
    def _resonance_keV(self, n, theta=0.0):
        """E_n(theta) in keV."""
        lam_u_cm = self.period_mm * 0.1
        base = 0.9496 * n * self.E_GeV ** 2 / (
            lam_u_cm * (1.0 + self.K * self.K / 2.0)
        )
        red = 1.0 + (self.gamma * theta) ** 2 / (1.0 + self.K * self.K / 2.0)
        return base / red

    def resonance_keV(self, n, theta=0.0):
        """Public alias returning E_n(theta) in keV."""
        return self._resonance_keV(n, theta)

    def central_cone_sigma_mrad(self, n):
        """Central-cone rms angular width (Gaussian approx), mrad."""
        return 1e3 / self.gamma * np.sqrt(
            (1.0 + self.K * self.K / 2.0) / (2.0 * n * self.N_periods)
        )

    def natural_bandwidth(self, n):
        """Relative FWHM natural bandwidth of the n-th harmonic (~1/(nN))."""
        return 1.0 / (n * self.N_periods)

    # ---- spectral flux -----------------------------------------------
    def _harmonic_lineshape(self, E_keV, E_n_keV, n):
        """Gaussian-broadened lineshape for harmonic n.

        We use a Gaussian approximation to the natural sinc^2 convolved
        with the electron-beam energy-spread contribution. The pure
        sinc^2 has real far-tail sidelobes that are numerical artifacts
        for any real beam (they are washed out by even tiny e-beam
        emittance and energy spread); using Gaussian tails avoids the
        spurious fringing they cause in angular / energy scans.

        RMS width (relative units, dE/E):
            sig_tot = sqrt(sig_natural^2 + sig_espread^2)
            sig_natural = 0.36 / (n * N_periods)  [Gaussian fit to sinc^2]
            sig_espread = 2 * sigma_E_beam / E_beam

        Peak amplitude is set so the integrated area equals that of the
        natural sinc^2 (= 1/(n*N)): peak = 1/(nN) / (sqrt(2*pi)*sig_tot).

        Accepts scalar or ND E_keV and E_n_keV; broadcasts.
        """
        E = np.asarray(E_keV, dtype=float)
        E_n = np.asarray(E_n_keV, dtype=float)
        safe = np.where(E_n > 0, E_n, np.nan)
        x = (E - safe) / safe
        sig_nat = 0.36 / (n * self.N_periods)
        sig_espread = 2.0 * self.energy_spread
        sig_tot = float(np.hypot(sig_nat, sig_espread))
        area_nat = 1.0 / (n * self.N_periods)
        peak_gauss = area_nat / (np.sqrt(2.0 * np.pi) * sig_tot)
        out = peak_gauss * np.exp(-0.5 * (x / sig_tot) ** 2)
        return np.where(np.isfinite(x), out, 0.0)

    def flux_density(self, E_keV, theta_h_mrad=0.0, theta_v_mrad=0.0):
        """d^2F/(dtheta_h dtheta_v) in ph/s/mrad^2/0.1%BW.

        Each harmonic contributes:
            d^2F/dOmega = peak0 * F_n(K) * G_n(theta) * L_n(E, E_n(theta))
        where
            peak0     = 1.744e14 * N^2 * E_ring^2 * I         [prefactor]
            F_n(K)    = planar-undulator amplitude factor (odd n only)
            G_n(theta)= exp(-theta^2 / (2 sigma_r'(n)^2))     [central-cone
                        angular envelope; approximates the Bessel-function
                        angular pattern of the harmonic]
            L_n(E,E_n)= Gaussian lineshape centred at the red-shifted
                        resonance energy E_n(theta)

        Without the angular envelope G_n, a wide-band integration over
        a small slit gives an unphysical top-hat: the amplitude is
        constant, only the resonance shifts, so every pixel inside the
        slit sees nearly the same integrated flux. Including G_n gives
        the correct Gaussian central-cone profile in angle.
        """
        E = np.atleast_1d(np.asarray(E_keV, dtype=float))
        th_h = float(np.asarray(theta_h_mrad).item()) if np.ndim(theta_h_mrad) == 0 else np.asarray(theta_h_mrad, dtype=float)
        th_v = float(np.asarray(theta_v_mrad).item()) if np.ndim(theta_v_mrad) == 0 else np.asarray(theta_v_mrad, dtype=float)
        theta = np.hypot(th_h, th_v) * 1e-3  # rad
        out = np.zeros_like(E)
        peak0 = 1.744e14 * self.N_periods ** 2 * self.E_GeV ** 2 * self.current_A
        for n in range(1, self.max_harmonic + 1):
            Fn = F_n_planar(n, self.K)
            if Fn <= 0:
                continue
            E_n = self._resonance_keV(n, theta=theta)
            # Angular envelope: central-cone Gaussian of half-width sigma_r'(n)
            sig_theta = (1.0 / self.gamma) * np.sqrt(
                (1.0 + self.K * self.K / 2.0) / (2.0 * n * self.N_periods))
            G_n = np.exp(-0.5 * (theta / sig_theta) ** 2)
            out = out + peak0 * Fn * G_n * self._harmonic_lineshape(E, E_n, n)
        return out if out.shape != () else float(out)

    def angular_flux(self, E_keV, theta_v_mrad=0.0):
        """dF/dtheta_h in ph/s/mrad/0.1%BW.

        Approximated by integrating the on-axis flux_density over
        theta_v across the central cone (Gaussian width). This is a
        first-order estimate; use `flux_through_slit()` for accurate
        aperture-integrated flux.
        """
        E = np.asarray(E_keV, dtype=float)
        # Use central cone width for n=1 as characteristic vertical spread
        sig_v = self.central_cone_sigma_mrad(1)  # mrad
        # Simpson over +/- 3 sigma
        n_pts = 21
        v_grid = np.linspace(-3 * sig_v, 3 * sig_v, n_pts)
        dv = v_grid[1] - v_grid[0]
        acc = np.zeros_like(E)
        for v in v_grid:
            acc = acc + self.flux_density(E, theta_h_mrad=0.0,
                                          theta_v_mrad=theta_v_mrad + v)
        return acc * dv

    # ---- central-cone integrated flux --------------------------------
    def central_cone_flux(self, E_keV):
        """Sum of central-cone integrated harmonic fluxes as a spectrum.

        Each harmonic contributes 1.431e14 * N * I * Q_n(K) with the
        sinc^2 lineshape around E_n. Returns ph/s/0.1%BW.
        """
        E = np.atleast_1d(np.asarray(E_keV, dtype=float))
        out = np.zeros_like(E)
        prefac = 1.431e14 * self.N_periods * self.current_A
        for n in range(1, self.max_harmonic + 1):
            Qn = Q_n_planar(n, self.K)
            if Qn <= 0:
                continue
            E_n = self._resonance_keV(n, theta=0.0)
            out = out + prefac * Qn * self._harmonic_lineshape(E, E_n, n)
        return out if out.shape != () else float(out)

    # ---- harmonic table ----------------------------------------------
    def harmonic_table(self):
        """List of (n, E_n_keV, F_n_peak_axis, F_n_cone_total) for odd n."""
        rows = []
        peak0 = 1.744e14 * self.N_periods ** 2 * self.E_GeV ** 2 * self.current_A
        cone0 = 1.431e14 * self.N_periods * self.current_A
        for n in range(1, self.max_harmonic + 1, 2):
            Fn = F_n_planar(n, self.K)
            Qn = Q_n_planar(n, self.K)
            rows.append((n, self._resonance_keV(n, 0.0),
                         peak0 * Fn, cone0 * Qn))
        return rows
