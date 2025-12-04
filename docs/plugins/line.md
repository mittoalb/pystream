# Line Profile Plugin

ImageJ-style line tool for drawing lines, measuring distances, and extracting intensity profiles from images.

## Overview

The Line Profile plugin provides:
- Interactive line drawing with endpoint and center handles
- **Shift-key constraint** for horizontal/vertical lines (ImageJ-style)
- **Distance measurement** in multiple units (pixels, micrometers, millimeters)
- **ΔX and ΔY measurements** for dimensional analysis
- Real-time line profile extraction
- Comprehensive line statistics (length, angle, intensity profile)
- Yellow visual styling for high visibility

## Features

### Visual Design
- **Yellow line**: Highly visible (3px width by default)
- **3 handles**:
  - 2 endpoint handles (red): Move line endpoints
  - 1 center handle (red): Drag entire line
- **Hover effect**: Line brightens when mouse hovers over it

### Controls

**Enable/Disable**
- Checkbox to toggle line tool visibility
- Line persists across image updates when enabled

**Drawing and Editing**
- **Drag endpoints**: Reposition line endpoints
- **Drag center**: Move entire line without changing orientation
- **Hold Shift while dragging**: Constrain to horizontal/vertical (ImageJ-style snap)
- **Reset button**: Return to default horizontal line at image center

### Shift-Key Snapping (ImageJ-style)

The line tool includes intelligent axis snapping when Shift is pressed:

1. **Press and hold Shift** while dragging an endpoint
2. The line automatically snaps to the closest axis (horizontal or vertical)
3. The anchor point (non-moving endpoint) stays fixed
4. The moving endpoint aligns to create a perfectly horizontal or vertical line

**Snapping Logic:**
- If `|dx| >= |dy|`: Snap to horizontal (same y as anchor)
- If `|dy| > |dx|`: Snap to vertical (same x as anchor)

This mimics ImageJ's line tool behavior for precise measurements.

### Statistics Display

Real-time statistics for the line:

**Distance Measurements**:
- **Length**: Total line length displayed in three units:
  - Pixels (px) - exact pixel distance
  - Micrometers (µm) - physical distance (requires pixel_size_um)
  - Millimeters (mm) - physical distance in millimeters
- **ΔX**: Horizontal component in all three units
- **ΔY**: Vertical component in all three units

**Line Geometry**:
- Start point: (x₁, y₁) coordinates
- End point: (x₂, y₂) coordinates
- Angle: 0-360° (0° = right, 90° = down)

**Intensity Profile**:
- Point count: Number of sampled points along the line
- Min, Max: Intensity range along the line
- Mean, Std: Statistical measures of the profile

**Note**: Physical distance measurements (µm, mm) require setting the pixel size. If not set, only pixel measurements are shown.

## Usage

### Basic Workflow

1. Enable the line tool checkbox
2. A default horizontal line appears at the image center
3. Drag endpoints to reposition
4. Hold Shift while dragging for horizontal/vertical snapping
5. Drag the center handle to move the entire line
6. View line statistics and intensity profile in the side panel

### Python API

```python
from pystream.plugins.line import LineProfileManager
import pyqtgraph as pg
from PyQt5 import QtWidgets

# Create image view
image_view = pg.ImageView()
stats_label = QtWidgets.QLabel()

# Create line profile manager
line_manager = LineProfileManager(
    image_view=image_view,
    stats_label=stats_label,
    handle_size=20,
    line_pen_width=3,
    pixel_size_um=1.3  # Set pixel size for physical distance measurements
)

# Set or update pixel size
line_manager.set_pixel_size(1.3)  # 1.3 µm/pixel

# Toggle visibility
line_manager.toggle(QtCore.Qt.Checked)

# Update with new image
import numpy as np
image = np.random.rand(512, 512)
line_manager.update_stats(image)

# Get line profile
profile = line_manager.get_line_profile(image)
if profile:
    positions, values = profile
    print(f"Profile length: {len(values)} points")
    print(f"Mean intensity: {values.mean():.2f}")

# Get line coordinates
coords = line_manager.get_line_coords()
if coords:
    print(f"Line from ({coords['x1']}, {coords['y1']}) to ({coords['x2']}, {coords['y2']})")

# Set line programmatically
line_manager.set_line_coords(x1=100, y1=150, x2=400, y2=150)

# Reset to default
line_manager.reset()

# Cleanup
line_manager.cleanup()
```

### Advanced Usage

