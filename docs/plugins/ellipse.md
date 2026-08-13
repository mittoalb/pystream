# Ellipse ROI

Draggable elliptical ROI over the live image, with min/max/mean/std/
sum + area + perimeter statistics computed on pixels inside the
ellipse.

## Usage

Enable the **Ellipse** checkbox. Click and drag on the image to draw
an ellipse. Once placed, drag the eight handles (four axis-aligned,
four diagonal at 45°) to reshape. **Reset** returns to a default
centered ellipse.

## Zoom-anchored + orphan sweep

Same fixes as [Rectangle ROI](roi.md): parented to the ViewBox (moves
with pan/zoom), sweep-list ensures every ellipse ever created can be
cleaned up even when internal `removeItem` fails silently.

## Extract data

`get_roi_data(image)` returns the pixel array inside the elliptical
mask (not the bounding box). Uses the standard analytic condition
`((x - cx)/a)² + ((y - cy)/b)² ≤ 1`.
