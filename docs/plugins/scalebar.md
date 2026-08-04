# Scale Bar

Two independent calibrated scale bars rendered over the image. Bar
length is auto-rounded to a nice number (1, 2, 5, 10, …) for the
current image width, and units auto-promote (1000 nm → 1 µm,
1000 µm → 1 mm, …).

## Usage

Enable the scale-bar checkbox. Click **Settings** to set per-bar pixel
size, unit (nm, µm, mm, m, Å, px), corner position, color, width
(fraction of image), and vertical offset (for stacking). Bar 2 defaults
to yellow, 40 px above bar 1.

## Adding a new unit or rounding rule

Unit promotion and the 1/2/5 rounding ladder live in `_get_nice_scale()`
and `_format_label()` in
[src/pystream/plugins/scalebar.py](../../src/pystream/plugins/scalebar.py).
To add a new base unit (e.g. pm), add it to the unit combobox and extend
the conversion ladder in `_format_label()`.
