# PyStream Documentation

![logo](./Images/logo.png)

PyStream is a Python package for real-time image streaming, processing, and analysis from EPICS area detectors.

## Features

- **Real-time Streaming**: Live image visualization from EPICS PVs
- **High-Speed Recording**: RAM-buffered TIFF sequence capture with non-blocking I/O (tested at 50 FPS with 2048×2048 images)
- **Image Analysis**: Information metrics, quality assessment, focus detection, distance measurement
- **Motor Control**: Automated mosaic scanning and alignment
- **HDF5 Tools**: Virtual loading and flat-field correction
- **Plugin Architecture**: Extensible processing pipeline
- **Beamlines System**: Auto-discovery of beamline-specific tools

## Contents

```{toctree}
:maxdepth: 2

quickstart
plugins/index
beamlines/index
api
```
