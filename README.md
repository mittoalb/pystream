# PyStream

Real-time image viewer for EPICS PVAccess NTNDArray data with beamline-specific tools.

## Features

- **Real-time streaming** — live EPICS area-detector visualization
- **Beamline plugin packs** — per-facility toolbars grouped into dropdown menus (Alignment / Scans / Detector / Viewers / Calculators / Tools / Test)
- **Image analysis** — ROI/ellipse/line-profile with intensity plot, scale bar, histogram, live metrics, Python console for on-the-fly image processing
- **HDF5 Viewer** — drag-and-drop, line + ROI tools with the same UX as the live viewer, filters (median/Gaussian/threshold), frame averaging, PNG/TIFF/NPY export
- **Motor-driven tools** — center-of-rotation finder, click-a-particle → auto-align on rotation axis, mosaic scan, XANES / XANES-2D / DataMap
- **Extensible AI backends** — heavy ML models (SAM2, …) run in a separate conda env via subprocess; pystream stays light
- **`pystream-new-beamline` CLI** — scaffold a new beamline package in one command

## Installation

```bash
# From this repo (recommended for developers):
cd pystream
pip install -e ".[bl32ID]"        # editable + bl32ID extras

# From GitHub with extras:
pip install "pystream[bl32ID] @ git+https://github.com/mittoalb/pystream.git@dev"
```

**Note**: `pip install pystream` (bare name) resolves to an unrelated PyPI package. Always use a local path (`.`) or a `git+…` URL.

## Quick Start

```bash
pystream --pv YOUR:NTNDARRAY:PV
```

Common flags: `--max-fps`, `--display-bin`, `--proc-config`, `--no-plugins`, `--log-level`, `--log-file`. See `pystream --help`.

## Creating a new beamline

```bash
pystream-new-beamline bl7BM --description "APS 7-BM tomography"
```

Creates `src/pystream/beamlines/bl7BM/__init__.py` with an empty plugin list. See [docs/beamlines/adding_a_beamline.md](docs/beamlines/adding_a_beamline.md).

## Testing without hardware

Included [test/sim_tomo_beamline.py](test/sim_tomo_beamline.py) is a synthetic 32-ID beamline — fake motor soft-IOC + PVA image stream of a noisy tomography phantom. Lets you exercise every plugin (CoR, AlignPart, aTomo, HDF5 Viewer) with zero real hardware.

```bash
python test/sim_tomo_beamline.py          # live PVA + motor IOC
python test/sim_tomo_beamline.py --write-h5 /tmp/sim.h5 --num-projections 90   # static DXchange-compatible HDF5
```

## Documentation

**📚 Full documentation**: https://pystream.readthedocs.io

## License

MIT License — Copyright (c) 2025 Alberto Mittone
