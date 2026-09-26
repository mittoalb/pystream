"""Filter transmission via xraylib.

A `Filter` is one slab: material name or compound formula, thickness (m),
optional density override (g/cm^3). The transmission is
    T(E) = exp(-mu(E) * rho * t)
where mu(E) is the mass attenuation coefficient (cm^2/g), rho is the
mass density (g/cm^3) and t is the thickness (cm).

A `FilterStack` is a list of Filters; transmission multiplies.

Common materials are known to xraylib as compounds ("Be", "Al", "Cu",
"Si", "SiO2", "Kapton", "H2O", ...). Pure elements can also be given by
symbol (e.g. "Fe") or Z number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Union

import numpy as np
import xraylib

from . import materials_store
from .logger import get_logger

_log = get_logger(__name__)


# Densities (g/cm^3) for common non-elemental materials that xraylib
# does not know about. xraylib's `GetCompoundDataNISTByName` covers many
# NIST materials; we fall back to this small table if the name is not
# found either as an element or a NIST compound.
DENSITY_TABLE = {
    "kapton": 1.42,
    "polyimide": 1.42,
    "mylar": 1.40,
    "pet": 1.38,
    "diamond": 3.515,
    "cvd_diamond": 3.515,
    "glassy_carbon": 1.42,
    "graphite": 2.267,
    "sapphire": 3.98,
    "quartz": 2.203,
    "air": 1.204e-3,
    "water": 1.000,
    "pmma": 1.18,
    "polycarbonate": 1.20,
    "polyethylene": 0.94,
    "beryllium": 1.848,
    "aluminum": 2.699,
    "aluminium": 2.699,
    "silicon": 2.329,
    "copper": 8.96,
    "iron": 7.874,
    "nickel": 8.908,
    "titanium": 4.506,
    "molybdenum": 10.28,
    "silver": 10.49,
    "gold": 19.30,
    "lead": 11.34,
    "tungsten": 19.25,
    "tantalum": 16.65,
    "platinum": 21.45,
}

# Chemical formulas for common trade names / aliases that xraylib does
# not parse directly.
FORMULA_ALIASES = {
    "kapton": "C22H10N2O5",
    "polyimide": "C22H10N2O5",
    "mylar": "C10H8O4",
    "pet": "C10H8O4",
    "diamond": "C",
    "cvd_diamond": "C",
    "glassy_carbon": "C",
    "graphite": "C",
    "sapphire": "Al2O3",
    "quartz": "SiO2",
    "air": "N1.562O0.42Ar0.00934C0.00033",  # approximate
    "water": "H2O",
    "pmma": "C5H8O2",
    "polycarbonate": "C16H14O3",
    "polyethylene": "C2H4",
    "beryllium": "Be",
    "aluminum": "Al", "aluminium": "Al",
    "silicon": "Si",
    "copper": "Cu",
    "iron": "Fe",
    "nickel": "Ni",
    "titanium": "Ti",
    "molybdenum": "Mo",
    "silver": "Ag",
    "gold": "Au",
    "lead": "Pb",
    "tungsten": "W",
    "tantalum": "Ta",
    "platinum": "Pt",
}


def _lookup_compound(name: str):
    """Return xraylib CompoundData for `name`, trying several strategies.

    Order:
      0. User's custom-materials store (~/.xraysource/materials.json) —
         overrides everything else, so users can shadow built-in aliases.
      1. Built-in alias table -> formula -> xraylib.CompoundParser
      2. Element symbol -> single-element pseudo-compound
      3. xraylib.CompoundParser directly (formulas like "SiO2")
      4. NIST compound database by name
    """
    key = name.strip()
    lower = key.lower()

    # 0. User store
    user_entry = materials_store.lookup(key)
    if user_entry:
        try:
            cd = xraylib.CompoundParser(user_entry["formula"])
            # Attach the user-declared density so `_density` can find it
            if isinstance(cd, dict):
                cd["_user_density"] = user_entry.get("density_g_cm3")
            return cd
        except Exception:
            pass

    # 1. Alias -> formula
    formula = FORMULA_ALIASES.get(lower, key)

    # 2. Element symbol
    try:
        Z = xraylib.SymbolToAtomicNumber(formula)
        if Z > 0:
            return {
                "nElements": 1,
                "Elements": [Z],
                "massFractions": [1.0],
                "molarMass": xraylib.AtomicWeight(Z),
            }
    except (ValueError, RuntimeError, Exception):
        pass

    # 3. Formula parser
    try:
        cd = xraylib.CompoundParser(formula)
        return cd
    except (ValueError, RuntimeError, Exception):
        pass

    # 4. NIST database
    try:
        cd = xraylib.GetCompoundDataNISTByName(key)
        return cd
    except (ValueError, RuntimeError, Exception):
        pass

    raise KeyError(f"Cannot resolve material {name!r} via xraylib")


def _density(name: str, cd) -> float:
    """Best-effort density lookup (g/cm^3)."""
    # 0. User store first
    user_entry = materials_store.lookup(name)
    if user_entry and user_entry.get("density_g_cm3"):
        return float(user_entry["density_g_cm3"])
    lower = name.strip().lower()
    if lower in DENSITY_TABLE:
        return DENSITY_TABLE[lower]
    if isinstance(cd, dict):
        # Custom compound with attached user density
        if cd.get("_user_density"):
            return float(cd["_user_density"])
        # NIST record — has "density" key
        d = cd.get("density", None)
        if d:
            return float(d)
        # Single element pseudo-compound
        if cd.get("nElements") == 1:
            Z = cd["Elements"][0]
            try:
                return xraylib.ElementDensity(Z)
            except Exception:
                pass
    # Try element density
    try:
        Z = xraylib.SymbolToAtomicNumber(name)
        if Z > 0:
            return xraylib.ElementDensity(Z)
    except Exception:
        pass
    raise KeyError(f"Density unknown for {name!r}; pass density_g_cm3 explicitly")


def mass_atten_cm2_g(material: str, E_keV):
    """Total mass attenuation coefficient mu/rho (cm^2/g) at E_keV.

    Uses xraylib.CS_Total_CP for compounds, CS_Total for elements.
    """
    cd = _lookup_compound(material)
    E = np.atleast_1d(np.asarray(E_keV, dtype=float))
    out = np.empty_like(E)

    # Prefer the compound-parser path for uniformity. When cd is not a
    # dict-like structure with element decomposition, fall back to
    # CS_Total_CP using either the user formula or the raw name.
    if isinstance(cd, dict) and cd.get("nElements", 0) >= 1:
        Zs = cd["Elements"]
        wts = cd["massFractions"]
        for i, ei in enumerate(E):
            mu = 0.0
            for Z, w in zip(Zs, wts):
                mu += w * xraylib.CS_Total(int(Z), float(ei))
            out[i] = mu
    else:
        formula = material
        user_entry = materials_store.lookup(material)
        if user_entry:
            formula = user_entry.get("formula", material)
        for i, ei in enumerate(E):
            out[i] = xraylib.CS_Total_CP(formula, float(ei))

    if np.ndim(E_keV) == 0:
        return float(out[0])
    return out


@dataclass
class Filter:
    """A single filter slab.

    Parameters
    ----------
    material : element symbol, chemical formula, or common material name
    thickness_um : slab thickness in micrometres
    density_g_cm3 : optional override of the tabulated density
    enabled : if False the filter contributes T=1 (used by the GUI)
    """
    material: str
    thickness_um: float
    density_g_cm3: Optional[float] = None
    enabled: bool = True

    def __post_init__(self):
        # Resolve density immediately so we fail fast on bad names
        cd = _lookup_compound(self.material)
        if self.density_g_cm3 is None:
            self.density_g_cm3 = _density(self.material, cd)
        self._compound = cd
        _log.debug("Filter resolved: %s (%.1f um, rho=%.3f g/cm^3, %s)",
                    self.material, self.thickness_um, self.density_g_cm3,
                    "on" if self.enabled else "off")

    def thickness_cm(self) -> float:
        return self.thickness_um * 1e-4

    def transmission(self, E_keV):
        if not self.enabled:
            E = np.asarray(E_keV, dtype=float)
            return np.ones_like(E) if E.ndim else 1.0
        mu = mass_atten_cm2_g(self.material, E_keV)
        return np.exp(-mu * self.density_g_cm3 * self.thickness_cm())

    def absorbed_fraction(self, E_keV):
        return 1.0 - self.transmission(E_keV)

    def __repr__(self):
        state = "" if self.enabled else " (disabled)"
        return (f"Filter({self.material}, {self.thickness_um} um, "
                f"rho={self.density_g_cm3:.3f} g/cm^3){state}")


@dataclass
class FilterStack:
    """Ordered list of Filters. Total transmission is the product."""
    filters: List[Filter] = field(default_factory=list)

    def add(self, material, thickness_um, density_g_cm3=None, enabled=True):
        f = Filter(material, thickness_um, density_g_cm3, enabled)
        self.filters.append(f)
        return f

    def clear(self):
        self.filters = []

    def transmission(self, E_keV):
        E = np.asarray(E_keV, dtype=float)
        T = np.ones_like(E) if E.ndim else 1.0
        for f in self.filters:
            T = T * f.transmission(E_keV)
        return T

    def __iter__(self):
        return iter(self.filters)

    def __len__(self):
        return len(self.filters)
