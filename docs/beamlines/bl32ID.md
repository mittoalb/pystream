# bl32ID Beamline Plugins

APS beamline 32-ID tools for TXM tomography and imaging.

## Plugins

### Detector Control

Sets camera binning and applies a crop ROI drawn on the live image. Use
*Enable ROI Drawing* to draw, then *Apply ROI to Detector*.

### SoftBPM

Watches beam-normalized image intensity and, when it drops past a
threshold, nudges two motors to recover it. Run with *Test Mode* on first
to verify before enabling motor moves.

### QGMax

Optimizes two motors to maximize image mean using coarse-then-fine
gradient steps. Can run once or be triggered automatically by a TomoScan
HDF5-location PV.

### AutoCenter

Detects a pinhole, condenser, or zone plate in the live image and moves
X/Y motors to bring it to the target. *Detect* shows the overlay,
*Center* moves once, *Auto Center* iterates until within tolerance.

### AutoROT

Estimates the vertical rotation axis from variance across a buffer of
recent images and overlays it on the viewer.

### TXM Optics

Launches the external TXM Optics Calculator. *Set Pixel Size PV* writes
the calculator's effective pixel size to `32id:TXMOptics:ImagePixelSize`.

### Mosalign

2D motor scan with image stitching and tomoscan integration. See
[Mosalign](../plugins/mosalign.md).

### DataMap

Runs a 2D projection (sample + flat) or a Tomoscan at every row of a
user-defined motor positions table.

- *Add Motor Column* on the Positions tab adds a motor; fill its PV on
  the **Motor PVs** tab.
- *Add Row* adds a blank point; *Capture Live Values → New Row*
  snapshots current motor RBVs.
- Pick **2D Projection** or **Tomoscan** under *Mode* — applies to every
  row. Expand the matching section to edit its parameters.
- *Run Selected Row* runs one point; *Run All* runs them in order.

### TXMBot (AI)

LLM chat assistant with read-only beamline introspection and gated
IOC-recovery actions. See [TXMBot](txmbot.md).

### XANES GUI

Launcher for the external XANES energy-calibration and scanning GUI.

## Settings

Plugin state is saved to `~/.pystream_bl32ID_settings.json` on close and
restored on next open.

## Adding a new plugin

1. Create `my_plugin.py` in `src/pystream/beamlines/bl32ID/`.
2. Define a `QDialog` subclass with `BUTTON_TEXT = "..."` and
   `HANDLER_TYPE = 'singleton'`.
3. For persistence: `from .plugin_settings import load_settings, save_settings`.
4. Import and add the class to `__all__` in
   `src/pystream/beamlines/bl32ID/__init__.py`.
5. Restart PyStream.
