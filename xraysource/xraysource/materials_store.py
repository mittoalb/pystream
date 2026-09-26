"""Persistent user-defined materials.

Stored as JSON at ~/.xraysource/materials.json:

    {
      "materials": {
        "my_alloy": {"formula": "Fe0.7Cr0.18Ni0.12", "density_g_cm3": 8.0,
                     "note": "SS316-like"},
        ...
      }
    }

`filters.py` consults the store first when resolving a material name, so
users can override built-in aliases too (e.g. bump the tabulated density
of "kapton" for a particular vendor).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from .logger import get_logger

_log = get_logger(__name__)


def store_path() -> Path:
    """Location of the JSON file. Honours $XRAYSOURCE_MATERIALS if set."""
    env = os.environ.get("XRAYSOURCE_MATERIALS")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".xraysource" / "materials.json"


def load() -> Dict[str, dict]:
    """Load {name: {formula, density_g_cm3, note}}. Empty dict if missing."""
    p = store_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        mats = data.get("materials", {})
        if not isinstance(mats, dict):
            return {}
        # Normalise keys to lowercase for lookup, keep original in "display"
        out = {}
        for k, v in mats.items():
            if not isinstance(v, dict):
                continue
            out[str(k).strip()] = {
                "formula": str(v.get("formula", k)).strip(),
                "density_g_cm3": float(v.get("density_g_cm3", 0.0)) or None,
                "note": str(v.get("note", "")).strip(),
            }
        return out
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def save(materials: Dict[str, dict]) -> None:
    """Overwrite the store with the given dict."""
    p = store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"materials": materials}
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(p)
    _log.info("Saved %d custom material(s) to %s", len(materials), p)


def add(name: str, formula: str, density_g_cm3: float,
        note: str = "") -> Dict[str, dict]:
    """Add or replace one entry; returns the updated store dict."""
    mats = load()
    mats[str(name).strip()] = {
        "formula": str(formula).strip(),
        "density_g_cm3": float(density_g_cm3),
        "note": str(note).strip(),
    }
    save(mats)
    return mats


def remove(name: str) -> Dict[str, dict]:
    mats = load()
    mats.pop(str(name).strip(), None)
    save(mats)
    return mats


def lookup(name: str) -> Optional[dict]:
    """Case-insensitive lookup; returns None if not present."""
    mats = load()
    lower_map = {k.lower(): (k, v) for k, v in mats.items()}
    hit = lower_map.get(name.strip().lower())
    return hit[1] if hit else None
