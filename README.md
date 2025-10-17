# NTNDArray Real-time Viewer (pystream)

Real-time viewer for EPICS PVAccess NTNDArray data with multiple backend options: PyQtGraph (SSH-compatible), VisPy (GPU-accelerated), and legacy Tkinter/Matplotlib. Features include interactive crosshair, histogram/contrast controls, flat-field correction, and a plugin pipeline for custom image processing.

---

## Features

- Real-time 2D image display from EPICS PVA NTNDArray PVs
- Three viewer backends:
  - **PyQtGraph** (default): SSH-compatible, high performance without OpenGL
  - **VisPy**: GPU-accelerated OpenGL rendering for local use
  - **Tkinter/Matplotlib**: Legacy backend
- Interactive crosshair with position and value readout
- Grayscale conversion (RGB to luminance)
- Dark interface theme
- Histogram with manual contrast sliders and autoscale
- Flat-field correction (Capture / Load / Save / Clear / Apply)
- Plugin pipeline (JSON-defined) for custom image processing per frame
- Image transforms (Flip H/V, Transpose)
- Pause / Resume, Save Frame (.npy, .png)
- FPS and UID display
- PV persistence across launches (saved to viewer_config.json)
- Structured logging with optional file output

---

## Installation

### Conda Environment

Create and activate a conda environment with required dependencies:
```bash
# Create environment
conda create -n pystream python=3.10 numpy pyqt -c conda-forge

# Activate environment
conda activate pystream

# Install additional dependencies
pip install pvapy pyqtgraph Pillow
```

For VisPy support (optional, for local high-performance rendering):
```bash
pip install vispy
```

For legacy Tkinter/Matplotlib backend (optional):
```bash
conda install matplotlib
# On Linux, may also need: sudo apt install python3-tk
```

### Package Installation

Install from the repository:
```bash
# Standard installation (PyQtGraph viewer)
pip install -e .

# With VisPy support
pip install -e .[vispy]

# With all features
pip install -e .[all]
```

---

## Usage

### PyQtGraph Viewer (Default - SSH Compatible)

Recommended for remote use over SSH. No OpenGL required.
```bash
pystream --pv YOUR:NTNDARRAY:PV
```

Or using the full script name:
```bash
python pyqtgraph_viewer.py --pv YOUR:NTNDARRAY:PV
```

### VisPy Viewer (High Performance - Local Use)

GPU-accelerated rendering. Requires OpenGL support.
```bash
pystream-vispy --pv YOUR:NTNDARRAY:PV
```

Or:
```bash
python pyqtstream.py --pv YOUR:NTNDARRAY:PV
```

Note: VisPy does not work over standard SSH X11 forwarding. Use PyQtGraph viewer for remote access.

### Legacy Tkinter Viewer

Original Matplotlib-based viewer:
```bash
pystream-legacy --pv YOUR:NTNDARRAY:PV
```

Or:
```bash
python pystream.py --pv YOUR:NTNDARRAY:PV
```

---

## Command-Line Options

Common options for all viewers:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `--pv` | NTNDArray PV name (can be changed in GUI) | none |
| `--max-fps` | Maximum display FPS (0 = unthrottled) | 0 for PyQtGraph/VisPy, 30 for legacy |
| `--hist-fps` | Histogram update rate (Hz) | 4.0 |
| `--display-bin` | Display decimation factor (0 = auto) | 0 |
| `--auto-every` | Autoscale every N frames | 10 |
| `--proc-config` | Path to plugin pipeline JSON | pipelines/processors.json |
| `--no-plugins` | Disable plugin processing | off |
| `--log-file` | Path to log file | none |
| `--log-level` | Logging level: DEBUG/INFO/WARNING/ERROR/CRITICAL | INFO |

VisPy-specific options:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `--software-rendering` | Force software rendering (for SSH/VNC) | off |

Legacy viewer options:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `--no-toolbar` | Hide Matplotlib toolbar | off |

Examples:
```bash
# PyQtGraph viewer over SSH
ssh -Y user@remote
pystream --pv 2bmSP2:Pva1:Image

# VisPy viewer locally with debug logging
pystream-vispy --pv 2bmSP2:Pva1:Image --log-level DEBUG --log-file viewer.log

# With custom pipeline
pystream --pv 2bmSP2:Pva1:Image --proc-config my_pipeline.json
```

---

## Interactive Crosshair

All viewers support an interactive crosshair for examining pixel values:

1. Enable the "Crosshair" checkbox in the toolbar
2. Click or drag on the image to position the crosshair
3. The left panel displays:
   - X position (column index)
   - Y position (row index)
   - Pixel value at crosshair location

The crosshair updates in real-time as the image streams.

---

## PV Persistence

The viewer saves the last PV name to `viewer_config.json` in the application directory. On next launch, the PV field is pre-filled and auto-connects if valid.

- Command-line `--pv` overrides the saved value for that session
- Current PV value is saved on clean exit

---

## Flat-field Correction

Flat-field normalization removes detector and illumination nonuniformity:
```
I_norm = (I_raw / I_flat) * mean(I_flat)
```

