"""
AI backend configuration.

`~/.pystream/ai_backends.json` maps backend name → invocation details.
Missing file / missing entry → backend reports itself as unavailable.

Format:
    {
        "sam2": {
            "python":      "/home/beams/AMITTONE/miniconda3/envs/lvp/bin/python",
            "worker":      "auto",              // "auto" = bundled _sam2_worker.py
            "model_type":  "sam2_hiera_small",  // or _tiny / _base_plus / _large
            "device":      "cpu",               // "cpu" / "cuda" / "cuda:0"
            "checkpoint":  null,                // null → sam2 default (may need HF download)
            "timeout_s":   120
        }
    }
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


PYSTREAM_HOME = os.path.expanduser('~/.pystream')
BACKENDS_FILE = os.path.join(PYSTREAM_HOME, 'ai_backends.json')


def backend_config_path() -> str:
    return BACKENDS_FILE


def load_backend_config() -> Dict[str, Any]:
    """Return the whole config dict, or {} if the file is missing or unreadable."""
    try:
        with open(BACKENDS_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def get_backend(name: str) -> Optional[Dict[str, Any]]:
    """Return the config dict for `name`, or None if missing/incomplete."""
    entry = load_backend_config().get(name)
    if isinstance(entry, dict) and entry.get('python'):
        return entry
    return None


def write_example_config() -> str:
    """Create an example `~/.pystream/ai_backends.json` with placeholder
    values so the user has something to edit. Won't overwrite an
    existing file. Returns the path written."""
    if os.path.exists(BACKENDS_FILE):
        return BACKENDS_FILE
    os.makedirs(PYSTREAM_HOME, exist_ok=True)
    example = {
        "_comment": ("Config for pystream AI backends. Each entry names "
                     "a conda env whose python has the required packages "
                     "installed. `worker: auto` means use the bundled "
                     "worker script from pystream/ai_backends/."),
        "sam2": {
            "python":     "/path/to/env/bin/python",
            "worker":     "auto",
            "model_type": "sam2_hiera_small",
            "device":     "cpu",
            "checkpoint": None,
            "timeout_s":  120
        }
    }
    with open(BACKENDS_FILE, 'w') as f:
        json.dump(example, f, indent=2)
    return BACKENDS_FILE
