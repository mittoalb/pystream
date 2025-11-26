# Plugins

PyStream includes several plugins for image analysis, visualization, and control.

## Available Plugins

### Core Viewers

```{toctree}
:maxdepth: 1

viewer
```

**HDF5 Image Viewer** - Interactive viewer for HDF5 image data with flat-field correction and comprehensive metadata exploration.

### ROI and Measurement Tools

```{toctree}
:maxdepth: 1

roi
ellipse
line
scalebar
```

- **Rectangle ROI** - ImageJ-style rectangular ROI tool for selecting and analyzing rectangular regions
- **Ellipse ROI** - ImageJ-style ellipse/circle ROI tool with accurate ellipse masking
- **Line Profile** - Interactive line tool with shift-key constraints and intensity profile extraction
- **Scale Bar** - Dual scale bar system with automatic nice-number rounding and smart unit conversion

### Analysis and Processing

```{toctree}
:maxdepth: 1

console
metrics
mosalign
```

- **Python Console** - Interactive Python console for real-time custom image processing
- **Image Metrics** - Real-time monitoring of image information content metrics (entropy, focus, spectral stats)
- **Mosaic Alignment** - Automated 2D motor scanning with live stitched preview for sample alignment

## Plugin Categories

### Image Viewers
- [HDF5 Viewer](viewer.md) - View and normalize HDF5 image stacks with metadata exploration

### ROI Tools
- [Rectangle ROI](roi.md) - Rectangular region selection and statistics
- [Ellipse ROI](ellipse.md) - Elliptical/circular region selection with accurate masking
- [Line Profile](line.md) - Line drawing and intensity profile extraction

### Visualization
- [Scale Bar](scalebar.md) - Dual scale bar overlay with automatic scaling

### Processing
- [Python Console](console.md) - Real-time custom image processing with Python code

### Analysis
- [Image Metrics](metrics.md) - Live image quality and information content metrics

### Motor Control
- [Mosaic Alignment](mosalign.md) - Automated motor scanning with stitched preview