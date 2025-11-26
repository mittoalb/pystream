# HDF5 Image Viewer

Interactive viewer for HDF5 image data with flat-field correction and comprehensive metadata exploration.

## Quick Start

```bash
viewer
```

![Viewer plugin](./../Images/viewer.png)

## Overview

The HDF5 Image Viewer provides a two-tab interface for:
1. **Image Viewer** - Real-time image division with normalization and contrast control
2. **Metadata** - Comprehensive HDF5 file exploration and export capabilities

## Usage

### Load File
Click "Load HDF5 File" and select a file with:
- `/exchange/data` - Raw images (projections)
- `/exchange/data_white` - White field images (flat-field reference)

The viewer will display dataset information including shapes and total number of images.

### Image Viewer Tab

#### Image Selection
- **Slider**: Navigate through the image stack
- **Image Index**: Displays current frame number

#### Normalization
- **Checkbox**: Enable/disable flat-field correction (data / data_white)
- **Mode Display**: Shows current mode (Division or Raw Data Only)

When normalization is enabled, the viewer divides each projection by the corresponding white field image to correct for illumination variations and detector response.

#### Contrast Control
Control how image intensity levels are displayed:

- **Per Image (default)**: Auto-adjust levels for each image independently
- **Min/Max**: Use the full data range of the current image
- **Percentile 1-99%**: Clip outliers, use 1st to 99th percentile
- **Percentile 2-98%**: Moderate outlier clipping (recommended for most data)
- **Percentile 5-95%**: Aggressive outlier clipping for high-contrast visualization
- **Manual**: Manually set min/max display levels with spinboxes

**Auto Adjust Now** button: Reapply the current contrast mode immediately.

#### Shift Control (Normalization Mode Only)
Fine-tune alignment between data and white field images:

- **Arrow keys** (← → ↑ ↓): Shift white field by 1 pixel
- **Shift + arrows**: Shift by 10 pixels
- **Ctrl + arrows**: Shift by 50 pixels
- **Reset Shift** button: Return to zero shift

Current shift values are displayed in real-time (X and Y shift in pixels).

#### Image Statistics
Real-time statistics for the displayed image:
- **Min**: Minimum pixel value
- **Max**: Maximum pixel value
- **Mean**: Average pixel value
- **Std Dev**: Standard deviation

### Metadata Tab

The metadata viewer provides comprehensive HDF5 file exploration:

#### Attributes View
- **Filterable table**: Search for specific attributes by typing in the filter box
- **Three columns**:
  - Path/Attribute: Full HDF5 path to the metadata field
  - Value: The metadata value (with units if available)
  - Type: Data type (string, float64, int32, etc.)
- **Sortable**: Click column headers to sort
- **Export to CSV**: Export all metadata to a CSV file for external analysis

#### File Structure View
- **Tree view**: Hierarchical display of all HDF5 groups and datasets
- **Four columns**:
  - Path: Full path in the HDF5 file
  - Type: Group or Dataset
  - Shape: Array dimensions (for datasets)
  - Dtype: Data type (for datasets)

The metadata viewer uses the meta-cli approach, automatically extracting metadata from all HDF5 datasets (excluding 'exchange' and 'defaults' sections to focus on experimental metadata).

### Example Workflow

1. Load HDF5 file with projections and white fields
2. Enable normalization to apply flat-field correction
3. Select "Percentile 2-98%" for optimal contrast
4. Use arrow keys to fine-tune alignment between data and white fields
5. Navigate through the stack with the slider
6. Switch to Metadata tab to explore experimental parameters
7. Filter metadata by typing keywords (e.g., "energy", "exposure")
8. Export metadata to CSV for documentation

## Python API

### Basic Usage

```python
from pystream.plugins.viewer import HDF5ImageDividerDialog
from PyQt5 import QtWidgets

app = QtWidgets.QApplication([])
dialog = HDF5ImageDividerDialog()
dialog.show()
app.exec_()
```

### Programmatic Control

```python
from pystream.plugins.viewer import HDF5ImageDividerDialog
from PyQt5 import QtWidgets

app = QtWidgets.QApplication([])
dialog = HDF5ImageDividerDialog()

# Load file programmatically (not directly supported - use GUI)
dialog.show()

# Access internal state
print(f"Current index: {dialog.current_index}")
print(f"Shift: ({dialog.shift_x}, {dialog.shift_y})")
print(f"Normalization enabled: {dialog.normalization_enabled}")

app.exec_()
```

## Features Summary

- ✓ Virtual HDF5 file access (memory efficient, no full loading)
- ✓ Real-time flat-field correction (data / data_white)
- ✓ Sub-pixel alignment with keyboard controls
- ✓ Multiple contrast modes (percentile, min/max, manual)
- ✓ Comprehensive metadata viewer with filtering
- ✓ File structure tree view
- ✓ CSV metadata export
- ✓ Real-time image statistics
- ✓ Dark theme UI optimized for image viewing
