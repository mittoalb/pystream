# bl32ID Beamline Plugins

Advanced Photon Source beamline 32-ID specialized tools for TXM tomography and imaging.

## Overview

The bl32ID beamline package provides built-in tools and launchers for optional external GUIs:

### Built-in Tools (Always Available)

- **Detector Control**: Camera binning, ROI drawing, and crop PV control
- **SoftBPM**: Software beam position monitor with automatic motor adjustment
- **QGMax**: Beam intensity optimizer using gradient-based motor optimization
- **AutoCenter**: Automatic centering of optical elements (pinhole, condenser, zone plate)
- **AutoROT**: Rotation axis detection for tomography alignment
- **Mosalign**: 2D motor scanning with image stitching
- **DataMap**: N-motor positions table; each point runs either a 2D
  projection (sample + flat) or a Tomoscan
- **TXMBot (AI)**: LLM chat assistant with read-only beamline introspection
  tools (PV reads, device health, image stats, scan inspection, local docs,
  web docs) and gated IOC-recovery actions. See [TXMBot](txmbot.md).

### Optional External Tools (Install Separately)

- **XANES GUI**: Energy calibration and XANES scanning control
- **TXM Optics**: Optics parameter calculator with effective pixel size PV setter

External tools are optional packages installed separately. Click the button to launch - if not installed, you'll see installation instructions.

### Settings Persistence

All plugins automatically save their configuration (PV names, calibration values, thresholds, etc.) to `~/.pystream_bl32ID_settings.json` when closed, and restore them on next open.

## Detector Control

Controls detector binning, region-of-interest, and crop settings for the area detector camera.

### Features

- **Binning Control**: Set X and Y binning factors (1-16)
- **ROI Drawing**: Press-drag-release ROI drawing on live image with 8 resize handles
- **Crop PV Control**: Sets CropLeft/Right/Top/Bottom (pixels removed from each border)
- **Vertical Flip**: Swap top/bottom for sensors with inverted row orientation
- **Real-time Feedback**: Live crop values displayed as you drag the ROI
- **Settings Persistence**: PV prefixes and flip state saved between sessions

### Controlled PVs

| PV Prefix | PV | Description |
|---|---|---|
| Camera (`32idbSP1:cam1`) | `BinX`, `BinY` | Binning factors |
| Camera | `SizeX`, `SizeY` | Image dimensions (auto-computed) |
| Camera | `MaxSizeX_RBV`, `MaxSizeY_RBV` | Full sensor size readback |
| Crop (`32id:TXMOptics`) | `CropLeft`, `CropRight` | Pixels removed from left/right borders |
| Crop | `CropTop`, `CropBottom` | Pixels removed from top/bottom borders |
| Crop | `Crop` | Apply crop trigger (set to 1) |

### ROI Drawing

1. Click **Enable ROI Drawing** - cursor changes to crosshair
2. Press left mouse button at one corner
3. Drag to opposite corner (live red preview rectangle)
4. Release to create ROI with 8 resize handles (4 corners + 4 edges)
5. Drag handles to adjust, or drag body to move
6. Click **Apply ROI to Detector** to set crop PVs

### Crop Logic

Crop values are distances from each sensor border to the ROI edge:

```
CropLeft + ROI_width + CropRight = sensor_width
CropTop + ROI_height + CropBottom = sensor_height
```

Example: 2000px ROI centered on 3232px sensor:
- CropLeft = CropRight = (3232 - 2000) / 2 = 616

### Usage

1. Click **Read Current** to load detector settings and sensor size
2. Click **Remove ROI (Full Frame)** to start from the full sensor
3. Click **Enable ROI Drawing** and draw the desired region
4. Click **Apply ROI to Detector** to set crop PVs

## SoftBPM (Software Beam Position Monitor)

Monitors beam-normalized image intensity during data acquisition and automatically adjusts motors to maximize intensity when it drops beyond a threshold.

### Features

- **Event-Driven Synchronization**: Directly synchronized with viewer updates (no polling)
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
| Poll Interval | 1.0 s | Not used - kept for UI compatibility (event-driven) |
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
   - Processes each new image as viewer updates (event-driven)
   - Skips empty images (< 70% of reference)
   - If intensity drops > threshold, adjusts motors
   - Updates reference intensity after adjustment

4. **Stop/Reset**
   - "Stop Monitoring" to pause
   - "Reset Reference" to re-establish baseline

### How It Works

