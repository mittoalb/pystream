# Scale Bar Plugin

Dual scale bar system for displaying measurement scales on images with configurable pixel sizes and units.

## Overview

The Scale Bar plugin provides:
- **Dual scale bars**: Two independent scale bars with different pixel sizes
- Automatic nice-number rounding (1, 2, 5, 10, 20, 50, 100, etc.)
- Smart unit conversion (nm → µm, µm → mm, mm → m)
- Configurable position, color, and appearance
- Real-time updates based on image dimensions

## Features

### Dual Scale Bar System

The plugin supports two independent scale bars that can be displayed simultaneously:

**Scale Bar 1** (Default):
- Primary scale bar
- Configurable pixel size
- White color by default
- Bottom position

**Scale Bar 2** (Secondary):
- Secondary scale bar (10× the primary scale by default)
- Yellow color by default
- Stacked 40 pixels above primary bar
- Useful for showing multiple magnifications

### Visual Design
- **Solid colored bars**: White, yellow, or custom colors
- **Text labels**: Auto-formatted with appropriate precision
- **Smart positioning**: 4 corner positions available
- **Vertical stacking**: Multiple bars can be stacked without overlap
- **High visibility**: Bold fonts and solid colors

### Automatic Features

**Nice Number Rounding**
Scale bars automatically round to visually appealing values:
- 1, 2, 5 (for small scales)
- 10, 20, 50 (for medium scales)
- 100, 200, 500 (for large scales)
- And so on...

**Unit Conversion**
Automatically converts to larger units when appropriate:
- 1000 nm → 1.0 µm
- 1000 µm → 1.0 mm
- 1000 mm → 1.0 m

**Dynamic Sizing**
Bar width adapts to image size (default: 25% of image width)

## Usage

### Basic Workflow

1. Enable the scale bar checkbox (shows both bars if individually enabled)
2. Click "Settings" to configure pixel size and appearance
3. Scale bars automatically update with image changes
4. Toggle individual bars on/off in settings dialog

### Settings Dialog

The settings dialog provides complete control over both scale bars:

**Scale Bar 1 Tab**:
- Enable/disable checkbox
- Pixel size and unit (nm, µm, mm, m, Å, px)
- Position (bottom-right, bottom-left, top-right, top-left)
- Color (white, black, yellow, red, green, blue, cyan, magenta)
- Bar width (10-50% of image width)
- Vertical offset (0-200 pixels)

**Scale Bar 2 Tab**:
- Same controls as Scale Bar 1
- Independent configuration
- Can be stacked with different offset

**Buttons**:
- Apply Scale Bar 1/2: Apply settings for one bar
- Apply All: Apply settings for both bars
- Close: Close dialog

### Python API

```python
from pystream.plugins.scalebar import ScaleBarManager
import pyqtgraph as pg

# Create image view
image_view = pg.ImageView()

# Create scale bar manager
scalebar_manager = ScaleBarManager(
    image_view=image_view,
    pixel_size=0.65,          # 0.65 nm per pixel
    unit="nm",
    position="bottom-right",
    color="white"
)

# Toggle visibility (both bars)
scalebar_manager.toggle(QtCore.Qt.Checked)

# Update with image
import numpy as np
image = np.random.rand(2048, 2048)
scalebar_manager.update_image(image)

# Set pixel size
scalebar_manager.set_pixel_size(pixel_size=0.65, unit="nm")

# Access individual bars
bar1 = scalebar_manager.get_scale_bar(1)
bar2 = scalebar_manager.get_scale_bar(2)

# Configure bar 2 independently
bar2.pixel_size = 6.5  # 10× the primary scale
bar2.color = "yellow"
bar2.vertical_offset = 50

# Cleanup
scalebar_manager.cleanup()
```

### Advanced Usage

**Independent Bar Control**
```python
# Enable/disable bars individually
scalebar_manager.toggle_bar_1(QtCore.Qt.Checked)
scalebar_manager.toggle_bar_2(QtCore.Qt.Unchecked)  # Hide bar 2

# Configure bar 1
bar1 = scalebar_manager.scale_bar_1
bar1.pixel_size = 0.5
bar1.unit = "nm"
bar1.color = "white"
bar1.position = "bottom-right"
bar1.bar_width_fraction = 0.2  # 20% of image width

# Configure bar 2 with different scale
bar2 = scalebar_manager.scale_bar_2
bar2.pixel_size = 5.0  # Different magnification
bar2.unit = "nm"
bar2.color = "yellow"
bar2.vertical_offset = 60  # Stack above bar 1

# Update display
scalebar_manager.update_image(image)
```

