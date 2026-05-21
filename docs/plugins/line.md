# Line Profile

Interactive line over the live image with an intensity profile and
length/ΔX/ΔY in px, µm, and mm.

## Usage

Enable the line checkbox. A horizontal line appears at image center; drag
either endpoint to reposition or the center handle to translate. **Hold
Shift while dragging** to snap the line to horizontal or vertical
(ImageJ-style). Distances in µm and mm require a pixel size set via
`set_pixel_size(...)` (otherwise only pixel distance is shown).

## Adding new measurements

Stats are formatted in `update_stats()` of
[src/pystream/plugins/line.py](../../src/pystream/plugins/line.py). The
sampled profile is produced by `get_line_profile(image)` as
`(positions, values)` — compute your metric on `values` and append a
line to the displayed text.
