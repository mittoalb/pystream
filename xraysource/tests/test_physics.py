"""Sanity checks on the physics formulas.

These tests validate the source spectra against textbook reference
values (X-ray Data Booklet, Kim's "Characteristics of Synchrotron
Radiation"). Tolerances are set to catch order-of-magnitude regressions
and formula sign errors.
"""
import math
import numpy as np
import pytest

from xraysource import (
    BendingMagnet, Wiggler, Undulator,
    Filter, FilterStack, Slit, Beamline,
    critical_energy_keV, K_from_B, gamma_from_energy,
)
from xraysource._specfuncs import G1, H2
from xraysource.undulator import F_n_planar, Q_n_planar


# ------------------------------------------------------------------
# Special functions
# ------------------------------------------------------------------
def test_G1_reference_values():
    # Tabulated values from Wiedemann, "Synchrotron Radiation" (2003), App. A.1:
    #   G1(0.1)  ~ 0.818
    #   G1(1.0)  ~ 0.6514
    #   G1(10.0) ~ 1.92e-4
    assert G1(1.0) == pytest.approx(0.6514, rel=1e-3)
    assert G1(0.1) == pytest.approx(0.818, rel=5e-3)
    assert G1(10.0) == pytest.approx(1.92e-4, rel=1e-1)


def test_H2_reference_values():
    # H2(1) = K_{2/3}(1/2)^2. K_{2/3}(0.5) ~ 1.209, so H2(1) ~ 1.46
    from scipy.special import kv
    assert H2(1.0) == pytest.approx(kv(2.0/3.0, 0.5)**2, rel=1e-6)


# ------------------------------------------------------------------
# Bending magnet
# ------------------------------------------------------------------
def test_bm_critical_energy():
    # APS BM: E=7 GeV, B=0.6 T => e_c ~ 19.55 keV
    assert critical_energy_keV(7.0, 0.6) == pytest.approx(19.55, rel=1e-3)


def test_bm_gamma():
    # gamma = E/m_e c^2, at 7 GeV ~ 13699
    assert gamma_from_energy(7.0) == pytest.approx(13699.0, rel=1e-3)


def test_bm_flux_at_critical():
    # Angular flux at e_c: 2.457e13 * E * I * G1(1) = 2.457e13*7*0.1*0.6514
    bm = BendingMagnet(E_GeV=7.0, current_A=0.1, B_T=0.6)
    F = bm.angular_flux(bm.epsilon_c_keV)
    expected = 2.457e13 * 7.0 * 0.1 * 0.6514
    assert F == pytest.approx(expected, rel=1e-2)


# ------------------------------------------------------------------
# Wiggler
# ------------------------------------------------------------------
def test_wiggler_K_and_B_consistent():
    # K = 0.09337 * B[T] * lambda_u[mm]
    w = Wiggler(E_GeV=7.0, current_A=0.1, period_mm=85.0, N_periods=28, K=15.0)
    assert w.K == pytest.approx(0.09337 * w.B_T * 85.0, rel=1e-6)
    # Round-trip via B
    w2 = Wiggler(E_GeV=7.0, current_A=0.1, period_mm=85.0, N_periods=28, B_T=w.B_T)
    assert w2.K == pytest.approx(15.0, rel=1e-6)


def test_wiggler_is_2N_times_bm():
    # Angular flux of wiggler = 2N * angular flux of BM at same B, E, I.
    E_GeV = 7.0; I = 0.1; N = 28
    B = 1.5
    w = Wiggler(E_GeV=E_GeV, current_A=I, period_mm=85.0, N_periods=N, B_T=B)
    bm = BendingMagnet(E_GeV=E_GeV, current_A=I, B_T=B)
    for e in (5.0, w.epsilon_c_keV, 100.0):
        ratio = w.angular_flux(e) / bm.angular_flux(e)
        assert ratio == pytest.approx(2 * N, rel=1e-6)


