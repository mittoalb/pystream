# pystream - High-performance viewer for EPICS PVAccess NTNDArray data

Real-time image streaming and analysis from EPICS area detectors with PyQtGraph rendering.

## Key Features

- **Real-time Streaming**: Live image visualization from EPICS PVs
- **Distance Measurement**: Calibrated measurements in pixels, micrometers, and millimeters
- **Beamline Tools**: Auto-discovering plugins for facility-specific workflows
- **Image Analysis**: Metrics, ROI analysis, intensity profiles, and quality assessment
- **Motor Control**: Automated mosaic scanning with real-time stitching
- **Plugin Architecture**: Extensible processing pipeline

## Documentation

**Full documentation available at:** https://pystream.readthedocs.io/en/latest/index.html

## Quick Start

```bash
pip install pystream
pystream --pv YOUR:NTNDARRAY:PV
```

## Beamline Configuration

PyStream supports configurable beamline-specific plugins. Edit `src/pystream/beamline_config.py` to choose your beamline:

```python
# Load your beamline plugins
ACTIVE_BEAMLINE = 'bl32ID'

# Or disable beamline plugins
ACTIVE_BEAMLINE = None
```

See [BEAMLINE_CONFIG.md](BEAMLINE_CONFIG.md) for detailed configuration and creating custom beamlines.

## Recent Updates

### Enhanced Line Profile Tool
- Distance measurements in multiple units (px, µm, mm)
- ΔX and ΔY component measurements
- Calibrated physical distances with configurable pixel size

### Beamlines Plugin System
- Automatic discovery of beamline-specific tools
- Horizontal toolbar for easy access
- Modular architecture for facility customization

### UI Improvements
- Reset View, Beamlines, and HDF5 Viewer in top toolbar
- Improved layout for frequently-used controls
- Cleaner, more intuitive interface

### Bug Fixes
- Fixed mosalign starting position parameters
- Resolved NTNDArray empty value handling
- Corrected static method signatures
