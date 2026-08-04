# HDF5 Image Viewer

Standalone viewer for HDF5 stacks with optional flat-field division.
Launch with `viewer`.

## What it does

- Loads an HDF5 file with `/exchange/data` (projections) and optionally
  `/exchange/data_white` (flats).
- Image tab: slider over the stack, optional normalization
  (`data / data_white`), contrast modes (per-image, min/max, percentile,
  manual), and arrow-key shift of the flat (1 / Shift=10 / Ctrl=50 px).
- Metadata tab: filterable attribute table, HDF5 tree, CSV export.

## Adding contrast modes or metadata fields

Modes are dispatched in `_apply_contrast()` of
[src/pystream/plugins/viewer.py](../../src/pystream/plugins/viewer.py).
Add a new entry to the contrast-mode combobox and a matching branch in
that method. The metadata table is populated by `_load_metadata()`; add
an entry there to surface a new dataset.
