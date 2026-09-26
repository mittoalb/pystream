"""Special functions for synchrotron radiation formulas.

Implements the standard integrals over modified Bessel functions
(K_{1/3}, K_{2/3}, K_{5/3}) used in Kim's synchrotron radiation
formulas. Vectorised for arrays of arbitrary shape.
"""
import numpy as np
from scipy import integrate, special


def _quad_vec(func, a_arr, b=np.inf, limit=200):
    """Integrate `func(x)` from a_arr[i] to b for each element of a_arr."""
    a_arr = np.atleast_1d(np.asarray(a_arr, dtype=float))
    out = np.empty_like(a_arr)
    for i, a in enumerate(a_arr.ravel()):
        if not np.isfinite(a) or a <= 0.0:
            out.flat[i] = np.nan
            continue
        val, _ = integrate.quad(func, a, b, limit=limit)
        out.flat[i] = val
    return out.reshape(a_arr.shape)


def G1(y):
    """G1(y) = y * integral_y^inf K_{5/3}(x) dx.

    Horizontal-angle-integrated bending magnet spectrum shape.
    """
    y = np.asarray(y, dtype=float)
    orig_shape = y.shape
    y_flat = np.atleast_1d(y).ravel()
    out = np.empty_like(y_flat)
    for i, yi in enumerate(y_flat):
        if yi <= 0 or not np.isfinite(yi):
            out[i] = 0.0
        elif yi < 1e-4:
            # Small-y asymptotic: G1(y) ~ 2.1495 * y^(1/3)
            out[i] = 2.1495 * yi ** (1.0 / 3.0)
        elif yi > 60.0:
            # Large-y asymptotic: G1(y) ~ sqrt(pi/2) * y^(1/2) * exp(-y)
            out[i] = np.sqrt(np.pi / 2.0) * np.sqrt(yi) * np.exp(-yi)
        else:
            val, _ = integrate.quad(lambda x: special.kv(5.0/3.0, x),
                                     yi, np.inf, limit=200)
            out[i] = yi * val
    return out.reshape(orig_shape) if orig_shape else float(out[0])


def H2(y):
    """H2(y) = y^2 * K_{2/3}(y/2)^2  (on-axis BM angular flux shape)."""
    y = np.asarray(y, dtype=float)
    orig_shape = y.shape
    y_flat = np.atleast_1d(y).astype(float)
    out = np.zeros_like(y_flat)
    m = (y_flat > 0) & np.isfinite(y_flat)
    out[m] = y_flat[m]**2 * special.kv(2.0/3.0, y_flat[m] / 2.0)**2
    if orig_shape == ():
        return float(out[0])
    return out.reshape(orig_shape)


def F_K13(xi):
    """K_{1/3}(xi) with safe handling of xi<=0."""
    xi = np.asarray(xi, dtype=float)
    out = np.zeros_like(xi)
    m = (xi > 0) & np.isfinite(xi)
    out[m] = special.kv(1.0/3.0, xi[m])
    return out


def F_K23(xi):
    """K_{2/3}(xi) with safe handling of xi<=0."""
    xi = np.asarray(xi, dtype=float)
    out = np.zeros_like(xi)
    m = (xi > 0) & np.isfinite(xi)
    out[m] = special.kv(2.0/3.0, xi[m])
    return out


def bending_magnet_S_functions(y, gamma_psi):
    """S_sigma and S_pi angular-distribution factors for a bending magnet.

    d^2 F/(d theta d psi) = (const) * gamma^2 * y^2 * (1 + X^2)^2 *
                            [K_{2/3}^2(xi) + X^2/(1+X^2) * K_{1/3}^2(xi)]
    with X = gamma * psi, xi = (y/2) * (1 + X^2)^(3/2).

    Returns (S_sigma, S_pi) with
      S_sigma = (1+X^2)^2 * K_{2/3}^2(xi)
      S_pi    = (1+X^2)^2 * X^2/(1+X^2) * K_{1/3}^2(xi)
    """
    X = np.asarray(gamma_psi, dtype=float)
    y = np.asarray(y, dtype=float)
    onepX2 = 1.0 + X * X
    xi = (y / 2.0) * onepX2 ** 1.5
    K23 = F_K23(xi)
    K13 = F_K13(xi)
    S_sigma = onepX2 * onepX2 * K23 * K23
    S_pi    = onepX2 * X * X * K13 * K13
    return S_sigma, S_pi