```
1. Connect to viewer's image_ready signal (event-driven)
2. On each new image from viewer:
   a. Check HDF5Location PV
   b. If location == "/exchange/data_white":
      - Calculate mean intensity from image
      - Normalize by beam current (I_norm = I_raw / I_beam)
      - If no reference, establish reference
      - Calculate change: Δ = (I_norm - I_ref) / I_ref × 100%
      - If Δ < -70%: skip (empty frame)
      - If Δ < -threshold: move motors to restore intensity
      - Update plot
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

- **Event-driven architecture**: No polling - directly synchronized with viewer's image updates
- **Real-time response**: Processes each frame as viewer displays it
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

## QGMax (Beam Intensity Optimizer)

Optimizes two motors to maximize image mean value using a two-stage gradient-based algorithm.

### Features

- **Two-Stage Optimization**: Coarse scan (5x step) then fine scan (1x step)
- **Two-Motor Support**: Alternates between Motor 1 and Motor 2
- **Direction Auto-Detection**: Reverses direction on consecutive decreases
- **Manual and Automated Mode**: Run once or continuously synchronized with TomoScan
- **Status PV**: External monitoring via `32id:pystream:qgmax`

### Default PVs

| PV | Description |
|---|---|
| `32id:m1` | Motor 1 for optimization |
| `32id:m2` | Motor 2 for optimization |
| `32id:TomoScan:HDF5Location` | Trigger PV for automated mode |
| `32id:TomoScan:Pause` | Pause PV for synchronized optimization |

### Settings

| Parameter | Default | Description |
|---|---|---|
| Motor Step Size | 0.01 | Base step size for each motor |
| Optimization Interval | 60 s | Interval between optimization cycles |
| Max Iterations | 5 | Maximum steps per motor per cycle |
| Convergence Threshold | 0.5% | Stop when improvement < threshold |
| Run Every N | 1 | Run every N `/exchange/data` triggers |

### Algorithm

1. Motor 1 Coarse Stage: try direction at 5x step, track best position
2. Motor 1 Fine Stage: refine at 1x step
3. After 2 consecutive decreases, return to best position and switch motors
4. Motor 2: repeat coarse + fine stages

---

## AutoCenter (Optical Element Centering)

Automatically detects and centers optical elements (pinhole, condenser, zone plate) by analyzing the camera image and moving X/Y motors.

### Features

- **Three Element Types**: Pinhole, Condenser, Zone Plate with per-element motor PVs and calibration
- **Detection Algorithms**: Threshold + center-of-mass, edge detection + circle fitting
- **Visual Overlay**: Red cross at detected center, green circle at target, crosshair lines
- **Single or Iterative Centering**: One-shot or automatic detect-move-repeat loop
- **Swap Axes**: Checkbox to swap X/Y motor assignments if needed

### Detection Algorithms

| Element | Algorithm |
|---|---|
| Pinhole | Otsu threshold, center of mass of bright pixels |
| Condenser | Largest connected component center of mass |
| Zone Plate | Gradient edge detection + Kasa circle fit with outlier rejection (ignores bright square) |

### Calibration

- **mm/px**: Motor movement (mm) per pixel of image offset
- **Sign matters**: Negative if motor direction is opposite to image shift
- **Default**: -0.000766 mm/px (0.766 um pixel size)
- **Note**: Motors at 32-ID are in mm. Adjust calibration for actual magnification between element and camera.

### Settings

| Parameter | Default | Description |
|---|---|---|
| Calibration (mm/px) | -0.000766 | Per element, per axis |
| Swap X/Y | Off | Swap motor axis assignments |
| Threshold | Auto (Otsu) | Automatic or manual |
| Target | Image center | Target position (0 = image center) |
| Tolerance | 2.0 px | Stop iterating when offset < tolerance |
| Max Iterations | 10 | Maximum centering iterations |
| Settle Time | 1.0 s | Wait between move and re-detect |

### Usage

1. Select element type (Pinhole, Condenser, Zone Plate)
2. Set motor PVs and calibration in Settings tab
3. Click **Detect** to find the element and show overlay
4. Click **Center** for a single move toward target
5. Click **Auto Center** for iterative centering until within tolerance

---

## AutoROT (Rotation Axis Detection)

Detects the vertical rotation axis position in tomography image sequences using variance analysis.

### Features

- **Variance-Based Detection**: Finds rotation axis as minimum of column-variance profile
- **Parabola Fitting**: Sub-pixel accuracy via quadratic fit
- **Confidence Score**: R-squared from fit quality
- **Visual Overlay**: Vertical line on image at detected axis position
- **Auto Update**: Continuously updates as new images arrive

### Algorithm

1. Buffers N recent images (configurable, default 10)
2. Computes per-pixel variance across the image stack
3. Projects to 1D variance profile (mean variance per column)
4. Fits parabola to find the minimum (rotation axis)

---

## TXM Optics Calculator

Launches the external TXM Optics Calculator and provides a button to write the effective pixel size to `32id:TXMOptics:ImagePixelSize`.

The **Set Pixel Size PV** button is next to Calculate/Reset/Export in the calculator. It reads the computed "Effective Pixel (nm)" value and writes it to the PV.

---

## Mosalign

2D motor scanning with image stitching and tomoscan integration. See [Mosalign Documentation](../plugins/mosalign.md) for complete details.

---

## DataMap

Run a 2D projection or a Tomoscan at each row of a user-defined
positions table.

### Tabs

- **Acquisition & Positions**
  - **Acquisition** — detector PVA channel, camera prefix, exposure,
    motor settle, output directory.
  - **Mode** — radio choice between **2D Projection** and **Tomoscan**.
    The selected mode is applied to every row.
  - **2D Projection settings** (collapsible) — Ref X / Z / Rotation PVs
    and target values used to move the sample out of the beam for the
    flat. Leave a PV blank to skip that axis.
  - **Tomoscan settings** (collapsible) — StartScan PV (default
    `32id:TomoScan:StartScan`), wait-for-finish flag, and timeout.
  - **Positions table** — columns are motors, rows are points. Buttons:
    *Add Motor Column*, *Remove Selected Column*, *Add Row*,
    *Remove Selected Row*, *Capture Live Values → New Row* (caget the
    current motor RBVs into a fresh row).
- **Motor PVs**
  - One row per motor column with `Name` and `PV`. Renaming the motor
    here updates the column header on the Positions tab. Adding or
    removing a row here also adds/removes the corresponding column on
    the other tab — the two views stay in sync.

### Run controls

- **Run Selected Row** — runs only the currently selected row using the
  active mode.
- **Run All** — runs every row in table order using the active mode.
- **Stop** — requests the worker to stop after the current step.

### 2D Projection per-row sequence

1. Move every configured motor to the row's target values.
2. Snap one sample frame from the PVA detector channel.
3. Move Ref X / Z / Rotation to their configured flat positions.
4. Snap one flat frame.
5. Restore X / Z / Rotation to their pre-flat values.
6. Save both frames to `<output_dir>/datamap_rowN_<ts>.h5`:
   - `/exchange/data` — sample frame (shape `(1, H, W)`)
   - `/exchange/data_flat` — flat frame (shape `(1, H, W)`)
   - `/measurement/instrument/datamap` — motor target + RBV attrs,
     row index.

### Tomoscan per-row sequence

1. Move every configured motor to the row's target values.
2. `caput 32id:TomoScan:StartScan 1` (waits on the busy record when
   *Wait for scan to finish* is checked, up to the configured timeout).

Scan parameters themselves (number of projections, rotation range,
flat/dark logic, etc.) remain owned by the TomoScan IOC and its own
GUI — DataMap only triggers the start.

### Default motors / PVs

- Motors default to `TopX = 32idbTXM:mcs:c1:m2` and
  `TopZ = 32idbTXM:mcs:c1:m1`. Add or remove columns to suit the scan.
- Ref defaults: `Ref X = 32idbTXM:mcs:c1:m2`,
  `Ref Z = 32idbTXM:mcs:c1:m1`,
  `Ref Rotation = 32idbTXM:ens:c1:m1`.
- TomoScan default: `32id:TomoScan:StartScan`.

### Settings

The whole table (motors, positions, acquisition params, selected mode)
persists to `~/.pystream/bl32ID_settings.json` under the
`DataMapDialog` key on dialog close.

## Settings File

All plugin settings are stored in `~/.pystream_bl32ID_settings.json`. This file is created automatically on first use and updated whenever a plugin dialog is closed. Delete this file to reset all plugins to defaults.

## Requirements

- PyQt5
- pyqtgraph
- pvaccess (for PVAccess image data)
- numpy
- scipy (optional, improves zone plate detection and condenser blob detection)
- EPICS environment properly configured

## Troubleshooting

### Detector Control

**ROI not appearing:**
- Ensure a live image is displayed in the viewer
- Check that "Enable ROI Drawing" is toggled on

**Crop values seem wrong:**
- Click "Remove ROI (Full Frame)" first to start from the full sensor
- The ROI drawn on an already-cropped image only selects within the visible region

### AutoCenter

**Element not detected:**
- Switch threshold from Auto to Manual and adjust the percentage
- Ensure the element is visible with sufficient contrast

**Motor moves wrong direction:**
- Change the sign of the calibration (positive <-> negative)
- If X/Y are swapped, check the "Swap X/Y motor axes" checkbox

**Centering takes many iterations:**
- The calibration (mm/px) is likely wrong for the current magnification
- Measure: move motor by known amount, count pixel shift, recompute

### SoftBPM / QGMax

**Motors not moving:**
- Check Test Mode is disabled (SoftBPM)
- Verify motor PVs are correct and writable
- Check motor permissions in EPICS

### General

**Plugin not appearing in toolbar:**
- Verify `__init__.py` exports the dialog class
- Check PyStream log for import errors

**Settings not saving:**
- Check write permissions to `~/.pystream_bl32ID_settings.json`
- Settings save on dialog close, not on every change

**EPICS connectivity:**
- Set EPICS environment: `EPICS_CA_ADDR_LIST`, `EPICS_CA_AUTO_ADDR_LIST`
- Test with `caget <PV_NAME>`

## Development

To add a new plugin:

1. Create `my_plugin.py` in `src/pystream/beamlines/bl32ID/`
2. Class inherits `QtWidgets.QDialog` with `BUTTON_TEXT` and `HANDLER_TYPE = 'singleton'`
3. Use `from .plugin_settings import load_settings, save_settings` for persistence
4. Add to `__init__.py`: import and append to `__all__`
5. Restart PyStream

## See Also

- [Beamlines Plugin System](index.md) - Overview of the beamlines architecture
- [Configuration Guide](configuration.md) - Beamline configuration
- [PyStream API](../api.md) - Core PyStream API reference
