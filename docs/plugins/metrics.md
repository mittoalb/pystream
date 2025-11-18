# Image Information Metrics — PyStream Plugin

A lightweight, real-time monitor that computes information-content metrics from an EPICS **NTNDArray** image PV and plots them live in a dark-themed PyQtGraph UI.

---

## Features
- Live plots for 10+ metrics (entropy, focus, spectral stats, compressibility).
- Optional **reference frame** for **mutual information** (MI).
- “**Interest score**” (0–1) combining several metrics to flag noteworthy frames.
- “Tomography mode” to index x-axis by **angle** instead of time and estimate total projections.
- Bookmark, list, and export “interesting” frames; view best-frame summary.
- CSV/NPZ export of all traces.

---

## Requirements
- Python 3.8+
- `numpy`, `pyqtgraph`, `PyQt5`
- `pvaccess` (EPICS PVA client)
- Optional: `scipy` (accelerates Laplacian via `convolve2d`, FFT via `scipy.fft`)

---

## Run
```bash
metrics
```
Then enter your detector PV (e.g. `32idbSP1:Pva1:Image`) and press **Start**.

> Headless/remote: ensure a working Qt/OpenGL setup (e.g., X11 forwarding or offscreen).

---

## UI at a glance
- **Controls**: PV, histogram **Bins** (16–512), **Interest Threshold**, Start/Stop, Capture/Clear Reference.
- **Tomography**: Enable, **Start/End angle**, **Angular spacing** (°/frame), computed **Total projections**.
- **Plots**: Time or Angle on x-axis; metrics on y-axis.  
  Gold ★ = best frame; green ○ = frames ≥ threshold.
- **Bottom bar**: Clear, Save (CSV/NPZ), Best-frame info, List/Export interesting frames, live counts.

---

## Metrics (concise)
| Key | Meaning (units) | Notes |
|---|---|---|
| `shannon_entropy` | Bits/pixel | Histogram on [0,1] with `bins`. |
| `normalized_entropy` | 0–1 | `H / log2(bins)`. |
| `zlib_compressibility` | Bytes/pixel | Zlib(level=9) of quantized image. Lower ≈ more compressible. |
| `laplacian_variance` | Variance | Focus/texture proxy (higher ≈ sharper). |
| `spectral_entropy` | Bits | Entropy of power spectrum (Hann-windowed FFT). |
| `spectral_centroid` | 0–1 | Power-weighted frequency “center of mass.” |
| `high_frequency_energy` | 0–1 | Fraction of power above a frequency threshold (default 0.3). |
| `gradient_magnitude` | Mean | Average ∥∇I∥ (edge content). |
| `spectral_flatness` | 0–1 | Wiener entropy (geom/arith mean of spectrum). 1≈white noise. |
| `mutual_information` | Bits | Vs captured reference (same shape). |
| `interest_score` | 0–1 | Weighted blend: normalized entropy (0.25), LapVar (0.25 scaled), spectral entropy (0.20), HF energy (0.15), gradient mag (0.15). Capped to 1.0. |

_All metrics operate on grayscale float images in [0,1] via `to_gray_float01()`._

---

## Workflow Tips
1. **Start** monitoring → watch **Interest Score**; adjust **Threshold** to your scene.
2. **Capture Reference** to enable **MI** (e.g., flat/dark/registration target).
3. For scans, toggle **Tomography** to plot vs **angle** and track **projections**.
4. Use **Show All Interesting Frames** to review hits; **Export** for logs/QA.

---

## Data & Export
- **Save Data…**:  
  - **CSV**: `time_or_angle, shannon_entropy, …, interest_score[, mutual_information]` per row.  
  - **NPZ**: `times` + arrays per metric (aligned).
- **Export Interesting Frames…**: CSV of frames ≥ threshold (sorted by frame index).

---

## Integration Notes
- The PVA fetcher (`pva_get_ndarray`) supports common NTNDArray numeric fields and attempts to reshape via `dimension` metadata; falls back to known camera sizes or nearest factors.
- SciPy is optional; without it, Laplacian uses a NumPy fallback.

---

## Troubleshooting
- **“Unsupported NTNDArray type”**: Check PV carries one of `ushort/short/int/float/double/ubyte/byte` arrays.
- **Wrong shape**: Ensure producer fills `dimension`; otherwise add your camera shape to `common_shapes`.
- **Low FPS / choppy**: Reduce **Bins**, increase sleep, or throttle upstream PV rate.
- **Flat interest**: Verify dynamic range (histogram bins), adjust **Threshold**, or check that frames change.

---

## API surface (for reuse)
- Metric helpers: `to_gray_float01`, `shannon_entropy_bits`, `normalized_entropy`, `zlib_compressibility`, `laplacian_variance`, `spectral_entropy`, `spectral_centroid`, `high_frequency_energy`, `gradient_magnitude`, `spectral_flatness`, `mutual_information`, `compute_all_metrics`.
- PV helper: `pva_get_ndarray(pv_name)`.
- Dialog: `ImageInfoDialog` (Qt `QDialog` with `metrics_updated` signal).

---

## License & Attribution
Include this file in your repo’s `docs/` and link it from `README.md`. Metrics are standard definitions adapted for live use; FFT operations apply Hann windows and zero DC before spectral stats.
