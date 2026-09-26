"""Compose a Source + Slit + FilterStack into a beamline spectrum."""
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from .sources import Source
from .slits import Slit
from .filters import FilterStack
from .logger import get_logger

_log = get_logger(__name__)


@dataclass
class ElectronBeam:
    """Storage-ring electron beam finite emittance.

    Contributes to the 2D beam profile at the observation plane by
    Gaussian blur:  sigma_blur = sqrt(sigma_size^2 + (sigma_div * D_plane)^2)

    Defaults are APS-U-like round-beam parameters.
    """
    sigma_x_um: float = 15.0     # horizontal source size (rms, um)
    sigma_y_um: float = 8.0      # vertical source size (rms, um)
    sigma_xp_urad: float = 3.0   # horizontal divergence (rms, urad)
    sigma_yp_urad: float = 1.5   # vertical divergence (rms, urad)

    def spot_at_plane_mm(self, D_plane_m: float):
        """(sigma_h, sigma_v) rms blur kernel size at the plane, in mm."""
        sh = np.hypot(self.sigma_x_um * 1e-3,
                       self.sigma_xp_urad * 1e-6 * D_plane_m * 1e3)
        sv = np.hypot(self.sigma_y_um * 1e-3,
                       self.sigma_yp_urad * 1e-6 * D_plane_m * 1e3)
        return sh, sv


