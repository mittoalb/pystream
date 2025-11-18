# Image Information Metrics

Real-time monitoring of image quality and information content metrics.

## Overview

The Image Info plugin analyzes image streams to detect interesting frames, measure focus quality, and track information content changes over time.

## Quick Start

```bash
imageinfo --pv YOUR_PV_NAME
```

Or from Python:

```python
from pystream.plugins.imageinfo import ImageInfoDialog

dialog = ImageInfoDialog()
dialog.show()
```

## Features

### Information Metrics

**Shannon Entropy**
- Measures information content (bits/pixel)
- Higher values = more information/detail

**Normalized Entropy**
- Shannon entropy normalized to 0-1 range
- Independent of bit depth

**Laplacian Variance**
- Focus/sharpness measure
- Higher values = sharper/more focused

**Gradient Magnitude**
- Edge and detail content
- Sensitive to noise and features

**Spectral Entropy**
- Frequency domain information content
- Detects texture and patterns

**Spectral Centroid**
- Center of mass of frequency spectrum
- Higher values = more high-frequency content

**High Frequency Energy**
- Ratio of high to total frequency energy
- Sharpness indicator (0-1)

**Spectral Flatness**
- Wiener entropy measure
- Near 1 = noise-like, near 0 = tonal

**Zlib Compressibility**
- Compressed bytes per pixel
- Lower values = more compressible/redundant

**Mutual Information** (optional)
- Similarity to reference frame
- Requires setting a reference frame

## Usage

### Basic Monitoring

1. Enter PV name
2. Click "Start Monitoring"
3. Watch real-time metric plots
4. Metrics update as frames arrive

### Interest Detection

**Purpose**: Automatically identify frames with significant content changes

**Controls:**
- **Interest Threshold**: Frames above this score are marked as "interesting"
- **List Interesting Frames**: View all detected interesting frames
- **Export to CSV**: Save list for later analysis

**Interest Score Calculation:**
- Weighted combination of multiple metrics
- Detects focus changes, motion, and content variations

### Tomography Mode

For tomography scans with rotation:

1. Enable "Tomography Mode"
2. Set angle parameters:
   - Start angle (degrees)
   - End angle (degrees)
   - Angular spacing (degrees/projection)
3. Plots show metrics vs angle instead of time

### Reference Frame

Set a reference frame to compute mutual information:

1. Let monitoring run to capture frames
2. Click "Set Current Frame as Reference"
3. Mutual information now computed relative to this frame
4. Useful for detecting drift or changes

## Keyboard Shortcuts

- `Space`: Pause/resume monitoring
- `R`: Set current frame as reference
- `I`: Show interesting frames list
- `E`: Export interesting frames to CSV

## Metric Interpretation

### Focus Quality
- **Laplacian Variance**: Primary focus metric
- **High Frequency Energy**: Secondary focus indicator
- **Gradient Magnitude**: Overall sharpness

High values = good focus, sharp image

### Information Content
- **Shannon Entropy**: Overall information
- **Spectral Entropy**: Frequency diversity
- **Zlib Compressibility**: Redundancy (lower = more redundant)

High entropy = more information/complexity

### Change Detection
- **Mutual Information**: Similarity to reference
- Watch for sudden drops = significant change

### Quality Assessment
- **Spectral Flatness**: Near 0.5-0.7 typical for images
- Very high (>0.9) = mostly noise
- Very low (<0.2) = very uniform/simple

## Export Format

CSV columns:
- `frame_number`: Frame index (1-indexed)
- `angle_degrees`: Rotation angle (tomography mode only)
- `time_seconds`: Timestamp
- `interest_score`: Combined interest metric
- All individual metrics (shannon_entropy, laplacian_variance, etc.)

## Python API

```python
from pystream.plugins.imageinfo import ImageInfoDialog

# Create dialog
dialog = ImageInfoDialog()

# Set PV programmatically
dialog.pv_input.setText("YOUR_PV")

# Enable tomography mode
dialog.chk_tomography.setChecked(True)
dialog.angle_start_spin.setValue(0.0)
dialog.angle_end_spin.setValue(180.0)
dialog.angular_spacing_spin.setValue(0.12)

# Start monitoring
dialog._start_monitoring()

# Show
dialog.show()
```

## Use Cases

### Focus Optimization
Monitor Laplacian variance while adjusting focus. Peak value = optimal focus.

### Tomography Quality Control
Watch metrics during scan to detect:
- Poor focus
- Motion blur
- Sample drift
- Missing projections

### Content Change Detection
Set reference frame at start. Monitor mutual information to detect:
- Sample changes
- Lighting changes
- Drift or motion

### Frame Selection
Export interesting frames list to identify:
- Key transition points
- Optimal sample positions
- Frames with artifacts

## Requirements

- pvaccess (EPICS Channel Access)
- scipy (optional, for better performance)
- numpy, PyQt5, pyqtgraph
