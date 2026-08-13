# AI Backends

Heavy ML tools (SAM2, and any future model) run in a **separate conda
environment** and are invoked from pystream via `subprocess`. Keeps
pystream's env light (PyQt5, numpy, scipy, epics — a few hundred MB)
while ML models sit in their own multi-GB envs.

## Architecture

```
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
```

Communication is via numpy tempfiles in a per-call temp directory — no
sockets, no long-lived daemon, no shared memory. Simple and robust.

## Folder layout

```
src/pystream/ai_backends/
    __init__.py            docs + re-exports
    config.py              loads ~/.pystream/ai_backends.json
    sam2_backend.py        SAM2 pystream-side wrapper
    _sam2_worker.py        SAM2 script that runs in the heavy env
```

## Config

`~/.pystream/ai_backends.json`:

```json
{
  "sam2": {
    "python":     "/home/beams/AMITTONE/miniconda3/envs/lvp/bin/python",
    "worker":     "auto",
    "model_type": "sam2_hiera_small",
    "device":     "cpu",
    "checkpoint": null,
    "timeout_s":  120
  }
}
```

- `python` — absolute path to the heavy env's python. Set to an existing
  interpreter that has `torch` + `sam2` installed.
- `worker` — `"auto"` uses the bundled `_sam2_worker.py`; a path
  overrides.
- `model_type` — `sam2_hiera_tiny` / `_small` / `_base_plus` / `_large`.
- `device` — `"cpu"` / `"cuda"` / `"cuda:0"`.
- `checkpoint` — absolute path to the `.pt` weights file. `null` lets
  sam2 auto-download from HuggingFace on first use (needs network).
- `timeout_s` — subprocess kill after this many seconds.

**Auto-detect**: if the config file is missing or the `python` path is
invalid, `SAM2Backend` searches known env paths (`lvp`, `cor_ml`,
`tomo-ml`) and known checkpoint cache dirs (`~/.cache/torch/hub`,
`~/.cache/huggingface`, `~/.pystream/models`). No config edit needed
if the setup follows convention.

## Adding a new backend

1. Drop `<foo>_backend.py` in `src/pystream/ai_backends/`. Class exposes
   `.available()`, `.<task-method>(args)`, `.last_error()`,
   `.why_unavailable()`, `.diag()`.
2. Drop `_<foo>_worker.py` in the same folder. Standalone script — no
   pystream imports (must run under the heavy env, which won't have
   pystream installed). Reads args (typically a JSON file path),
   writes result (typically a `.npy` file), exits.
3. Register in `~/.pystream/ai_backends.json` under a new key with
   `python` pointing at the appropriate env.
4. Import + call from a plugin: `from ..ai_backends.foo_backend import
   FooBackend; b = FooBackend(); result = b.compute(...)`.

## Current backends

### SAM2 (Segment Anything 2)

Point-prompted image segmentation. Used by
[AlignPart](beamlines/bl32ID.md#alignpart-particle-cor-alignment) as
the first-choice segmentation method; falls back to region-grow → Otsu
if unavailable or errors.

**Requirements**:
- Matched torch + torchvision pair (e.g. torch 2.5 + torchvision 0.20)
- `pip install sam2`
- SAM2 checkpoint `.pt` file (~150 MB for `hiera_small`)

**Quick setup**:
```bash
conda create -n pystream_sam2 python=3.11 pytorch=2.5 torchvision=0.20 -c pytorch
conda activate pystream_sam2
pip install sam2
mkdir -p ~/.pystream/models
wget -O ~/.pystream/models/sam2_hiera_small.pt \
  https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt
```

Then either edit `~/.pystream/ai_backends.json` to point `python` at
the new env, or the auto-detector will find it if the env name is in
`_CANDIDATE_PYTHONS`.
