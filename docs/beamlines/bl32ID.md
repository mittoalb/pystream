# bl32ID Beamline Plugins

Advanced Photon Source beamline 32-ID specialized tools for tomography and imaging.

## Overview

The bl32ID beamline package provides three specialized tools for detector control, beam position monitoring, and motor alignment:

- **Detector Control**: Manage camera binning and ROI settings
- **SoftBPM**: Software beam position monitor with automatic motor adjustment
- **Mosalign**: 2D motor scanning with image stitching

## Detector Control

Controls detector binning and region-of-interest (ROI) for the area detector camera.

### Features

- **Binning Control**: Set X and Y binning factors (1-16)
- **ROI Drawing**: Interactive ROI rectangle on live image
- **Direct PV Control**: Apply settings directly to detector PVs
- **Real-time Feedback**: Read and display current detector settings

### Controlled PVs

The plugin controls the following EPICS PVs (default prefix: `32idbSP1:cam1`):

| PV | Description |
|---|---|
| `BinX` | X-axis binning factor |
| `BinY` | Y-axis binning factor |
| `MinX` | ROI minimum X position (unbinned pixels) |
| `MinY` | ROI minimum Y position (unbinned pixels) |
| `SizeX` | ROI width (automatically updated with binning) |
| `SizeY` | ROI height (automatically updated with binning) |

### Usage

1. **Open the Plugin**
   - Click "Detectorcontrol" button in the bl32ID beamlines toolbar

2. **Set Binning**
   - Adjust BinX and BinY spinboxes (range: 1-16)
   - Click "Apply Binning" to push values to detector
   - Click "Read Current" to verify settings

3. **Draw and Apply ROI**
   - Click "Enable ROI Drawing" to show interactive ROI
   - Red rectangle appears on the live image
   - Drag corners/edges to resize
   - Drag center to reposition
   - Click "Apply ROI to Detector" to push coordinates to detector PVs

4. **Reset ROI**
   - Click "Reset ROI" to center ROI at 50% of image size

### Notes

- **Binning updates Size**: When binning changes, SizeX/SizeY automatically update to reflect the binned dimensions
- **Unbinned coordinates**: ROI coordinates (MinX, MinY) are always in unbinned pixel units
- **PV Prefix**: The camera PV prefix can be changed in the dialog if using a different detector
- **Live image required**: ROI drawing requires a live image from the parent viewer

### Example Workflow

```
1. Set binning to 2x2 for faster readout
2. Enable ROI drawing
3. Adjust ROI to region of interest (e.g., sample area)
4. Apply ROI to detector
5. Detector now acquires binned 2x2 images of the selected region
```

## SoftBPM (Software Beam Position Monitor)

Monitors beam-normalized image intensity during data acquisition and automatically adjusts motors to maximize intensity when it drops beyond a threshold.

### Features

- **Beam Normalization**: Normalizes image intensity by storage ring beam current
- **Automatic Motor Adjustment**: Moves motors to restore beam intensity
- **Threshold Detection**: Configurable drop threshold for triggering adjustments
- **Empty Frame Filtering**: Skips images below 70% of reference (empty first frames)
- **Test Mode**: Monitor without moving motors (safe observation)
- **Real-time Plotting**: Live intensity plot over time
- **HDF5 Trigger**: Only monitors when HDF5 location is `/exchange/data_white`

### Default PVs

| PV | Description |
|---|---|
| `32id:TomoScan:HDF5Location` | Trigger PV (monitors when `/exchange/data_white`) |
| `32idbSP1:Pva1:Image` | Camera image PV (PVAccess NTNDArray) |
| `S:SRcurrentAI` | Storage ring beam current (mA) |
| `32idb:m1` | Motor 1 for beam adjustment |
| `32idb:m2` | Motor 2 for beam adjustment |

### Settings

| Parameter | Default | Description |
|---|---|---|
| Threshold (%) | 10.0% | Intensity drop threshold to trigger adjustment |
| Test Mode | Off | If enabled, monitors without moving motors |
| Poll Interval | 1.0 s | How often to check for new images |
| Motor 1 Step | 0.1 | Step size for motor 1 |
| Motor 2 Step | 0.1 | Step size for motor 2 |

### Usage

1. **Configure Settings**
   - Set threshold percentage (typically 5-15%)
   - Configure motor step sizes
   - Enable Test Mode for initial observation

2. **Start Monitoring**
   - Click "Start Monitoring"
   - Plugin waits for HDF5 location to be `/exchange/data_white`
   - Once triggered, establishes reference intensity

