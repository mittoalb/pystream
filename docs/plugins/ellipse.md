# Ellipse ROI Plugin

ImageJ-style ellipse/circle ROI tool for selecting and analyzing elliptical regions in images.

## Overview

The Ellipse ROI plugin provides:
- 8 prominent yellow handles (4 corners + 4 edges) for resizing
- Real-time dimension display overlay
- Accurate ellipse masking (only pixels inside the ellipse)
- Professional appearance with customizable styling
- Live statistics for selected region

## Features

### Visual Design
- **Yellow outline**: Highly visible ellipse boundary (3px width by default)
- **8 handles**: Full control over ellipse shape and size
  - 4 axis handles (0°, 90°, 180°, 270°): Stretch along one axis only
  - 4 diagonal handles (45°, 135°, 225°, 315°): Scale uniformly
- **Dimension overlay**: Real-time width × height display above the ellipse
- **Shape indicator**: Shows ⭕ for circles, ⬭ for ellipses

### Controls

**Enable/Disable**
- Checkbox to toggle ellipse ROI visibility
- ROI persists across image updates when enabled

**Resize and Move**
- **Drag handles**: Resize the ellipse
  - Axis handles: Stretch horizontally or vertically
  - Diagonal handles: Scale uniformly while maintaining aspect ratio
- **Drag center**: Move the entire ellipse
- **Reset button**: Return to default size and position (centered, 1/4 of image size)

### Statistics Display

Real-time statistics for pixels inside the ellipse:
- **Position**: X, Y coordinates of top-left corner
- **Size**: Width, Height in pixels
- **Shape**: Circle or Ellipse classification
- **Geometry**:
  - Area: Calculated using πab (exact ellipse area)
  - Perimeter: Ramanujan approximation
  - Pixel count: Number of pixels inside the ellipse
- **Intensity Stats**:
  - Min, Max: Intensity range
  - Mean, Std: Statistical measures
  - Sum: Total intensity

## Usage

### Basic Workflow

1. Enable the ellipse ROI checkbox
2. A default ellipse appears at the image center
3. Drag handles to resize or reshape the ellipse
4. Drag the center to reposition
5. View real-time statistics in the side panel

### Python API

```python
from pystream.plugins.ellipse import EllipseROIManager
import pyqtgraph as pg
from PyQt5 import QtWidgets

# Create image view
image_view = pg.ImageView()
stats_label = QtWidgets.QLabel()

# Create ellipse ROI manager
ellipse_manager = EllipseROIManager(
    image_view=image_view,
    stats_label=stats_label,
    handle_size=12,
    roi_pen_width=3,
    show_dimensions=True
)

# Toggle visibility
ellipse_manager.toggle(QtCore.Qt.Checked)

# Update with new image
import numpy as np
image = np.random.rand(512, 512)
ellipse_manager.update_stats(image)

# Get ROI data (pixels inside ellipse only)
roi_data = ellipse_manager.get_roi_data(image)

# Get ROI bounds
bounds = ellipse_manager.get_roi_bounds()
print(f"Position: ({bounds['x']}, {bounds['y']})")
print(f"Size: {bounds['width']} × {bounds['height']}")

# Set ROI programmatically
ellipse_manager.set_roi_bounds(x=100, y=100, width=150, height=200)

# Reset to default
ellipse_manager.reset()

# Cleanup
ellipse_manager.cleanup()
```

### Advanced Usage

**Custom Styling**
```python
ellipse_manager = EllipseROIManager(
    image_view=image_view,
    stats_label=stats_label,
    handle_size=15,          # Larger handles
    roi_pen_width=4,         # Thicker outline
    show_dimensions=False    # Hide dimension overlay
)
```

**Extract Ellipse Mask**
```python
# Get only pixels inside the ellipse
roi_data = ellipse_manager.get_roi_data(image)

# roi_data is a 1D array containing only pixels where:
# ((x - cx) / a)^2 + ((y - cy) / b)^2 <= 1
# where a and b are semi-major and semi-minor axes
```

## Implementation Details

### Ellipse Masking
The plugin uses accurate ellipse masking based on the mathematical equation:

```
((x - cx) / a)^2 + ((y - cy) / b)^2 <= 1
```

Where:
- `(cx, cy)` = center of ellipse
- `a` = semi-major axis (width / 2)
- `b` = semi-minor axis (height / 2)

Only pixels satisfying this equation are included in statistics and data extraction.

### Handle Configuration
- **Axis handles** (4): Fixed opposite anchor, stretch along one dimension
- **Diagonal handles** (4): Positioned on ellipse circumference at 45° intervals, scale uniformly from center

### Performance
- Virtual ROI (no data copying until requested)
- Real-time statistics update on drag
- Efficient numpy-based ellipse masking

## Technical Notes

- **Compatibility**: Works with all PyQtGraph versions
- **Parent item**: ROI is parented to ImageItem for pixel-space alignment
- **Z-order**: ROI at z=1000, handles at z=1001, dimension text at z=2000
- **Color scheme**: Yellow (RGB: 255, 255, 0) for high visibility
- **Shape detection**: Automatically detects circular vs elliptical based on width/height difference < 2 pixels
