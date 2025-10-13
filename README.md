# NTNDArray Real-Time Viewer

A lightweight **EPICS PVA (pvAccess)** viewer that displays 2D `NTNDArray` images in real time with **ImageJ-like controls**: zoom, pan, contrast, histogram, and grayscale visualization.

---

## ✨ Features

- Live display of `NTNDArray` images from an EPICS PV  
- Automatic grayscale conversion (RGB → luminance)  
- Real-time histogram with autoscale or manual contrast  
- Zoom, pan, and flip tools (via Matplotlib + Tkinter)  
- Pause/resume and frame save options (`.png` or `.npy`)  
- Shows PV `uniqueId` and measured FPS  

---

## ⚙️ Requirements

Install the following Python packages (Python ≥ 3.8):

```bash
pip install pvapy numpy matplotlib
```

> 🧩 `tkinter` is included with most Python distributions (on Linux: `sudo apt install python3-tk`).

---

## 🚀 Usage

```bash
python pv_ntnda_viewer.py --pv <PV_NAME>
```

Example:

```bash
python pv_ntnda_viewer.py --pv 32idbSP1:Pva1:Image
```

Optional arguments:

| Option | Description | Default |
|---------|--------------|----------|
| `--pv` | NTNDArray PV name | *required* |
| `--max-fps` | Limit UI redraw rate (0 = unthrottled) | 30 |
| `--no-toolbar` | Hide zoom/pan toolbar | off |

---

## 🖼️ Display Controls

| Control | Description |
|----------|-------------|
| **Zoom / Pan** | Toolbar icons or mouse scroll/drag |
| **Autoscale** | Auto-adjust contrast for each frame |
| **Manual Contrast** | Adjust Min/Max sliders |
| **Flip H / V / Transpose** | Quick view orientation tools |
| **Pause / Resume** | Temporarily stop live updates |
| **Save Frame** | Save as `.npy` (raw) or `.png` |
| **Histogram** | Always visible and updates live |

---

## 🧠 Notes

- The viewer **does not affect PV streaming** — it passively monitors and displays new frames.
- The displayed **FPS** is computed from incoming PV updates.
- For best results, use with AreaDetector `NDPluginPva` or TomoStream PVs.

---

© 2025 – APS Imaging Group utilities (example)
