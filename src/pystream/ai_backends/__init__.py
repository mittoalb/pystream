"""
AI backends for pystream — heavyweight ML tools invoked from a separate
conda environment via subprocess.

Motivation: pystream itself should stay light (PyQt5, numpy, scipy,
pyepics — that's it). Torch, transformers, SAM2, etc. are ~2 GB installs
that would double the pystream image size and slow every import. Instead
we call them out-of-process:

    ┌── pystream env (light) ────────┐   ┌── lvp / cor_ml env (heavy) ─┐
    │  particle_align.py             │   │                             │
    │    click (x, y)                │   │                             │
    │    ↓                           │   │                             │
    │  SAM2Backend.segment()         │──▶│  _sam2_worker.py            │
    │    writes image + prompt to    │   │    torch + sam2 + weights   │
    │    tempfiles, runs subprocess  │   │    predict → write mask.npy │
    │    ↓ reads mask.npy back       │◀──│    exit                     │
    │  mask (bool 2D array)          │   │                             │
    └────────────────────────────────┘   └─────────────────────────────┘

Backends live one per file: `<name>_backend.py` exposes a `<Name>Backend`
class with `.available()` and a task-specific method. Workers live as
`_<name>_worker.py` — plain scripts run in the heavy env, no pystream
imports allowed (they must import cleanly under an env that doesn't
have pystream installed).

Add a new backend:
  1. Drop `<foo>_backend.py` + `_<foo>_worker.py` in this folder.
  2. Register the env path in `~/.pystream/ai_backends.json`:
        {"foo": {"python": "/path/to/env/bin/python", ...}}
  3. In your plugin: `from ..ai_backends.foo_backend import FooBackend`.
"""

from .config import load_backend_config, backend_config_path
from .sam2_backend import SAM2Backend

__all__ = ['SAM2Backend', 'load_backend_config', 'backend_config_path']