# ------------------------------------------------------------------
# Undulator
# ------------------------------------------------------------------
def test_undulator_resonance():
    # E_1[keV] = 0.9496 * E^2 / (lambda_u[cm] * (1+K^2/2))
    und = Undulator(E_GeV=7.0, current_A=0.2, period_mm=33.0, N_periods=72, K=2.5)
    expected = 0.9496 * 49.0 / (3.3 * (1 + 2.5**2 / 2))
    assert und.E1_keV == pytest.approx(expected, rel=1e-3)


def test_undulator_even_harmonics_zero_on_axis():
    for n in (2, 4, 6, 8, 10):
        assert F_n_planar(n, 2.0) == 0.0
        assert Q_n_planar(n, 2.0) == 0.0


def test_undulator_F_n_positive_odd():
    for n in (1, 3, 5, 7, 9):
        assert F_n_planar(n, 2.0) > 0
        assert F_n_planar(n, 2.5) > 0


def test_undulator_offaxis_redshift():
    # Off-axis red-shift: E_n(theta) < E_n(0)
    und = Undulator(E_GeV=7.0, current_A=0.2, period_mm=33.0, N_periods=72, K=2.5)
    E_axis = und._resonance_keV(1, 0.0)
    E_off = und._resonance_keV(1, theta=1e-4)  # 0.1 mrad
    assert E_off < E_axis


# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------
def test_filter_transmission_monotone_thickness():
    for E in (5.0, 15.0, 40.0):
        T1 = Filter("Be", 100.0).transmission(E)
        T2 = Filter("Be", 500.0).transmission(E)
        T3 = Filter("Be", 2000.0).transmission(E)
        assert T3 < T2 < T1 <= 1.0


def test_filter_Cu_K_edge_jump():
    # Cu K-edge at 8.98 keV: sharp attenuation jump
    cu = Filter("Cu", 50.0)
    T_below = cu.transmission(8.9)
    T_above = cu.transmission(9.1)
    assert T_above < T_below < 1.0
    # Below-edge / above-edge ratio is large (order 1e6+ for 50 um Cu)
    assert T_below / T_above > 1e4


def test_filter_stack_product():
    fs = FilterStack()
    a = fs.add("Be", 500.0)
    b = fs.add("Al", 100.0)
    E = np.array([10.0, 30.0])
    T = fs.transmission(E)
    T_ref = a.transmission(E) * b.transmission(E)
    assert np.allclose(T, T_ref)


def test_filter_disabled():
    f = Filter("Al", 1000.0, enabled=False)
    assert f.transmission(20.0) == 1.0


def test_filter_alias_diamond():
    # "diamond" -> pure C with rho=3.515
    d = Filter("diamond", 100.0)
    assert d.density_g_cm3 == pytest.approx(3.515, rel=1e-3)


# ------------------------------------------------------------------
# Beamline
# ------------------------------------------------------------------
def test_beamline_flux_matches_manual():
    bm = BendingMagnet(E_GeV=7.0, current_A=0.1, B_T=0.6)
    slit = Slit(distance_m=25.0, h_mm=1.0, v_mm=1.0)
    stack = FilterStack(); stack.add("Be", 500.0)
    bl = Beamline(source=bm, slit=slit, filters=stack, n_theta=9)
    E = np.array([10.0, 20.0])
    F_bl = bl.flux(E)
    # Manual: flux through slit * transmission
    Ff = bm.flux_through_slit(E, 25.0, 1.0, 1.0, n_theta=9)
    T = stack.transmission(E)
    assert np.allclose(F_bl, Ff * T, rtol=1e-6)


def test_power_positive():
    und = Undulator(E_GeV=7.0, current_A=0.2, period_mm=33.0, N_periods=72, K=2.5)
    slit = Slit(distance_m=30.0, h_mm=1.0, v_mm=1.0)
    stack = FilterStack(); stack.add("Be", 500.0)
    bl = Beamline(source=und, slit=slit, filters=stack, n_theta=9)
    P = bl.power_W(1.0, 60.0, n=400)
    assert P > 0
