# Image Metrics

Live information-content metrics computed from an EPICS NTNDArray image
PV: entropy, normalized entropy, zlib compressibility, Laplacian
variance, spectral entropy/centroid/flatness, high-frequency energy,
gradient magnitude, optional mutual information against a captured
reference, and a combined 0–1 *interest score*.

Launch with `metrics`, enter the detector PV (e.g.
`32idbSP1:Pva1:Image`), and press **Start**.

## Usage

- **Capture Reference** records a frame; mutual information is then
  plotted against it.
- **Tomography mode** switches the x-axis from time to angle and uses
  start/end angles + spacing to estimate total projections.
- Frames above the **Interest Threshold** are marked; the best frame is
  highlighted. **Save Data…** exports CSV or NPZ.

## Adding a new metric

1. Add the metric function in
   [src/pystream/plugins/metrics.py](../../src/pystream/plugins/metrics.py),
   following the existing helpers (input is a float grayscale image in
   `[0, 1]`).
2. Call it from `compute_all_metrics()` and add its key to the returned
   dict.
3. Add a plot trace for it in the dialog setup so it appears in the UI.
