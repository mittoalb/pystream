# NTNDArray Real-time Viewer (pystream)

High-performance viewer for EPICS PVAccess NTNDArray data with PyQtGraph rendering (SSH-compatible). Features interactive crosshair, recording to TIFF sequences, flat-field correction, and plugin pipeline.

---

## Installation

### 1. Create Conda Environment
```bash
conda create -n pystream python=3.10 numpy pyqt -c conda-forge
conda activate pystream
pip install pvapy pyqtgraph Pillow
```

### 2. Install Package
```bash
cd /path/to/pystream
pip install -e .
```

---

## Usage
```bash
# Basic usage
pystream --pv YOUR:NTNDARRAY:PV

# With options
pystream --pv 2bmSP2:Pva1:Image --max-fps 0 --log-level DEBUG
```
![PYSTREAM GUI](https://github.com/mittoalb/pystream/blob/main/GUI.png)

### Command-Line Options

| Option | Description | Default |
| ------ | ----------- | ------- |
| `--pv` | NTNDArray PV name | none |
| `--max-fps` | Maximum display FPS (0 = unlimited) | 0 |
| `--display-bin` | Decimation factor (0 = auto) | 0 |
| `--proc-config` | Plugin pipeline JSON path | pipelines/processors.json |
| `--no-plugins` | Disable plugin processing | off |
| `--log-level` | DEBUG/INFO/WARNING/ERROR | INFO |
| `--log-file` | Log file path | none |

---

## Features

### Interactive Crosshair
1. Check "Crosshair" in toolbar
2. Click/drag on image to position
3. View X, Y position and pixel value in left panel

### Recording
1. Set output directory in "Recording" panel
2. Set filename prefix (default: "frame")
3. Click "Start Recording"
4. Frames saved as individual TIFFs: `prefix_000001.tiff`, `prefix_000002.tiff`, etc.
5. Click "Stop Recording" when done

### Flat-Field Correction
- **Capture**: Save current frame as flat reference
- **Apply Flat**: Toggle correction on/off
- **Load/Save**: Import/export flat as .npy
- Formula: `I_norm = (I_raw / I_flat) * mean(I_flat)`

### Image Controls
- Flip H/V, Transpose
- Manual contrast sliders or autoscale
- Pause/Resume streaming
- Save single frame (.npy or .png)

---

## Plugin Pipeline

Plugins process each frame before display.

### Configuration Example

**pipelines/processors.json:**
```json
{
  "processors": [
    {
      "name": "MedianFilter",
      "module": "processors.filters",
      "class": "MedianFilter",
      "kwargs": {"kernel_size": 3}
    },
    {
      "name": "BackgroundSubtract",
      "module": "processors.background",
      "class": "BackgroundSubtract",
      "kwargs": {"method": "rolling", "window": 10}
    }
  ]
}
```

### Processor Template

**processors/myfilter.py:**
```python
import numpy as np

class MyFilter:
    def __init__(self, **kwargs):
        self.param = kwargs.get('param', 1.0)
    
    def apply(self, img: np.ndarray, meta: dict) -> np.ndarray:
        # meta contains: {"uid": frame_id, "timestamp": ts}
        return img * self.param
```

Processors execute top-to-bottom. Place plugins in `processors/` directory.

---

## Configuration

Settings saved to `~/.pystream/viewer_config.json`:
- Last used PV name (auto-connects on next launch)

---

## Directory Structure
```
pystream/
├── src/pystream/
│   ├── pyqtgraph_viewer.py
│   ├── logger.py
│   ├── procplug.py
│   └── pipelines/
│       └── processors.json
├── processors/          # User plugins here
├── pyproject.toml
└── README.md
```

---

## Requirements

- Python 3.8+
- numpy >= 1.21
- PyQt5 >= 5.15
- pyqtgraph >= 0.13.0
- pvapy >= 5.6.0
- Pillow >= 9.0

---

## Troubleshooting

**Script not found after install:**
```bash
hash -r
pystream --help
```

**Module import errors:**
Ensure relative imports in package files use `.logger` not `logger`.

**Performance issues:**
- Use `--display-bin 2` or `--display-bin 4`
- Increase `--auto-every 20`
- Disable plugins: `--no-plugins`

---

## License

MIT
