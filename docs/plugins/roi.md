# Rectangle ROI Plugin

ImageJ-style rectangular ROI tool for selecting and analyzing rectangular regions in images.

## Overview

The Rectangle ROI plugin provides:
- 8 prominent red handles (4 corners + 4 edges) for precise resizing
- Real-time dimension display overlay
- Rectangular selection with pixel-perfect accuracy
- Live statistics for selected region
- Professional appearance with bright, visible handles

## Features

### Visual Design
- **Yellow outline**: Highly visible rectangle boundary (2px width by default)
- **8 red handles with white borders**: Maximum visibility for precise control
  - 4 corner handles: Diagonal resizing
  - 4 edge handles: Single-axis resizing (top, bottom, left, right)
- **Dimension overlay**: Real-time width × height display above the rectangle
- **Professional styling**: Similar to ImageJ's ROI tools

### Controls

**Enable/Disable**
- Checkbox to toggle rectangle ROI visibility
- ROI persists across image updates when enabled

**Resize and Move**
- **Drag corner handles**: Resize diagonally
- **Drag edge handles**: Resize along one axis (horizontal or vertical)
- **Drag center**: Move the entire rectangle without resizing
- **Reset button**: Return to default size and position (centered, 1/4 of image size)

### Statistics Display

Real-time statistics for pixels inside the rectangle:
- **Position**: X, Y coordinates of top-left corner
- **Size**: Width, Height in pixels
- **Pixel count**: Total number of pixels in the ROI
- **Intensity Stats**:
  - Min, Max: Intensity range
  - Mean, Std: Statistical measures
  - Sum: Total intensity

## Usage

### Basic Workflow

1. Enable the rectangle ROI checkbox
2. A default rectangle appears at the image center
3. Drag corner handles for diagonal resizing
4. Drag edge handles for single-axis resizing
5. Drag the center to reposition
6. View real-time statistics in the side panel

### Python API

```python
from pystream.plugins.roi import ROIManager
import pyqtgraph as pg
from PyQt5 import QtWidgets

# Create image view
image_view = pg.ImageView()
stats_label = QtWidgets.QLabel()

# Create ROI manager
roi_manager = ROIManager(
    image_view=image_view,
    stats_label=stats_label,
    handle_size=10,
    roi_pen_width=2,
    show_dimensions=True
)

# Toggle visibility
roi_manager.toggle(QtCore.Qt.Checked)

# Update with new image
import numpy as np
image = np.random.rand(512, 512)
roi_manager.update_stats(image)

# Get ROI data (rectangular cutout)
roi_data = roi_manager.get_roi_data(image)
print(f"ROI shape: {roi_data.shape}")

# Get ROI bounds
bounds = roi_manager.get_roi_bounds()
print(f"Position: ({bounds['x']}, {bounds['y']})")
print(f"Size: {bounds['width']} × {bounds['height']}")

# Set ROI programmatically
roi_manager.set_roi_bounds(x=100, y=100, width=200, height=150)

# Reset to default
roi_manager.reset()

# Cleanup
roi_manager.cleanup()
```

### Advanced Usage

**Custom Styling**
```python
roi_manager = ROIManager(
    image_view=image_view,
    stats_label=stats_label,
    handle_size=15,          # Larger handles
    roi_pen_width=3,         # Thicker outline
    show_dimensions=False    # Hide dimension overlay
)
```

**Extract ROI Data**
```python
# Get rectangular cutout from image
roi_data = roi_manager.get_roi_data(image)

# roi_data is a 2D numpy array containing the selected rectangle
# Can be used for further analysis, saving, etc.

# Process ROI data
mean_intensity = roi_data.mean()
max_intensity = roi_data.max()
```

**Programmatic ROI Control**
```python
# Set specific ROI bounds
roi_manager.set_roi_bounds(x=50, y=50, width=300, height=200)

# Get current bounds
bounds = roi_manager.get_roi_bounds()
if bounds:
    x, y = bounds['x'], bounds['y']
    w, h = bounds['width'], bounds['height']
    print(f"ROI at ({x}, {y}) with size {w}×{h}")
```

## Implementation Details

### Handle Configuration
The plugin uses PyQtGraph's `RectROI` with 8 handles for full control:

**Corner Handles** (4):
- Top-Left: anchor at bottom-right
- Top-Right: anchor at bottom-left
- Bottom-Left: anchor at top-right
- Bottom-Right: anchor at top-left

**Edge Handles** (4):
- Top-Center: anchor at bottom (vertical resize)
- Bottom-Center: anchor at top (vertical resize)
- Left-Center: anchor at right (horizontal resize)
- Right-Center: anchor at left (horizontal resize)

### Handle Styling
- **Brush**: Bright red (RGB: 255, 0, 0, 255)
- **Pen**: White border (3px width) for maximum visibility
- **Size**: 2× the configured handle_size parameter
- **Z-order**: Handles rendered above ROI (zValue + 1)

### ROI Extraction
Uses PyQtGraph's `getArraySlice()` method for efficient rectangular data extraction:
```python
roi_slice, _ = roi.getArraySlice(image, image_item)
roi_data = image[roi_slice[0], roi_slice[1]]
```

### Performance
- Virtual ROI (no data copying until requested)
- Real-time statistics update on drag
- Efficient slice-based extraction
- Minimal memory overhead

## Technical Notes

- **Compatibility**: Simplified version guaranteed to work with all PyQtGraph versions
- **Parent item**: ROI is parented to ImageItem for pixel-space alignment
- **Z-order**: ROI at z=1000, handles at z=1001, dimension text at z=2000
- **Color scheme**:
  - Outline: Yellow (for consistency with other tools)
  - Handles: Red with white borders (for maximum visibility)
- **Dimension text**: Yellow text on semi-transparent black background

## Comparison with Ellipse ROI

| Feature | Rectangle ROI | Ellipse ROI |
|---------|---------------|-------------|
| Shape | Rectangular | Elliptical/Circular |
| Handles | 8 (corners + edges) | 8 (axes + diagonals) |
| Handle Color | Red | Yellow |
| Data Extraction | Rectangular slice | Masked ellipse pixels |
| Area Calculation | Width × Height | π × a × b |
| Use Case | General rectangular selections | Circular/elliptical features |
