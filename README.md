# PyStream

Real-time image viewer for EPICS PVAccess NTNDArray data with beamline-specific tools.

## Features

- **Real-time Streaming**: Live EPICS area detector visualization
- **Beamline Plugins**: Configurable facility-specific tools
- **Image Analysis**: Metrics, ROI, profiles, and measurements
- **Plugin Architecture**: Extensible processing pipeline

## Installation

```bash
# Basic installation
pip install pystream

# With beamline tools (e.g., bl32ID)
pip install pystream[bl32ID]
```

## Quick Start

```bash
pystream --pv YOUR:NTNDARRAY:PV
```

## Documentation

**📚 Full documentation:** https://pystream.readthedocs.io

## License

MIT License - Copyright (c) 2025 Alberto Mittone
