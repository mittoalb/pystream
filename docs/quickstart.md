# Quick Start

## Installation

```bash
pip install pystream
```

## Real-time Image Viewer

View live images from EPICS area detector:

```bash
pystream --pv SIMPS:IMG
```

Features:
- Real-time streaming
- Auto-scaling and histogram
- ROI analysis
- Line profiles
- Image processing pipeline

## HDF5 Viewer

View and normalize HDF5 tomography data:

```bash
viewer
```

Features:
- Virtual HDF5 loading (memory efficient)
- Flat-field correction (data / data_white)
- Interactive shift alignment
- Multiple contrast modes

## Image Quality Metrics

Monitor image information and focus quality:

```bash
imageinfo --pv YOUR_PV
```

Features:
- Real-time metric plots
- Shannon entropy, focus metrics
- Interest detection
- Tomography mode
- Export interesting frames

## Mosaic Alignment

Automated 2D motor scanning with stitching:

```bash
mosalign
```

Features:
- EPICS motor control
- Real-time stitching preview
- Configurable overlap
- Tomoscan integration

## Python API

All plugins can be used programmatically:

```python
from pystream.plugins.viewer import HDF5ViewerDialog
from pystream.plugins.imageinfo import ImageInfoDialog
from pystream.plugins.mosalign import MotorScanDialog

# Create and show any plugin
dialog = HDF5ViewerDialog()
dialog.show()
```

## Next Steps

- [Plugin Documentation](plugins/index.md)
- [API Reference](api.md)
- [Installation Guide](installation.md)