Controls:

| Button | Function |
| ------ | -------- |
| Capture Flat | Capture current displayed image as flat reference |
| Apply Flat | Toggle flat-field correction on/off |
| Load Flat | Load flat from .npy file |
| Save Flat | Save current flat to .npy file |
| Clear Flat | Remove flat reference |

Notes:
- Flat shape must match incoming frame shape
- Flat-field is applied after plugin pipeline processing
- Applied to view-transformed image (after flip/transpose)

---

## Plugin Pipeline

The plugin pipeline processes each frame before display. Processors are defined in a JSON configuration file.

### Configuration Format

**pipelines/processors.json**:
```json
{
  "processors": [
    {
      "name": "MyProcessor",
      "module": "my_module",
      "class": "MyProcessorClass",
      "kwargs": {
        "param1": "value1",
        "param2": 42
      }
    }
  ]
}
```

### Processor Requirements

Each processor class must implement:
```python
class MyProcessorClass:
    def __init__(self, **kwargs):
        # Initialize with kwargs from JSON
        pass
    
    def apply(self, img: np.ndarray, meta: dict) -> np.ndarray:
        # Process image and return modified version
        # meta contains: {"uid": frame_id, "timestamp": ts}
        return processed_img
```

### Example: Frame Summation

**sum.py**:
```python
import numpy as np

class SumFrames:
    def __init__(self, preview_sum=False, **kwargs):
        self.preview = preview_sum
        self.sum_img = None
        self.count = 0
    
    def apply(self, img, meta):
        if self.sum_img is None:
            self.sum_img = img.astype(np.float64)
        else:
            self.sum_img += img
        self.count += 1
        
        if self.preview:
            return (self.sum_img / self.count).astype(img.dtype)
        return img
```

**pipelines/processors.json**:
```json
{
  "processors": [
    {
      "name": "SumFrames",
      "module": "sum",
      "class": "SumFrames",
      "kwargs": {"preview_sum": true}
    }
  ]
}
```

Place `sum.py` next to the viewer scripts or on PYTHONPATH.

### Pipeline Execution

- Processors execute in order (top to bottom in JSON)
- Each processor receives the output of the previous processor
- Flat-field correction is applied after all pipeline stages
- Pipeline runs on GUI thread to avoid threading issues

---

## Logging

Structured logging with colorized console output:
```bash
# Info level (default)
pystream --pv 2bmSP2:Pva1:Image

# Debug level with file output
pystream --pv 2bmSP2:Pva1:Image --log-level DEBUG --log-file viewer.log

# Error level only
pystream --pv 2bmSP2:Pva1:Image --log-level ERROR
```

Logger name: `pystream` (PyQtGraph), `pystream_vispy` (VisPy), or `pystream` (legacy)

---

## Directory Structure
```
pystream/
    pyqtgraph_viewer.py    # PyQtGraph viewer (SSH-compatible)
    pyqtstream.py          # VisPy viewer (GPU-accelerated)
    pystream.py            # Legacy Tkinter/Matplotlib viewer
    procplug.py            # Plugin pipeline loader
    logger.py              # Logging utilities
    pipelines/
        processors.json    # Default pipeline configuration
    plugins/               # Optional plugin directory
        sum.py
README.md
pyproject.toml
viewer_config.json         # Auto-generated PV persistence
```

---

## Troubleshooting

### VisPy OpenGL Errors over SSH

VisPy requires OpenGL which does not work over standard SSH X11 forwarding. Symptoms:
```
WARNING: QOpenGLWidget: Failed to create context
WARNING: composeAndFlush: makeCurrent() failed
```

Solutions:
- Use PyQtGraph viewer (default) for SSH access
- Use VirtualGL + TurboVNC for remote OpenGL
- Run locally with display forwarding disabled

### Plugin Not Loading

Check:
- JSON syntax is valid (no trailing commas, no comments)
- Module file exists on PYTHONPATH or in same directory
- Module name in JSON matches filename (sum.py → "module": "sum")
- Class name matches actual class in module
- Not using `--no-plugins` flag
- Processor class has both `__init__(**kwargs)` and `apply(img, meta)` methods

### Python Version Compatibility

Python 3.10+ recommended. For Python 3.8-3.9:
- Avoid PEP 604 union syntax (`dict | None`)
- Use `typing.Optional[dict]` instead

### Performance Issues

For high frame rates:
- Use PyQtGraph or VisPy viewer (not legacy)
- Increase `--auto-every` to reduce autoscale computation
- Use `--display-bin N` to decimate display (e.g., 2 or 4)
- Disable histogram updates: `--hist-fps 0`
- Disable plugins: `--no-plugins`

---

## Requirements

- Python 3.8+
- numpy >= 1.21
- PyQt5 >= 5.15
- pyqtgraph >= 0.13.0
- pvapy >= 5.6.0 (EPICS PVAccess client)

Optional:
- vispy >= 0.14.0 (for GPU-accelerated viewer)
- matplotlib >= 3.5 (for legacy viewer)
- Pillow >= 9.0 (for PNG export)

---