@dataclass
class Beamline:
    """Compute the photon flux after slits + filters.

    All spectral quantities are per 0.1% relative bandwidth (the
    synchrotron convention). Divide by 1000 to get per-eV at any given
    energy for narrow bands (E * 0.001).

    `ebeam` sets the electron-beam emittance that blurs the 2D beam
    profile at the observation plane. Pass `ElectronBeam()` for a
    default APS-U-like ring, or None to model a zero-emittance point
    source.
    """
    source: Source
    slit: Slit = field(default_factory=Slit)
    filters: FilterStack = field(default_factory=FilterStack)
    n_theta: int = 15  # integration samples per slit axis
    ebeam: Optional[ElectronBeam] = None

    # ------------------------------------------------------------------
    def flux_at_slit(self, E_keV):
        """Photon flux transmitted by the slit (before filters).

        Returns ph/s/0.1%BW.

        For undulator sources with slit larger than the central cone the
        integrator underestimates the flux; in that case we clip to the
        central-cone total flux (a common practical bound).
        """
        E = np.atleast_1d(np.asarray(E_keV, dtype=float))
        F = self.source.flux_through_slit(
            E, self.slit.distance_m, self.slit.h_mm, self.slit.v_mm,
            self.slit.h_offset_mm, self.slit.v_offset_mm,
            n_theta=self.n_theta,
        )
        F = np.atleast_1d(np.asarray(F, dtype=float))
        # For undulators, also compute central-cone integrated flux and
        # take the lesser of (integrated slit, central-cone) when slit
        # covers > 2 sigma central-cone. This guards against the crude
        # angular envelope model overshooting.
        if hasattr(self.source, "central_cone_flux"):
            Fcone = np.atleast_1d(self.source.central_cone_flux(E))
            # If slit smaller than central cone, geometric factor scales down
            sig_h = self.source.central_cone_sigma_mrad(1)
            slit_h_half = 0.5 * self.slit.h_accept_mrad()
            slit_v_half = 0.5 * self.slit.v_accept_mrad()
            if slit_h_half >= 2 * sig_h and slit_v_half >= 2 * sig_h:
                F = np.minimum(F, Fcone)
        return F

    def transmission(self, E_keV):
        """Total filter-stack transmission (dimensionless, 0..1)."""
        return self.filters.transmission(E_keV)

    def flux(self, E_keV):
        """Final photon flux after slit + filters (ph/s/0.1%BW)."""
        return self.flux_at_slit(E_keV) * self.transmission(E_keV)

    # ------------------------------------------------------------------
    def spectrum(self, E_min_keV=1.0, E_max_keV=100.0, n=800, log=True):
        """Convenience: build (E, flux, transmission, flux_at_slit) arrays.

        `log=True` uses a log-spaced energy axis (recommended when the
        source spans several decades in energy).
        """
        if log:
            E = np.geomspace(E_min_keV, E_max_keV, n)
        else:
            E = np.linspace(E_min_keV, E_max_keV, n)
        F0 = self.flux_at_slit(E)
        T = self.transmission(E)
        return E, F0 * T, T, F0

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def beam_2d(self, plane_distance_m, x_mm, y_mm, E_keV,
                 integrate_band=False):
        """Photon flux distribution on a plane perpendicular to the beam.

        Parameters
        ----------
        plane_distance_m : distance from source to the plane (m).
            Must be >= slit distance; the slit shadow is applied by
            projecting each plane point back to the slit plane and
            gating.
        x_mm, y_mm : 1D arrays of horizontal / vertical coordinates on
            the plane (mm). Origin (0, 0) is on the beam axis.
        E_keV : scalar or 1D array of photon energies (keV).
        integrate_band : if True and E_keV is an array, integrate flux
            over the band (returns ph/s/mm^2). Otherwise returns
            ph/s/mm^2/0.1%BW per energy point:
              - E scalar          -> shape (ny, nx)
              - E array + no int  -> shape (nE, ny, nx)

        Returns
        -------
        img : ndarray as above.
        extent : (x_min, x_max, y_min, y_max) tuple in mm, for imshow.
        """
        D = float(plane_distance_m)
        if D <= 0:
            raise ValueError("plane_distance_m must be > 0")
        x = np.asarray(x_mm, dtype=float)
        y = np.asarray(y_mm, dtype=float)
        E = np.atleast_1d(np.asarray(E_keV, dtype=float))
        scalar_E = np.ndim(E_keV) == 0

        # Undulator band integration needs many energy samples: the
        # natural harmonic width is E_n / (n*N) ~ 30 eV for a typical
        # ID, so a sparse trapz misses harmonic peaks entirely and
        # gives a checkerboard-like image. Densify silently. Users
        # that pass more samples than the auto-min are honoured.
        if integrate_band and not scalar_E and E.size >= 2:
            if hasattr(self.source, "N_periods"):
                N_p = int(getattr(self.source, "N_periods", 1))
                max_n = int(getattr(self.source, "max_harmonic", 15))
                E_lo = float(E.min()); E_hi = float(E.max())
                band = E_hi - E_lo
                min_width_eV = max(E_lo, 1.0) / (max_n * max(N_p, 1)) * 1000.0
                step_eV = max(min_width_eV / 5.0, 2.0)
                n_min = int(np.clip(band * 1000.0 / step_eV, 200, 5000))
                if E.size < n_min:
                    _log.debug(
                        "beam_2d: densifying energy grid %d -> %d for "
                        "undulator band integration (natural width ~%.1f eV)",
                        E.size, n_min, min_width_eV)
                    E = np.linspace(E_lo, E_hi, n_min)
        _log.info("beam_2d: %s at %.2f m, grid %dx%d, %d E-pt%s%s",
                   self.source.__class__.__name__, D,
                   x.size, y.size, E.size,
                   ("s" if E.size != 1 else ""),
                   (" [band]" if integrate_band and not scalar_E else ""))

        # Angles seen from source (mrad)
        # theta[i,j] in mrad = x[j]/D * 1e-3 rad = x[j]/D (mm/m) mrad?
        # Actually: angle in rad = (x[mm]*1e-3)/D[m], so angle in mrad = x/D.
        th_h = x / D                        # mrad, shape (nx,)
        th_v = y / D                        # mrad, shape (ny,)

        # Slit gating: only applies when the observation plane is at or
        # past the slit. Upstream of the slit the beam hasn't been
        # clipped yet, so gate = 1 everywhere.
        D_slit = self.slit.distance_m
        if D >= D_slit:
            x_slit = np.outer(np.ones_like(th_v), th_h) * D_slit    # (ny, nx)
            y_slit = np.outer(th_v, np.ones_like(th_h)) * D_slit
            h_half = self.slit.h_mm * 0.5
            v_half = self.slit.v_mm * 0.5
            gate = (
                (np.abs(x_slit - self.slit.h_offset_mm) <= h_half) &
                (np.abs(y_slit - self.slit.v_offset_mm) <= v_half)
            ).astype(float)                                          # (ny, nx)
        else:
            gate = np.ones((y.size, x.size), dtype=float)

        # Flux density in ph/s/mrad^2/0.1%BW -> convert to ph/s/mm^2 at
        # the plane: 1 mrad^2 at distance D covers D^2 mm^2.
        # -> flux per mm^2 = flux_density / D^2  (mm-scale distances)
        # (Cross-check: 1 mrad*D_m = mm; area on plane = D^2 mm^2, so
        # dN/dA_mm2 = dN/dOmega_mrad2 / D_m^2.)
        inv_D2 = 1.0 / (D * D)

        # Filter transmission per energy
        T = np.atleast_1d(np.asarray(self.transmission(E), dtype=float))

        # Broadcast flux_density over the grid. We iterate over energies
        # to keep memory bounded (E can be large).
        img = np.zeros((E.size, y.size, x.size), dtype=float)
        for iE, e in enumerate(E):
            # Vectorise angles: build 2D (ny, nx) arrays
            TH_h = np.broadcast_to(th_h[None, :], (y.size, x.size))
            TH_v = np.broadcast_to(th_v[:, None], (y.size, x.size))
            # flux_density returns per-angle array with same shape when
            # E is scalar. Some source models loop internally on angles,
            # so we vectorise by calling once per E with 2D angles.
            fd = self.source.flux_density(
                np.array([e]),
                theta_h_mrad=TH_h,
                theta_v_mrad=TH_v,
            )
            # flux_density signatures differ slightly across sources;
            # coerce shape.
            fd = np.asarray(fd).reshape(y.size, x.size)
            img[iE] = fd * gate * inv_D2 * T[iE]

        extent = (float(x.min()), float(x.max()),
                   float(y.min()), float(y.max()))

        # Reduce to a single 2D map (band integral or single-E) before blurring
        if scalar_E:
            out2d = img[0]
        elif integrate_band:
            # dN/dE [ph/s/mm^2/keV] = ph/s/mm^2/0.1%BW / (E*0.001)
            dN_dE = img / (E[:, None, None] * 1e-3)
            out2d = np.trapz(dN_dE, E, axis=0)
        else:
            # Return the raw per-E stack (no blur applied)
            return img, extent

        # Apply electron-beam emittance blur at the observation plane
        if self.ebeam is not None:
            sh_mm, sv_mm = self.ebeam.spot_at_plane_mm(D)
            dx_mm = float(x[1] - x[0]) if x.size > 1 else 0.0
            dy_mm = float(y[1] - y[0]) if y.size > 1 else 0.0
            if dx_mm > 0 and dy_mm > 0:
                sig_h_px = sh_mm / dx_mm
                sig_v_px = sv_mm / dy_mm
                # Skip if kernel is sub-pixel (nothing to smear)
                if max(sig_h_px, sig_v_px) > 0.3:
                    try:
                        from scipy.ndimage import gaussian_filter
                        out2d = gaussian_filter(
                            out2d, sigma=(sig_v_px, sig_h_px),
                            mode="constant", cval=0.0)
                        _log.debug("emittance blur applied: sig_h=%.3f mm, "
                                    "sig_v=%.3f mm at %.1f m", sh_mm, sv_mm, D)
                    except ImportError:
                        _log.warning("scipy.ndimage not available; skipping "
                                     "electron-beam blur")
        return out2d, extent

    # ------------------------------------------------------------------
    def beam_2d_peak_energy(self, plane_distance_m, x_mm, y_mm,
                             E_min_keV=None, E_max_keV=None, n_E=120):
        """Peak-emission photon energy at each pixel [keV], for ANY source.

        For each pixel (x, y) with corresponding emission angles
        (theta_h, theta_v) = (x/D, y/D), evaluate `source.flux_density`
        across a log-spaced energy grid and take the argmax.

        - Bending magnet / wiggler: the peak of y^2 * [K_{2/3}^2 + ...]
          in Kim's angular distribution shifts to lower energy at
          larger |gamma*psi|.  At psi=0 the peak sits at about
          y = 0.83 * epsilon_c; at |gamma*psi| ~ 1 it drops noticeably.
        - Undulator: recovers the red-shifted resonance E_n(theta) of the
          dominant harmonic at each angle.

        `E_min_keV` and `E_max_keV` default to a reasonable range for
        the source (0.01..10 * critical energy for a BM/wiggler; 0.3 *
        E_1 .. max_harmonic * E_1 for an undulator).

        Returns (E_map, extent). Off-signal pixels (flux < 1e-6 of the
        max) and pixels outside the slit shadow (when the plane is at
        or past the slit) get NaN.
        """
        src = self.source
        D = float(plane_distance_m)
        x = np.asarray(x_mm, dtype=float)
        y = np.asarray(y_mm, dtype=float)
        TH_h = np.broadcast_to((x / D)[None, :], (y.size, x.size))
        TH_v = np.broadcast_to((y / D)[:, None], (y.size, x.size))
        theta = np.hypot(TH_h, TH_v) * 1e-3  # rad

        best_E = np.full((y.size, x.size), np.nan)
        best_A = np.zeros((y.size, x.size))

        if hasattr(src, "_resonance_keV"):
            # Undulator: report the dominant HARMONIC at each angle,
            # ranked by F_n(K) * G_n(theta). We deliberately do NOT
            # weight by the Gaussian peak amplitude 1/(nN*sqrt(2pi)*sig)
            # here: doing so would let the widest-bandwidth low-order
            # harmonic dominate every pixel (higher peak/0.1%BW density
            # is a bandwidth effect, not "which harmonic is emitting
            # into this pixel"). The physically intuitive picture used
            # in Kim's undulator radiation diagrams ranks harmonics by
            # their angular flux amplitude F_n * G_n, giving the
            # familiar concentric-ring structure.
            from .undulator import F_n_planar
            for n in range(1, getattr(src, "max_harmonic", 15) + 1):
                Fn = F_n_planar(n, src.K)
                if Fn <= 0:
                    continue
                E_n = src._resonance_keV(n, theta=theta)
                sig_theta = (1.0 / src.gamma) * np.sqrt(
                    (1.0 + src.K * src.K / 2.0) / (2.0 * n * src.N_periods))
                G_n = np.exp(-0.5 * (theta / sig_theta) ** 2)
                A = Fn * G_n
                take = A > best_A
                best_A = np.where(take, A, best_A)
                best_E = np.where(take, E_n, best_E)
        else:
            # BM / wiggler / anything else: sample flux_density(E, θ) on a
            # log-spaced E grid and take argmax per pixel. To avoid the
            # discrete-block artefact from grid quantisation, we then
            # refine each pixel's peak with a parabolic fit through the
            # three samples straddling the argmax — that gives a smooth
            # sub-grid E estimate.
            if E_min_keV is None:
                E_min = (max(src.epsilon_c_keV * 0.02, 0.05)
                          if hasattr(src, "epsilon_c_keV") else 0.5)
            else:
                E_min = float(E_min_keV)
            if E_max_keV is None:
                E_max = (src.epsilon_c_keV * 6.0
                          if hasattr(src, "epsilon_c_keV") else 100.0)
            else:
                E_max = float(E_max_keV)
            n_E = max(n_E, 200)
            E_grid = np.geomspace(E_min, E_max, n_E)
            log_E = np.log(E_grid)

            # Store the full stack so we can do parabolic refinement.
            fd_stack = np.zeros((n_E, y.size, x.size))
            for i, e in enumerate(E_grid):
                fd = src.flux_density(np.array([e]),
                                        theta_h_mrad=TH_h,
                                        theta_v_mrad=TH_v)
                fd_stack[i] = np.asarray(fd, dtype=float).reshape(y.size, x.size)
            argmax = np.argmax(fd_stack, axis=0)
            best_A = np.take_along_axis(fd_stack, argmax[None], axis=0)[0]

            # Parabolic refinement in log(E). For interior points, fit
            #   f(u) = a u^2 + b u + c  through (u_{i-1}, u_i, u_{i+1})
            # and take the vertex u_peak = u_i - 0.5 * (f_{i+1} - f_{i-1})
            #                                            / (f_{i+1} - 2 f_i + f_{i-1})
            im = np.clip(argmax - 1, 0, n_E - 1)
            ip = np.clip(argmax + 1, 0, n_E - 1)
            f0 = np.take_along_axis(fd_stack, im[None], axis=0)[0]
            f1 = best_A
            f2 = np.take_along_axis(fd_stack, ip[None], axis=0)[0]
            denom = f0 - 2.0 * f1 + f2
            # Guard: parabola only meaningful when concave-down (denom < 0)
            # and when argmax is an interior grid point.
            interior = (argmax > 0) & (argmax < n_E - 1) & (denom < 0)
            delta = np.where(interior, 0.5 * (f0 - f2) / denom, 0.0)
            # Clip |delta|<=1 grid step to avoid extrapolation outliers
            delta = np.clip(delta, -1.0, 1.0)
            u_peak = np.take(log_E, argmax) + delta * (log_E[1] - log_E[0])
            best_E = np.exp(u_peak)

        # NaN out pixels with negligible signal
        m = best_A.max()
        if m > 0:
            best_E = np.where(best_A > m * 1e-6, best_E, np.nan)

        # Slit shadow (only if plane is at or past the slit)
        D_slit = self.slit.distance_m
        if D >= D_slit:
            x_slit = TH_h * D_slit
            y_slit = TH_v * D_slit
            gate = ((np.abs(x_slit - self.slit.h_offset_mm) <= self.slit.h_mm * 0.5) &
                    (np.abs(y_slit - self.slit.v_offset_mm) <= self.slit.v_mm * 0.5))
            best_E = np.where(gate, best_E, np.nan)

        extent = (float(x.min()), float(x.max()),
                   float(y.min()), float(y.max()))
        return best_E, extent

    def power_W(self, E_min_keV=0.1, E_max_keV=200.0, n=2000):
        """Integrated x-ray power through the beamline (Watts).

        P = integral( E * flux * dE / (E * 0.001) )    [ph/s * eV * 1e-3]
          = integral( flux * dE / 0.001 )              [flux per 0.1%BW]
        Wait: flux per 0.1%BW at energy E corresponds to
              dN/dE [ph/s/eV] = flux(E) / (E * 0.001)
        Power P [W] = integral( E[eV] * dN/dE dE ) * 1.602e-19
                    = integral( flux(E) / 0.001 * dE ) * 1.602e-19
                    = 1.602e-16 * integral(flux(E) dE_keV)  (since dE_keV=dE_eV/1000)
        """
        E = np.geomspace(E_min_keV, E_max_keV, n)
        F = self.flux(E)  # ph/s/0.1%BW
        # dN/dE [ph/s/keV] = F / (E * 0.001)
        # Power density in keV/s per keV = E * dN/dE = F / 0.001
        # Integrated power in keV/s = integral(F/0.001) dE_keV
        integrand = F / 0.001  # keV/s per keV
        P_keV_s = np.trapz(integrand, E)
        # 1 keV = 1.602176e-16 J
        return P_keV_s * 1.602176e-16
