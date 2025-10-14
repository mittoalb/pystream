# NTNDArray Real-time Viewer (`pystream`)

Real-time viewer for EPICS PVAccess `NTNDArray` data with dark-themed UI, flat-field correction, and plugin-based image-processing pipelines.  
Part of the APS Imaging Group real-time stream utilities.

## Features

- Real-time 2D image display from `NTNDArray` PVs  
- Grayscale conversion (RGB → luminance)  
- Dark, minimal interface (black background, white text)  
- Histogram and manual contrast sliders  
- Flat-field correction (Capture / Load / Save / Clear / Apply)  
- Plugin-based processing pipeline (JSON-defined)  
- Pause / Resume, Save Frame (`.npy`, `.png`)  
- Automatic FPS and UID display  
- Optional Matplotlib toolbar for zoom/pan  
- Extensible: easily add new processors without modifying core code

## Installation

Install directly in editable mode or from source:

```bash
pip install -e .
```

or simply install dependencies manually:

```bash
pip install numpy matplotlib pvaccess
```

Tkinter is required for GUI operation:
```bash
sudo apt install python3-tk     # Linux
```

## Usage

```bash
pystream --pv YOUR:NTNDARRAY:PV
```

Optional arguments:

| Option | Description | Default |
|---------|-------------|----------|
| `--max-fps` | Redraw rate (0 = unthrottled) | 30 |
| `--no-toolbar` | Hide Matplotlib toolbar | off |
| `--proc-config` | Path to JSON pipeline configuration | `processors.json` |
| `--no-plugins` | Disable plugin processing | off |

Example:
```bash
pystream --pv 32idbSP1:Pva1:Image --proc-config processors.json
```

## Flat-field correction

Flat-field normalization removes detector and illumination nonuniformity:

I_norm = (I_raw / I_flat) * mean(I_flat)

| Button | Function |
|---------|-----------|
| Capture Flat | Capture current image as flat |
| Apply Flat | Enable/disable flat-field correction |
| Load Flat | Load `.npy` flat file |
| Save Flat | Save flat to `.npy` |
| Clear Flat | Remove current flat |

## Plugin System

The viewer supports modular image processing through external Python scripts.  
Each plugin defines a function:

```python
def process(img, meta=None, **params):
    return img, meta
```

Plugins are defined in a JSON pipeline file. Example processor `processors/invert.py`:

```python
import numpy as np

def process(img, meta=None):
    img = img.astype(np.float32)
    lo, hi = np.nanmin(img), np.nanmax(img)
    if hi > lo:
        img = hi - (img - lo)
    return img.astype(np.float32), meta
```

Example configuration `processors_invert.json`:

```json
{
  "processors_dir": "processors",
  "hot_reload": true,
  "pipeline": [
    {"name": "invert", "module": "invert", "enabled": true, "params": {}}
  ]
}
```

## Example Plugin — Integrated Intensity vs Rotation

A plugin `processors/intensity_vs_rotation.py` allows monitoring integrated intensity as a motor scans.

- Opens a small control window.  
- Parameters: PV name, start angle, end angle.  
- Provides Start, Stop, and Save controls.  
- Plots integrated intensity for each frame during the motion.  

Example JSON entry:

```json
{
  "name": "intensity_vs_rotation",
  "module": "intensity_vs_rotation",
  "enabled": true,
  "params": {
    "motor_pv": "32idb:motor1",
    "start": 0,
    "end": 360
  }
}
```

## Directory Layout

```
pystream/
    __init__.py
    pystream.py
    procplug.py
    processors.json
    processors/
        normalize.py
        median.py
        invert.py
        intensity_vs_rotation.py
README.md
pyproject.toml
```

## Notes

- Pipelines are hot-reloaded when files change (if `hot_reload` = true).  
- Processors execute in JSON order (top-to-bottom).  
- Flat-field correction can combine with plugins.  
- Saving frames preserves current contrast and scaling.  
- All plugins are independent of the viewer core.
