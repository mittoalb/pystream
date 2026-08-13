# Rectangle ROI

Draggable rectangular ROI over the live image, with min/max/mean/std/
sum + area statistics updated per frame.

## Usage

Enable the **Rect ROI** checkbox. Click and drag on the image to draw
a rectangle. Once placed, drag the corner/edge handles to resize or the
center to translate. **Reset** returns to a default centered rectangle.

## Zoom-anchored

The ROI is added to the ViewBox (image-item local coordinates), so
pan/zoom carries it with the image — it stays on whatever feature you
drew it around. Old behavior: ROI stayed in scene coords and drifted off
the image on zoom.

## Orphan sweep (no more accumulating ROIs)

Each manager keeps a strong-reference list (`_all_rois`, `_all_texts`)
of every ROI + dimension-text it has ever created. On remove/reset,
the entire list is swept — so if a previous `view.removeItem` failed
silently (which used to leave orphans on the ViewBox with no
reference to remove them), the next toggle-off / reset / new-draw
cleans them all up. Prevents the "multiple ROIs I can't remove"
symptom.

## Extract data

`get_roi_data(image)` returns the pixel array within the ROI —
useful from a Python console or a downstream analysis plugin.
`get_roi_bounds()` returns `{x, y, width, height}` in image pixels.