3. **Automatic Operation**
   - Polls image PV every interval (default 1s)
   - Skips duplicate images (same uniqueId)
   - Skips empty images (< 70% of reference)
   - If intensity drops > threshold, adjusts motors
   - Updates reference intensity after adjustment

4. **Stop/Reset**
   - "Stop Monitoring" to pause
   - "Reset Reference" to re-establish baseline

### How It Works

```
1. Check HDF5Location PV every poll interval
2. If location == "/exchange/data_white":
   a. Fetch image from camera PV (via PVAccess)
   b. Check uniqueId - skip if duplicate
   c. Calculate mean intensity
   d. Normalize by beam current (I_norm = I_raw / I_beam)
   e. If no reference, establish reference
   f. Calculate change: Δ = (I_norm - I_ref) / I_ref × 100%
   g. If Δ < -70%: skip (empty frame)
   h. If Δ < -threshold: move motors to restore intensity
   i. Update plot
```

### Motor Adjustment Algorithm

When intensity drops beyond threshold:
1. Calculate direction: `dir = -1` (move to restore)
2. Move motor 1 by `motor1_step × dir`
3. Move motor 2 by `motor2_step × dir`
4. Update reference intensity
5. Log adjustment

The algorithm performs simple gradient ascent to find the intensity maximum.

### Notes

- **Image ID tracking**: Uses uniqueId from NTNDArray to detect new images
- **Prevents reprocessing**: Skips images that haven't changed since last check
- **Beam current normalization**: Accounts for storage ring current variations
- **Empty frame filtering**: Automatically skips first/empty frames in acquisition sequences
- **Test mode recommended**: Always test with motors disabled before enabling automatic adjustment

### Example Workflow

```
1. Set threshold to 10%
2. Enable Test Mode
3. Start acquisition with /exchange/data_white
4. Observe intensity plot and log messages
5. Verify intensity is stable
6. Disable Test Mode for automatic motor adjustment
7. Monitor continues and adjusts motors as needed
```

## Mosalign

2D motor scanning with image stitching and tomoscan integration. See [Mosalign Documentation](../plugins/mosalign.md) for complete details.

## Installation Notes

All bl32ID plugins are automatically discovered and loaded by PyStream. No additional installation or configuration is required beyond installing PyStream itself.

## Requirements

- PyQt5
- pyqtgraph
- pvaccess (for PVAccess image data)
- numpy
- EPICS environment properly configured

## Troubleshooting

### Detector Control

**ROI not appearing:**
- Ensure a live image is displayed in the viewer
- Check that "Enable ROI Drawing" is toggled on
- Verify parent viewer has `image_view` attribute

**PV connection fails:**
- Verify camera PV prefix is correct
- Test with `caget 32idbSP1:cam1:BinX`
- Check EPICS environment variables

### SoftBPM

**No data updating:**
- Verify image PV is publishing data
- Check HDF5Location PV is set to `/exchange/data_white`
- Enable debug logging to see PVA fetch attempts
- Verify beam current PV is readable

**Intensity declining artificially:**
- Fixed in latest version by using PVA channel.get() with uniqueId tracking
- If still occurring, check that uniqueId is incrementing with new images

**Empty frames triggering adjustment:**
- Plugin automatically skips frames < 70% of reference
- Adjust threshold if needed

**Motors not moving:**
- Check Test Mode is disabled
- Verify motor PVs are correct and writable
- Check motor permissions in EPICS

### General

**Plugin not appearing in toolbar:**
- Check bl32ID directory exists in `src/pystream/beamlines/`
- Verify `__init__.py` properly exports dialog classes
- Check PyStream log for import errors

**EPICS connectivity:**
- Set EPICS environment: `EPICS_CA_ADDR_LIST`, `EPICS_CA_AUTO_ADDR_LIST`
- Test PV access: `caget <PV_NAME>`
- Check IOC status and network connectivity

## Development

To modify or extend bl32ID plugins:

1. Navigate to `src/pystream/beamlines/bl32ID/`
2. Edit the plugin file (e.g., `detectorcontrol.py`)
3. Update `__init__.py` if adding new dialog classes
4. Restart PyStream to load changes

For hot-reloading during development, consider using Python's `importlib.reload()`.

## See Also

- [Beamlines Plugin System](index.md) - Overview of the beamlines architecture
- [Mosalign Documentation](../plugins/mosalign.md) - Detailed mosalign guide
- [PyStream API](../api.md) - Core PyStream API reference
