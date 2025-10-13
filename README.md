# NTNDArray Real-time Viewer (Dark UI + Flat-field)

A live viewer for **EPICS PVAccess NTNDArray** data streams, designed for X-ray or optical imaging workflows.  
It provides real-time display, histogram and contrast control, and **flat-field normalization** with a modern dark interface.

---

## Features
- **Dark UI** (black background for reduced glare)
- Real-time image stream from any `NTNDArray` PV (e.g. `32idbSP1:Pva1:Image`)
- Grayscale enforced (RGB → luminance)
- ImageJ-like tools: zoom, pan, histogram, contrast sliders
- **Flat-field correction** (Capture / Load / Save / Clear + toggle Apply Flat)
- Pause / Resume stream
- Frame save (`.npy` or `.png`)
- FPS and UID display
- Optional Matplotlib toolbar

---

## ⚙️ Flat-field normalization

Flat-field correction removes illumination and detector nonuniformity:

\[
I_{norm} = \frac{I_{raw}}{I_{flat}} \times \langle I_{flat} \rangle
\]

### Controls
| Button | Function |
|---------|-----------|
| **Capture Flat** | Capture the current displayed image as the flat (open beam) |
| **Apply Flat** | Toggle normalization ON/OFF in real time |
| **Load Flat…** | Load a saved `.npy` flat file |
| **Save Flat…** | Save the current flat for later use |
| **Clear Flat** | Remove the stored flat |

---

## Installation

**Dependencies:**
```bash
pip install pvapy numpy matplotlib
```
*(and `python3-tk` via your OS package manager if missing, e.g. `sudo apt install python3-tk`)*

---

## Usage

```bash
python pv_ntnda_viewer.py --pv YOUR:NTNDARRAY:PV
```

**Optional arguments:**
| Option | Default | Description |
|---------|----------|-------------|
| `--max-fps` | `30` | UI redraw throttle (0 = unthrottled) |
| `--no-toolbar` | _off_ | Hide Matplotlib zoom/pan toolbar |

---

## 💡 Notes
- The viewer automatically converts RGB NTNDArray frames to grayscale.
- Histogram and contrast sliders update dynamically.
- The flat is applied **after** orientation transforms (flip/transpose), ensuring correct alignment.
- You can extend it with dark-field correction or ROI-based statistics.

---

## Example
```bash
python pv_ntnda_viewer.py --pv 32idbSP1:Pva1:Image
```
Capture a flat under open-beam conditions, then enable **Apply Flat** to see live normalized images.

---

**Author:** APS Imaging Group (Argonne National Laboratory)  
**Version:** 2025-10  
**License:** Internal research use only