**Extract and Plot Line Profile**
```python
import matplotlib.pyplot as plt

# Get line profile
profile = line_manager.get_line_profile(image)
if profile:
    positions, values = profile

    # Plot intensity profile
    plt.figure(figsize=(10, 4))
    plt.plot(positions, values, 'b-', linewidth=2)
    plt.xlabel('Distance (pixels)')
    plt.ylabel('Intensity')
    plt.title('Line Profile')
    plt.grid(True, alpha=0.3)
    plt.show()
```

**Custom Styling**
```python
line_manager = LineProfileManager(
    image_view=image_view,
    stats_label=stats_label,
    handle_size=25,          # Larger handles
    line_pen_width=4         # Thicker line
)
```

**Programmatic Line Control**
```python
# Draw horizontal line
line_manager.set_line_coords(x1=50, y1=256, x2=450, y2=256)

# Draw vertical line
line_manager.set_line_coords(x1=256, y1=50, x2=256, y2=450)

# Draw diagonal line
line_manager.set_line_coords(x1=100, y1=100, x2=400, y2=400)

# Get current coordinates
coords = line_manager.get_line_coords()
```

**Analyze Line Profile**
```python
profile = line_manager.get_line_profile(image)
if profile:
    positions, values = profile

    # Find peaks
    peak_idx = values.argmax()
    peak_pos = positions[peak_idx]
    peak_val = values[peak_idx]

    print(f"Peak at position {peak_pos}: {peak_val:.2f}")

    # Calculate gradient
    gradient = np.gradient(values)
    max_gradient_idx = np.abs(gradient).argmax()
    print(f"Max gradient at position {positions[max_gradient_idx]}")
```

## Implementation Details

### Line Profile Extraction

The plugin uses linear interpolation to sample intensity values along the line:

```python
# Calculate line length
length = int(sqrt((x2 - x1)² + (y2 - y1)²))

# Create evenly spaced points along line
x = linspace(x1, x2, length)
y = linspace(y1, y2, length)

# Sample image at these coordinates
x_int = clip(x.astype(int), 0, width - 1)
y_int = clip(y.astype(int), 0, height - 1)
values = image[y_int, x_int]
```

### Shift-Key Detection

The plugin uses a `ShiftKeyFilter` event filter to detect Shift key state:

1. Installed on application, view, scene, and line objects
2. Monitors `KeyPress` and `KeyRelease` events
3. Sets `_shift_pressed` flag for snapping logic
4. Non-consuming filter (doesn't block other key events)

### Handle Configuration

**Endpoint Handles** (2):
- Position: Line start and end points
- Type: Scale handles (resize line)
- Behavior: Move freely, snap with Shift

**Center Handle** (1):
- Position: Midpoint between endpoints
- Type: Translate handle (move entire line)
- Behavior: Moves both endpoints together
- Auto-updated when endpoints move

### Angle Calculation

Angle is calculated using `arctan2` and normalized to 0-360°:
```python
angle = degrees(arctan2(y2 - y1, x2 - x1))
if angle < 0:
    angle += 360
```

Convention:
- 0° = horizontal right (→)
- 90° = vertical down (↓)
- 180° = horizontal left (←)
- 270° = vertical up (↑)

## Technical Notes

- **Compatibility**: Works with all PyQtGraph versions
- **Parent item**: Line is parented to ImageItem for pixel-space alignment
- **Z-order**: Line at z=1000, handles at z=1001
- **Color scheme**: Yellow (RGB: 255, 255, 0) for line and handles
- **Sampling**: Uses integer pixel coordinates (nearest-neighbor interpolation)
- **Precision**: Sub-pixel positioning supported, rounded for display

## Use Cases

### Distance Measurement
- **Measure feature sizes**: Particle diameters, cell dimensions, structural features
- **Calibrated measurements**: Physical distances in micrometers and millimeters
- **Component separation**: ΔX and ΔY measurements for dimensional analysis
- **Multi-scale analysis**: View measurements in pixels, µm, and mm simultaneously

### Scientific Measurements
- Measure distance between features
- Extract intensity profiles across edges
- Analyze gradients and transitions
- Quantify line-like structures

### Quality Control
- Measure line widths
- Check edge sharpness
- Validate contrast
- Inspect uniformity

### Image Analysis
- Cross-section analysis
- Profile comparison
- Edge detection verification
- Feature characterization

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Shift + Drag | Constrain to horizontal/vertical |
| (No special keys) | Free-form line drawing |

## Tips

1. **For horizontal lines**: Hold Shift while dragging endpoints
2. **For precise positioning**: Use the Python API to set exact coordinates
3. **For smooth profiles**: Draw longer lines to get more sampling points
4. **For quick resets**: Use the Reset button to start over
