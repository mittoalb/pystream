"""
Pystream-side wrapper for SAM 2 — reads the config, marshals the
image + click into a tempfile, runs `_sam2_worker.py` in the configured
heavy-env python, reads the mask back.

Every plugin that wants SAM should just:

    from ..ai_backends.sam2_backend import SAM2Backend
    sam = SAM2Backend()
    if sam.available():
        mask = sam.segment(image, click_x, click_y)   # -> bool ndarray or None
    else:
        # fall back to your classical segmentation
        ...
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Optional

import numpy as np

from .config import get_backend


# ── Auto-discovery: envs and checkpoints we're likely to find on this
# beamline machine. Config JSON always wins; these are just fallbacks
# so the user doesn't have to hand-edit paths for the common case.

_CANDIDATE_PYTHONS = [
    "/home/beams/AMITTONE/miniconda3/envs/lvp/bin/python",
    "/home/beams0/AMITTONE/miniconda3/envs/lvp/bin/python",
    "/home/beams/AMITTONE/miniconda3/envs/cor_ml/bin/python",
    "/home/beams/AMITTONE/miniconda3/envs/tomo-ml/bin/python",
]

# The model_type → checkpoint-filename mapping SAM2 uses.
_CKPT_FILENAMES = {
    "sam2_hiera_tiny":      "sam2_hiera_tiny.pt",
    "sam2_hiera_small":     "sam2_hiera_small.pt",
    "sam2_hiera_base_plus": "sam2_hiera_base_plus.pt",
    "sam2_hiera_large":     "sam2_hiera_large.pt",
}

# Common places SAM2 or torch would cache weights.
_CANDIDATE_CKPT_DIRS = [
    os.path.expanduser("~/.cache/torch/hub/checkpoints"),
    os.path.expanduser("~/.cache/huggingface/hub"),
    os.path.expanduser("~/.pystream/models"),
    "/home/beams/AMITTONE/models/sam2",
    "/home/beams0/AMITTONE/Software/lvp/models",
    "/home/beams0/AMITTONE/Software/lvp/checkpoints",
]


def _auto_detect_python() -> Optional[str]:
    """Return the first _CANDIDATE_PYTHONS entry that exists AND whose
    site-packages contains a sam2/ folder."""
    for py in _CANDIDATE_PYTHONS:
        if not (os.path.isfile(py) and os.access(py, os.X_OK)):
            continue
        # Cheap check: sam2 is right next to python's site-packages.
        env_root = os.path.dirname(os.path.dirname(py))
        # Look under env_root/lib/pythonX.Y/site-packages/sam2
        for d in (os.path.join(env_root, "lib")).split(':'):
            if not os.path.isdir(d):
                continue
            for py_ver in sorted(os.listdir(d)):
                sp = os.path.join(d, py_ver, "site-packages", "sam2")
                if os.path.isdir(sp):
                    return py
    return None


def _auto_detect_checkpoint(model_type: str) -> Optional[str]:
    """Find a checkpoint file matching model_type in any known cache dir."""
    fname = _CKPT_FILENAMES.get(model_type)
    if not fname:
        return None
    for d in _CANDIDATE_CKPT_DIRS:
        if not os.path.isdir(d):
            continue
        # First: direct file at the top level of the dir.
        direct = os.path.join(d, fname)
        if os.path.isfile(direct):
            return direct
        # Then: walk one level deep — for HF-style hierarchies.
        try:
            for entry in os.listdir(d):
                sub = os.path.join(d, entry, fname)
                if os.path.isfile(sub):
                    return sub
        except OSError:
            pass
    return None


def _hf_download_url(model_type: str) -> str:
    fname = _CKPT_FILENAMES.get(model_type, "sam2_hiera_small.pt")
    return (f"https://dl.fbaipublicfiles.com/segment_anything_2/072824/{fname}")


class SAM2Backend:
    NAME = "sam2"

    def __init__(self):
        # Start from the JSON config (may be empty / missing).
        cfg = dict(get_backend(self.NAME) or {})

        # If the config's python path is missing OR points to a
        # non-existent file (e.g. the placeholder in the example
        # config), fall through to auto-detect. This means a
        # user-scaffolded ai_backends.json without a real python
        # path doesn't have to be edited when the standard lvp env
        # exists.
        cfg_py = cfg.get('python', '')
        if not (cfg_py and os.path.isfile(cfg_py) and os.access(cfg_py, os.X_OK)):
            auto_py = _auto_detect_python()
            if auto_py:
                cfg['python'] = auto_py
            elif cfg_py:
                cfg['python'] = cfg_py    # keep for a specific error message

        cfg.setdefault('model_type', 'sam2_hiera_small')
        cfg.setdefault('device',     'cpu')
        cfg.setdefault('timeout_s',  120)
        cfg.setdefault('worker',     'auto')
        if not cfg.get('checkpoint'):
            auto_ck = _auto_detect_checkpoint(cfg['model_type'])
            if auto_ck:
                cfg['checkpoint'] = auto_ck

        self._cfg = cfg if cfg.get('python') else None
        # Path to the bundled worker script (sits next to this file).
        self._default_worker = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '_sam2_worker.py')

    # ── Availability + diagnostics ────────────────────────────────
    def available(self) -> bool:
        """True iff a config entry exists AND the external python is
        executable AND the worker script is on disk. Does NOT verify
        that torch/sam2 actually work — that only shows on first
        `segment()` call, whose failure the caller can log."""
        if not self._cfg:
            return False
        py = self._cfg.get('python', '')
        if not py or not os.path.isfile(py) or not os.access(py, os.X_OK):
            return False
        worker = self._resolved_worker()
        if not worker or not os.path.isfile(worker):
            return False
        return True

    def why_unavailable(self) -> str:
        """Human-readable reason if `available()` is False. Empty
        string if the backend is available."""
        if not self._cfg:
            return ("no heavy-env python with sam2 installed on disk. "
                    "Auto-tried: " + ", ".join(_CANDIDATE_PYTHONS) + ". "
                    "Add one to ~/.pystream/ai_backends.json under key "
                    f"[{self.NAME}][python].")
        py = self._cfg.get('python', '')
        if not py:
            return f"`python` path missing in ai_backends.json [{self.NAME}]"
        if not os.path.isfile(py):
            return f"python not found: {py}"
        if not os.access(py, os.X_OK):
            return f"python not executable: {py}"
        worker = self._resolved_worker()
        if not worker or not os.path.isfile(worker):
            return f"worker script not found: {worker}"
        return ""

    def diag(self) -> str:
        """One-line human-readable diagnostic — always safe to print."""
        if not self.available():
            return f"SAM2 unavailable: {self.why_unavailable()}"
        cfg = self._cfg
        ck = cfg.get('checkpoint') or "(none — sam2 will auto-download on first use)"
        return (f"SAM2 ready: python={cfg['python']}  "
                f"model={cfg['model_type']}  device={cfg['device']}  "
                f"ckpt={ck}")

    def missing_checkpoint_help(self) -> Optional[str]:
        """If the env is present but no checkpoint file is configured or
        found on disk, return a specific help message with the download
        URL. Otherwise None."""
        if not self._cfg or not self._cfg.get('python'):
            return None
        if self._cfg.get('checkpoint'):
            return None
        mt = self._cfg['model_type']
        url = _hf_download_url(mt)
        target = os.path.expanduser(f"~/.pystream/models/{_CKPT_FILENAMES[mt]}")
        return (f"SAM2 env is set up but no {mt} checkpoint found on disk. "
                f"Download once with:  wget -O {target}  {url}  "
                f"(pystream auto-detects it next launch.)")

    def _resolved_worker(self) -> str:
        w = self._cfg.get('worker', 'auto') if self._cfg else 'auto'
        return self._default_worker if w == 'auto' else str(w)

    # ── Segmentation ───────────────────────────────────────────────
    def segment(self, image: np.ndarray,
                point_x: float, point_y: float,
                timeout_s: Optional[float] = None) -> Optional[np.ndarray]:
        """Returns a boolean (H, W) mask, or None if the backend
        errored. Callers should log `.why_unavailable()` in the None
        branch to help the user diagnose."""
        if not self.available():
            return None
        cfg = self._cfg
        timeout_s = timeout_s if timeout_s is not None else float(
            cfg.get('timeout_s', 120))

        # Marshal image + prompt through tempfiles — robust across env
        # boundaries (no need for the two envs to share pickle protocols).
        with tempfile.TemporaryDirectory(prefix='pystream_sam2_') as td:
            img_path    = os.path.join(td, 'image.npy')
            mask_path   = os.path.join(td, 'mask.npy')
            req_path    = os.path.join(td, 'request.json')

            np.save(img_path, image)
            req = {
                'image_path':  img_path,
                'point_x':     float(point_x),
                'point_y':     float(point_y),
                'model_type':  cfg.get('model_type', 'sam2_hiera_small'),
                'device':      cfg.get('device', 'cpu'),
                'checkpoint':  cfg.get('checkpoint'),
                'output_path': mask_path,
            }
            with open(req_path, 'w') as f:
                json.dump(req, f)

            try:
                proc = subprocess.run(
                    [cfg['python'], self._resolved_worker(), req_path],
                    capture_output=True, text=True, timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._last_error = f"SAM2 worker timed out after {timeout_s}s"
                return None
            except Exception as ex:
                self._last_error = f"SAM2 worker failed to launch: {ex}"
                return None

            if proc.returncode != 0:
                self._last_error = (
                    f"SAM2 worker exit={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout or '').strip()[:400]}")
                return None
            if not os.path.exists(mask_path):
                self._last_error = "SAM2 worker returned no mask file"
                return None
            try:
                mask = np.load(mask_path)
            except Exception as ex:
                self._last_error = f"couldn't read SAM2 mask output: {ex}"
                return None

        self._last_error = ""
        return mask.astype(bool, copy=False)

    def last_error(self) -> str:
        return getattr(self, '_last_error', '')
