# Ellipse ROI

Elliptical region selection over the live image. Stats are computed over
pixels that satisfy `((x-cx)/a)² + ((y-cy)/b)² ≤ 1` — not just the
bounding box.

## Usage

Enable the ellipse checkbox, press-drag-release to draw, then drag axis
handles for single-axis stretch or diagonal handles for uniform scale.
**Reset** centers the ellipse back to ¼ of the image. The shape switches
between *Circle* and *Ellipse* automatically when width ≈ height.

## Adding new stats

Stats are formatted in `update_stats()` of
[src/pystream/plugins/ellipse.py](../../src/pystream/plugins/ellipse.py).
Pixels inside the ellipse are produced by `get_roi_data(image)`; compute
your metric on that array and append a line to the displayed text.
