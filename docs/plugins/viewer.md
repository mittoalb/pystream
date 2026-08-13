# HDF5 Image Viewer

Interactive viewer for HDF5 tomography stacks with flat-field division,
per-slice tools, display-only filters, frame averaging, and export.
Launch via `viewer` (standalone) or the HDF5 Viewer button in pystream.

## What it does

- Loads an HDF5 file with `/exchange/data` (projections) and
  `/exchange/data_white` (flats).
- **Drag-and-drop** — drop `.h5` / `.hdf5` files onto the window; loads
  without touching the file dialog.
- Two tabs: **Image Viewer** (below) and **Metadata** (filterable table
  + HDF5 tree + CSV export).

## Image Viewer tab

**Top bar** — three dropdown menus:

- **Tools ▾** — Line + Rect ROI + Ellipse ROI + Scale bar toggles, plus
  reset / Profile / scale-bar-settings actions. All four managers are the
  same ones the live pystream viewer uses; the [Line](line.md),
  [ROI](roi.md), [Ellipse](ellipse.md), [Scale Bar](scalebar.md)
  behaviors + zoom-anchor + orphan-sweep + display-bin fixes all apply
  here too.
- **Filter ▾** — radio-select `None / Median / Gaussian / Threshold (>)`
  with a parameter spin box in the menu (via `QWidgetAction`). Applied
  post-division, pre-contrast. Display-only; the on-disk file is
  untouched. Gracefully disabled if scipy isn't installed.
- **Export ▾** — save the current view as **PNG** (rendered ImageView
  including tool overlays), **TIFF** (float32 raw of the current
  displayed image via `tifffile`, falling back to `imageio`), or
  **NPY** (numpy save).

**Left panel** — file selection, dataset info, image slider, **Average
±N frames** spin box (loads `data[i-N:i+N+1]` and averages before
`data/data_white` division — good for noisy adaptive-exposure
projections), Normalization toggle, Contrast presets (per-image,
min/max, percentile 1-99%/2-98%/5-95%, manual), XY shift for the flat
(arrow keys, +Shift=10, +Ctrl=50), image statistics, Analysis panel
(line/ROI/ellipse stat readouts).

**Right panel** — the pyqtgraph `ImageView`.

## Metadata tab

Filterable attribute table + full HDF5 tree. Metadata reader comes from
[meta-cli](https://github.com/xray-imaging/meta-cli).

## Adding contrast modes or metadata fields

Modes dispatched in `_apply_contrast_settings()` of
[src/pystream/plugins/viewer.py](../../src/pystream/plugins/viewer.py).
Add a new entry to the `auto_level_combo` and a matching branch. The
metadata table is populated by `load_metadata()` on the
`MetadataViewer`.

## Env caveats

- **Filters** need `scipy` — Median/Gaussian/Threshold. If missing, the
  Filter menu items grey out with a "scipy not installed" note.
- **TIFF export** prefers `tifffile`; falls back to `imageio`. If
  neither is installed, TIFF errors cleanly but PNG and NPY still work.
