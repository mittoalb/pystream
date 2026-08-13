# bl32ID Beamline Plugins

APS beamline 32-ID tools for TXM tomography, XANES imaging, and beam
optimization.

## Toolbar layout

Plugins are grouped into dropdown menus in the toolbar. Class attribute
`GROUP = "…"` on each plugin decides which menu it lands in; order comes
from `__all__` in [bl32ID/__init__.py](../../src/pystream/beamlines/bl32ID/__init__.py).

| Menu | Plugins |
|---|---|
| **Alignment ▾** | Mosalign, CoR, AlignPart, QGMax |
| **Detector ▾** | Detector |
| **Scans ▾** | XANES, XANES 2D, DataMap, aTomo |
| **Viewers ▾** | XANES 2D Viewer |
| **Calculators ▾** | TXM Optics, X-ray Tools |
| **Test ▾** | AutoROT, AutoCenter, Autofocus *(under development)* |
| **Tools ▾** | BL GUI |

The **AI Agent (Röntgen)** is not in a toolbar dropdown — it lives as a
permanent bottom panel provided by pystream core. bl32ID contributes
its tool catalog + prompt body via `provide_agent_context()`. See
[Röntgen](txmbot.md).

## Plugins

### Detector Control

Sets camera binning and applies a crop ROI drawn on the live image. Use
*Enable ROI Drawing* to draw, then *Apply ROI to Detector*.

### CoR (Center of Rotation)

One-button 0°/180° cross-correlation to find the rotation axis. Grabs
+averages N frames at the current angle, `caput`s the rotation motor to
θ+180°, grabs again, mirrors the second image horizontally, cross-
correlates with sub-pixel refinement, and reports the CoR column both as
an absolute pixel and as an offset from image-center. Rotation motor is
guaranteed to return to θ₀ via a `finally` block, even on abort. All
tuning knobs (rot PV, Δ°, settle time, averaging) are hardcoded module
constants — one-line edit to retune.

### AlignPart (Particle → CoR alignment)

Click a particle in the live viewer → the plugin measures CoR (rotate
±180° internally, same algorithm as CoR), then iteratively drives topx /
topz sample-stage motors until the clicked feature sits on the rotation
axis at the vertical center. Segmentation cascade: **SAM2** (if
configured — see [ai_backends](../ai_backends.md)) → **region-grow from
snapped seed** (ImageJ magic-wand style: snaps click to nearest local
extremum, floods within noise-adjusted tolerance) → **Otsu** as last
resort. Draws a magenta crosshair + bbox rectangle + boundary outline
on the detected blob so you see what was segmented. Motor safety: rotation
returns to θ₀ in a `finally`; topx/topz stay where the last iteration
left them.

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

### AutoCenter *(Test group — under development)*

Detects a pinhole, condenser, or zone plate in the live image and moves
X/Y motors to bring it to the target. *Detect* shows the overlay,
*Center* moves once, *Auto Center* iterates until within tolerance.
For the actual rotation-axis workflow use **CoR** + **AlignPart** above.

### AutoROT *(Test group — under development)*

Estimates the vertical rotation axis from variance across a buffer of
recent images and overlays it on the viewer. Different algorithm from
**CoR** — variance-minimization across many angles rather than
0°/180° cross-correlation.

### Autofocus *(Test group — under development)*

Launcher for the standalone autofocus routine.

### TXM Optics

Launches the external TXM Optics Calculator. *Set Pixel Size PV* writes
the calculator's effective pixel size to `32id:TXMOptics:ImagePixelSize`.

### Mosalign

2D motor scan with image stitching and tomoscan integration. See
[Mosalign](../plugins/mosalign.md).

### aTomo

Launcher for the standalone [atomo](https://github.com/mittoalb/atomo)
adaptive-exposure tomography GUI. atomo runs as a headless soft-IOC
daemon (`atomo-ioc`) whose PVs mirror tomoscan's, so pystream's QGMax
auto-mode drives it unchanged. The launcher spawns `atomo-gui` as a
subprocess — the GUI is a thin CA client onto the daemon.

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

### Röntgen (AI)

Core pystream feature — always visible as a bottom panel, not a bl32ID
toolbar entry. bl32ID contributes its 32-ID-specific tools (`read_pv`,
`list_status_pages`, IOC scripts, XANES2D metadata, …) and prompt body
via `provide_agent_context()` in [bl32ID/__init__.py](../../src/pystream/beamlines/bl32ID/__init__.py).
Actual tool implementations live in [agent_tools.py](../../src/pystream/beamlines/bl32ID/agent_tools.py).

Full agent docs: [Röntgen](txmbot.md).

Default agent name honors Wilhelm Conrad Röntgen, who discovered X-rays
in 1895 — editable in the ⚙ Settings dialog.

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
QGMax request/response files, the X-ray Tools density cache, the AI
agent's `agent_settings.json` + `agent_history_dock.json`, and the
knowledge-base `docs/` symlinks / `ioc_scripts.json` /
`status_pages.json` seeded by [agent_tools.py](../../src/pystream/beamlines/bl32ID/agent_tools.py).

## Adding a new plugin

1. Create `my_plugin.py` in `src/pystream/beamlines/bl32ID/`.
2. Define a `QDialog` subclass with `BUTTON_TEXT = "..."` and
   `HANDLER_TYPE = 'singleton'` (or `'launcher'` for a fire-and-close
   external-process launcher).
3. For persistence: `from .plugin_settings import load_settings, save_settings`.
4. Import and add the class to `__all__` in
   `src/pystream/beamlines/bl32ID/__init__.py`.
5. Restart PyStream.
