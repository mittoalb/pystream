# Rectangle ROI

Rectangular region selection over the live image, with 8 resize handles
and live stats (min/max/mean/std/sum, position, size).

## Usage

Enable the rectangle checkbox, press-drag-release to draw, then drag
corner handles for diagonal resize, edge handles for single-axis
resize, or the body to move. **Reset** centers the ROI back to ¼ of
the image.

## Adding new stats

Stats are formatted in `update_stats()` of
[src/pystream/plugins/roi.py](../../src/pystream/plugins/roi.py).
Extract the ROI pixels via `roi.getArraySlice(image, image_item)`,
compute whatever you need, and add a line to the displayed text.
