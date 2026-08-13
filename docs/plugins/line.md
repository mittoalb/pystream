# Line Profile

Interactive line over the live image with an intensity profile popup and
length/ΔX/ΔY in px, µm, and mm.

## Usage

Enable the **Line** checkbox. A crosshair cursor appears — first click
places the start, drag + click again to place the end. Then drag either
endpoint to reposition or the center handle to translate. **Hold Shift
while dragging** to snap to horizontal or vertical (ImageJ-style).
Distances in µm and mm come from the pixel size set on the
[Scale Bar](scalebar.md); without one, only pixel distance is shown.

## Intensity profile popup

Click **Profile** next to the Line checkbox to open an ImageJ-style
line-profile plot. The plot live-updates with:

- Every frame the viewer receives (sampled bilinearly along the current
  line at one sample per displayed pixel).
- Every drag of an endpoint or the center handle.

Buttons in the popup: **Freeze** (pauses live updates so you can inspect
a specific frame's profile), **Copy to clipboard** (dumps tab-separated
`distance_um\tintensity` for pasting into Excel/notebook).

## Zoom-anchored annotations

The line and its handles are parented to the ImageItem, so pan/zoom
carries them with the image — the line stays on the feature you drew it
across regardless of view transformations. Same fix applies to Rect /
Ellipse ROI. (Old behavior: line stayed in scene coords and drifted off
the feature when you zoomed.)

## Display-bin length correction

pystream's viewer decimates large images to fit the widget
(auto-decimation, or explicit via `--display-bin N`). The line-length
readout compensates automatically — dx/dy in decimated pixels are scaled
up by the decimation factor, and multiplied by the scale bar's per-
sensor-pixel µm value. A line labeled "76.6 µm" is 76.6 µm on the
sample regardless of window size or `--display-bin` setting.

## Adding new measurements

Stats are formatted in `_refresh_stats()` of
[src/pystream/plugins/line.py](../../src/pystream/plugins/line.py). The
sampled profile is produced by `_update_profile()` as
`(distances_um, intensities)` — compute your metric on `intensities`
and append a line to the displayed text.
