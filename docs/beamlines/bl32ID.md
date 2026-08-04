# bl32ID Beamline Plugins

APS beamline 32-ID tools for TXM tomography, XANES imaging, and beam
optimization.

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
gradient steps. Can run once or run automatically inside a TomoScan.

**Automated Mode** watches the TomoScan `HDF5Location` PV and, on every
new `/exchange/data` event (i.e., every new energy point in a 3D XANES
scan):

- Runs a fast **online bright-spot check** without pausing tomoscan.
  After a 1.5 s settle it grabs one frame, computes the center/outer
  ratio, and if a bright spot is detected nudges **motor 1 by one fine
  step**. The step direction is picked from the spot's Y position
  (upper half of image → +1, lower → -1, scaled by the internal
  `bright_spot_direction_sign` if the wiring is inverted).
- On every N-th event (configurable), instead runs a **full
  motor 1 + motor 2 optimization** — this pauses tomoscan via
  `TomoScan:Pause`, sweeps both motors to maximise the mean, ends with
  the same bright-spot correction, and resumes tomoscan.

Auto-mode can be toggled from the QGMax dialog directly, or driven from
the XANES GUIs — see the *XANES GUI* and *XANES 2D GUI* sections below.
Requests from the XANES GUIs use a small JSON file at
`~/.pystream/qgmax_request.json`; QGMax's background watcher (started
automatically on pystream launch) picks them up whether or not the QGMax
dialog is open.

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

Launcher for the external 3D XANES energy-calibration and scanning GUI
(`xanes_gui.gui`). The 3D XANES scan is executed by an external
`xanes_energy.py` process that hands the energy list to `tomoscan
energy`.

The scan tab has a **QGMax optimization** box with *Run every N
tomoscans (0 = off)*. Setting N ≥ 1 writes to
`~/.pystream/qgmax_request.json` on Start to enable QGMax's Automated
Mode with that N, and to disable it on Finish / Error / Stop. All other
QGMax knobs (motor PVs, step sizes, thresholds, TomoScan pause PV) stay
in the QGMax dialog.

### XANES 2D GUI

Launcher for the external 2D XANES GUI (`xanes_gui.gui_2d`) — the
Python-driven loop that steps energies, moves ZP, and acquires
sample/flat frames per energy. The energy loop runs in Python here (not
in tomoscan), so QGMax is called inline between energies using the same
`qgmax_request.json` protocol.

**Fast-shutter behavior**: the shutter is opened at the top of each scan
series (`_run_one_scan`) and closed in the `finally` at the end of the
series. Between series, the wait is a *gap* (`interval_s` measured
end-of-scan to start-of-next-scan), and the shutter stays closed during
that wait.

### XANES 2D Viewer

Standalone Qt viewer for the HDF5 master files produced by the XANES 2D
GUI. Launches `xanes_gui/viewer_2d.py` in a subprocess.

- **Image Viewer tab**: slider + spinbox over N frames, live
  `E = <eV>` label, on-the-fly `data / data_flat` division, six
  contrast presets, integer X/Y flat shift (arrow keys), image
  statistics.
- **Normalization**: default uses the flats stored in the file. Switch
  to *Use flats from external file* to normalize against another
  master's `/exchange/data_flat` (matched by index; shape-checked
  on load).
- **Metadata tab**: filterable attribute table + full HDF5 tree.

### X-ray Tools

Reference calculator ported from the xraytr web app (originally a Dash
app on port 8009). Two tabs:

- **Transmissivity & Refractive Index**: enter a formula (e.g. `SiO2`,
  `Fe`, `Lu3Al5O12`), an optional density, thickness in mm, and an
  energy range as `start:stop:step` in keV. Uses `xraylib` to compute
  transmission `T(E)` and refractive-index components `δ, β(E)`. Density
  is auto-resolved: user input → `xraylib` elemental density → PubChem
  (asynchronous, off the UI thread) → local cache
  (`~/.pystream/xray_densities.csv`) → fallback 1.0 g/cm³. Left-click
  either plot to snap a marker to the nearest data point and read the
  value in the readout label above the plots.
- **X-ray Absorption Edges**: filterable/sortable table of K/L1/L2/L3
  edges for Z = 1–103, with search and energy-range filters.

`xraylib` is required for the transmissivity tab. If it isn't installed
in the pystream env, the tab shows a red banner and disables *Compute*;
the edges tab still works. To install:

```bash
conda install -n pystream -c conda-forge xraylib
```

## Settings

Plugin state is saved to `~/.pystream/bl32ID_settings.json` on close and
restored on next open. The directory `~/.pystream/` also holds the
QGMax request/response files and the X-ray Tools density cache.

## Adding a new plugin

1. Create `my_plugin.py` in `src/pystream/beamlines/bl32ID/`.
2. Define a `QDialog` subclass with `BUTTON_TEXT = "..."` and
   `HANDLER_TYPE = 'singleton'` (or `'launcher'` for a fire-and-close
   external-process launcher).
3. For persistence: `from .plugin_settings import load_settings, save_settings`.
4. Import and add the class to `__all__` in
   `src/pystream/beamlines/bl32ID/__init__.py`.
5. Restart PyStream.