**Custom Styling**
```python
scalebar_manager = ScaleBarManager(
    image_view=image_view,
    pixel_size=1.2,
    unit="µm",
    bar_width_fraction=0.3,   # 30% of image width
    position="top-left",
    bar_height=10,            # Thicker bar
    font_size=14,             # Larger font
    color="cyan",
    margin=30                 # More margin from edge
)
```

**Multiple Magnifications**
```python
# Show scale bars for different zoom levels
# Primary bar: 1:1 scale
bar1.pixel_size = 1.0
bar1.unit = "µm"
bar1.color = "white"

# Secondary bar: 10× zoomed scale
bar2.pixel_size = 0.1
bar2.unit = "µm"
bar2.color = "yellow"
bar2.vertical_offset = 50

scalebar_manager.update_image(image)
```

## Implementation Details

### Nice Scale Calculation

The `_get_nice_scale()` method rounds to visually appealing values:

```python
# Normalize to order of magnitude
magnitude = 10^floor(log10(value))
normalized = value / magnitude

# Round to nice number
if normalized < 1.5:    nice = 1.0
elif normalized < 3.5:  nice = 2.0
elif normalized < 7.5:  nice = 5.0
else:                   nice = 10.0

return nice × magnitude
```

**Example:**
- 127 → 100
- 247 → 200
- 683 → 500
- 1842 → 2000

### Text Formatting

Smart precision based on value magnitude:

```python
if value >= 1000:
    # Convert to next unit (e.g., nm → µm)
    return f"{value/1000:.1f} µm"
elif value >= 100:
    return f"{int(value)} nm"
elif value >= 10:
    return f"{value:.1f} nm"
else:
    return f"{value:.2f} nm"
```

### Position Calculation

Scale bars are positioned relative to image corners:

| Position | X Coordinate | Y Coordinate |
|----------|--------------|--------------|
| bottom-right | `width - bar_width - margin` | `height - bar_height - margin - offset` |
| bottom-left | `margin` | `height - bar_height - margin - offset` |
| top-right | `width - bar_width - margin` | `margin + offset` |
| top-left | `margin` | `margin + offset` |

The `vertical_offset` parameter allows stacking multiple bars.

### Z-Order

- Bar rectangle: z = 2000
- Bar text: z = 2001

This ensures scale bars appear above images and ROIs.

## Configuration Examples

### Electron Microscopy (nm scale)
```python
scalebar_manager.set_pixel_size(pixel_size=0.5, unit="nm")
# Shows: "100 nm", "500 nm", etc.
```

### Light Microscopy (µm scale)
```python
scalebar_manager.set_pixel_size(pixel_size=0.1, unit="µm")
# Shows: "10 µm", "50 µm", etc.
```

### Macro Photography (mm scale)
```python
scalebar_manager.set_pixel_size(pixel_size=0.05, unit="mm")
# Shows: "5 mm", "10 mm", etc.
```

### Dual Scale Setup
```python
# Fine scale (primary)
bar1.pixel_size = 0.2
bar1.unit = "µm"
bar1.color = "white"
bar1.vertical_offset = 0

# Coarse scale (secondary)
bar2.pixel_size = 2.0
bar2.unit = "µm"
bar2.color = "yellow"
bar2.vertical_offset = 50
```

## Technical Notes

- **Graphics items**: Uses `QGraphicsRectItem` for bar, `TextItem` for label
- **Parent item**: Scale bars parented to ImageItem for pixel-space alignment
- **Update mechanism**: Bars recalculate on image dimension change
- **Backward compatibility**: Single toggle controls both bars, maintains old API
- **Default values**:
  - Bar width: 25% of image width
  - Bar height: 8 pixels
  - Font size: 12pt, bold
  - Margin: 20 pixels
  - Primary offset: 0 pixels
  - Secondary offset: 40 pixels

## Use Cases

### Multi-Scale Imaging
Display two scale bars for:
- Original and zoomed views
- Different magnifications
- Reference scales

### Publication Figures
- Professional scale bars
- Customizable colors for different backgrounds
- Precise positioning

### Microscopy
- nm, µm, mm scales
- Auto-conversion between units
- Consistent sizing across images

### Image Analysis
- Reference for measurements
- Visual size estimation
- Calibration validation

## Tips

1. **For dark images**: Use white or yellow scale bars
2. **For bright images**: Use black scale bars
3. **For stacking**: Increase `vertical_offset` to prevent overlap
4. **For publications**: Use `bar_width_fraction=0.2` for compact bars
5. **For presentations**: Use `font_size=16` for better visibility
