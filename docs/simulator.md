# Synthetic Beamline Simulator

[test/sim_tomo_beamline.py](../test/sim_tomo_beamline.py) is a fake
32-ID TXM beamline for testing pystream plugins without real hardware.

## What it provides

- **Fake soft-IOC motors** (via `pcaspy`):
  - `32idbTXM:ens:c1:m1` — rotation (deg)
  - `32idbTXM:mcs:c1:m2` — topx (mm)
  - `32idbTXM:mcs:c1:m1` — topz (mm)
  - Each PV has `.VAL` and `.RBV` variants; `caput` echoes to all three.
- **Fake detector PVA channel** `32idbSP1:Pva1:Image` (via `pvapy`) —
  NTNDArray at ~10 fps, matching the real detector's channel name so
  pystream connects unchanged.
- Every published frame is a **parallel-beam projection of a 3D phantom**
  (background sample stub + 5 lumpy irregular particles) at the current
  motor RBVs.
- Realistic image noise: Poisson shot noise + Gaussian read noise +
  dark offset + hot pixels + Gaussian beam-profile flat field.

## Two modes

**Live stream** (default):

```bash
python test/sim_tomo_beamline.py
python test/sim_tomo_beamline.py --fps 5 --width 2048 --height 2048
python test/sim_tomo_beamline.py --color always      # force ANSI in piped output
```

**Write a static HDF5 file** for HDF5 Viewer testing:

```bash
python test/sim_tomo_beamline.py --write-h5 /tmp/sim.h5 --num-projections 90
```

Produces a DXchange-compatible file with `/exchange/data`,
`/exchange/data_white`, `/exchange/data_dark`, `/exchange/theta`.

## What you can test

- **CoR plugin** — click Run. Reports the rotation axis at
  `image_width/2 + 25 px` (the simulator's `COR_COL_OFFSET_PX`).
- **AlignPart plugin** — Pick Particle → click a lumpy particle → Run.
  Motors move (visible on the fake motor RBVs); particle converges onto
  the CoR at vertical center.
- **aTomo daemon** — point it at the fake rotation motor + detector,
  run a real scan against the fake beamline.
- **HDF5 Viewer** — drag-drop the `--write-h5` file, use the Tools /
  Filter / Averaging / Export dropdowns.
- **QGMax auto-mode** — point at `32idbSP1:Pva1:Image` and drive it
  through its request-file protocol.

## Tunable constants

Edit the top of `test/sim_tomo_beamline.py`:

- `IMAGE_W`, `IMAGE_H` — detector size (default 1024²)
- `MM_PX` — pixel size (default 0.766 µm, matches 32-ID TXM)
- `COR_COL_OFFSET_PX` — true rotation axis offset from image center
  (default +25 px, so CoR/AlignPart have real work to do)
- `FLUX` — photons/pixel through empty beam (default 5000; lower =
  noisier)
- `READ_NOISE` — Gaussian σ (default 45)
- `DARK_OFFSET`, `N_HOT_PIXELS`
- `DEFAULT_PHANTOM` — 5 lumpy clusters + 1 background stub. Each entry
  is `(x_mm, y_mm, z_mm, radius_mm, absorption)` in sample-frame coords.
  See `build_realistic_phantom()` for how clusters are generated.

## Coordinate conventions

- Beamline frame: rotation is around vertical (z), beam along y, x
  horizontal perpendicular to beam.
- Rotation axis: image column `IMAGE_W/2 + COR_COL_OFFSET_PX`. Vertical
  center: image row `IMAGE_H/2`.
- Sign convention: `positive topx` moves the rotation axis LEFT in the
  image (matches the AutoCenter/AlignPart plugin's `mm_px_x = -0.000766`
  sign so alignment converges, not diverges).

## Requirements

`pcaspy`, `pvapy`, `numpy`, `h5py` — all already in pystream's env.
