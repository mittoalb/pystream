# Plugins

PyStream's core plugins for viewing, measuring, and processing image
data.

- [HDF5 Viewer](viewer.md) — view HDF5 image stacks with flat-field
  correction.
- [Rectangle ROI](roi.md), [Ellipse ROI](ellipse.md),
  [Line Profile](line.md) — region selection and intensity profiles.
- [Scale Bar](scalebar.md) — calibrated scale-bar overlay.
- [Python Console](console.md) — run Python on the live image.
- [Image Metrics](metrics.md) — live image-quality metrics.
- [Mosaic Alignment](mosalign.md) — 2D motor scan with stitched preview.

## Adding a plugin

1. Add a Python module under `src/pystream/plugins/`.
2. Define a `QDialog` or `QWidget` class with class attribute
   `BUTTON_TEXT = "..."`. Most plugins also set
   `HANDLER_TYPE = 'singleton'`.
3. Wire the button into the main toolbar in
   [src/pystream/pystream.py](../../src/pystream/pystream.py) — copy an
   existing handler such as `_open_metrics()` and adapt.

```{toctree}
:maxdepth: 1
:hidden:

viewer
roi
ellipse
line
scalebar
console
metrics
mosalign
```
