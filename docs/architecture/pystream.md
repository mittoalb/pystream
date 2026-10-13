# pystream

A Qt live viewer for EPICS areaDetector streams, plus the host process
for the beamline's control dialogs and the AI agent.

## Purpose in one sentence

Subscribe to a camera's live NTNDArray stream, render it with
pyqtgraph, run per-frame plugins (ROI stats, line profile, scalebar,
flat-field, autoscale), and host a tabbed set of beamline-specific
control dialogs plus the AI agent dock.

## Where it fits

```{mermaid}
flowchart LR
    AD[AreaDetector IOC<br/>or detectors IOC]
    MIOC[motor IOCs]
    PS[pystream]
    AG[beamline-agent]
    BG[bl_gui]
    DISK[recorded TIFFs]

    AD -. PVA image1:ArrayData .-> PS
    AD -. CA cam1 .-> PS
    MIOC -. CA .-> PS
    PS -- in-process host .-> AG
    AG -. shares image + bus .-> PS
    PS --> DISK
    BG -. coexists on same IOC .-> AD
```

pystream subscribes to the image stream, exchanges small values with
the IOC via CA, hosts the agent as a dock widget, and when the user
hits Record writes TIFFs to disk with a JSON metadata sidecar.

## Architecture

```{mermaid}
flowchart TB
    subgraph Process ["pystream process"]
        subgraph MainWin ["PvViewerApp (QMainWindow)"]
            subgraph Center ["Central splitter"]
                IV[pyqtgraph ImageView<br/>+ live Mean/FPS overlay]
                AGPANE[AI Agent chat dock<br/>via beamline-agent]
            end

            subgraph Sidebar ["Left sidebar"]
                CTRL[Pause / Record / Reset]
                CONTR[Contrast / autoscale / sliders]
                HIST[Histogram]
            end

            subgraph Plugins ["Per-frame plugins"]
                ROI[ROI stats]
                LP[Line profile]
                EL[Ellipse ROI]
                SB[Scalebar]
                CS[Console / processors]
            end

            subgraph Dialogs ["Beamline dialogs (singleton or launcher)"]
                DET[DetectorControl]
                QG[QGMaxDialog]
                COR[CenterOfRotation]
                AC[AutoCenter]
                DM[DataMap]
                PA[ParticleAlign]
                XG[XANESGui / XANES2DGui]
            end
        end

        subgraph Backing ["Backing threads / timers"]
            SUB[pvaccess subscriber thread]
            Q[frame queue]
            PUMP[QTimer pump]
            REC[RecordingPool threads]
        end
    end

    SUB -- NTNDArray --> Q
    Q --> PUMP
    PUMP -- image_ready signal --> IV
    PUMP --> Plugins
    PUMP --> REC
    IV -. right-click .-> Dialogs
    AGPANE -. HostContext .-> MainWin
```

Key observations about the structure:

* `PvViewerApp` owns the single `pg.ImageView`. Every plugin, every
  dialog, the agent — they all read the current frame from it. The
  Mean/FPS overlay is a child QLabel pinned to the top-right.
* The image comes in on a **background thread** (`pvaccess.Channel`
  subscribe callback), gets pushed through a bounded `queue.Queue`,
  and a Qt timer drains the queue on the main thread. This keeps the
  pyqtgraph calls on the GUI thread while never blocking the pvaccess
  worker.
* Beamline dialogs are **singletons** cached on `PvViewerApp` by class
  name (`qgmaxdialog_instance`, `detectorcontroldialog_instance`, …).
  Reopening the toolbar button `.show()`s the same instance — state
  (timers, enabled modes) persists across hide/show cycles.
* Record spins up a `_RecordingPool`: N worker threads reading from a
  bounded queue, writing TIFFs in parallel (no compression by default
  — the single biggest throughput win vs AD HDF1 for debug dumps).

## Data flow

```{mermaid}
sequenceDiagram
    participant IOC as AreaDetector IOC
    participant SUB as pvaccess subscriber
    participant Q as frame queue
    participant PUMP as QTimer pump
    participant IV as ImageView
    participant PL as plugins
    participant REC as RecordingPool

    IOC->>SUB: NTNDArray (callback thread)
    SUB->>Q: enqueue (non-blocking)
    PUMP->>Q: drain latest frame (main thread)
    PUMP->>PL: _apply_view_ops (decimate, flip, flat-field)
    PUMP->>IV: setImage(img, levels)
    PUMP->>IV: emit image_ready(uid, img, ts)
    IV->>PL: ROI / line / scalebar update
    IV->>PUMP: overlay Mean + FPS
    opt recording
        PUMP->>REC: put(idx, frame_copy)
    end
```

Each frame travels one hop: subscriber thread → queue → Qt pump →
image_view. Plugins receive it synchronously from the pump. The
agent sees it via the `image_ready` Qt signal on `PvViewerApp`.

## Stream PV auto-detection

On startup pystream decides which image stream to subscribe to in
this priority order:

1. `--pv <name>` command-line argument.
2. `pv_name` in `~/.pystream/viewer_config.json` (last-used,
   remembered across restarts).
3. **Auto-probe**. Walks a candidate list (built-in defaults +
   `stream_pv_candidates` from user config) and connects to the first
   PV that responds within a configurable timeout.

Default candidates cover both AreaDetector (`32idbSP1:image1:ArrayData`,
`32idbSP2:image1:ArrayData`) and the detectors Python IOC (`ORYX:`,
`KTX:`, `KINETIX:`, `ORCA:`, `DET:` all with the `:image1:ArrayData`
suffix). First responder wins. Lets pystream latch onto either IOC
without the user telling it.

## Host context for the agent

`PvViewerApp` builds a `HostContext` and hands it to
`beamline-agent.mount()`:

```python
host = HostContext(
    main_window      = self,
    live_frame       = lambda: self.image_view.getImageItem().image,
    frame_signal     = self.image_ready,
    active_beamline  = beamline_config.ACTIVE_BEAMLINE,
    open_hdf5_viewer = self._open_viewer,
    open_plugin      = self._open_beamline_plugin,
    list_plugins     = self._list_beamline_plugins,
)
```

The agent lives inside pystream's event loop; its tools call these
host accessors directly (no RPC, no MCP). See
{doc}`beamline-agent` for why.

## Beamline dialogs

Each dialog is a `QDialog` subclass in `pystream/beamlines/<bl>/`
with these class attributes picked up by the launcher:

| Attribute       | Meaning                                                           |
|-----------------|-------------------------------------------------------------------|
| `BUTTON_TEXT`   | Label on the toolbar button                                       |
| `GROUP`         | Toolbar group header (`Detector`, `Alignment`, `Scans`, `Tools`)  |
| `HANDLER_TYPE`  | `singleton` / `multi-instance` / `launcher`                       |

* **singleton** — one cached instance per class, re-shown on click.
  Used for `DetectorControl`, `QGMax`, etc. — anything with per-session
  state the user wants preserved.
* **multi-instance** — new dialog each click. Used for scan setups
  that are run multiple times with different params.
* **launcher** — the dialog launches an external process (bl_gui,
  Atomo, …) and immediately closes.

See the `provide_task_templates`, `provide_bottom_panels` hooks in
`beamlines/<bl>/__init__.py` for the extension points a new beamline
plugs into.

## Recording and metadata

Hitting Record creates `~/<path>/recording_<timestamp>/` and writes
TIFF frames through a worker pool. On Stop pystream writes a
`metadata.json` sidecar whose structure is driven by
[`detectors/recording_metadata.json`](../../../detectors/detectors/recording_metadata.json)
— the template is shipped with the `detectors` package, not with
pystream, so camera PV names live with the camera code.

Each leaf of the template is `{"pv": ...}`, `{"value": ...}` or
`{"auto": ...}` — see {doc}`detectors` for the schema.

## Public API / extension points

* **Plugin a per-frame transform**: add a module under
  `pystream/plugins/`, implement the standard `update_stats(img)` or
  `process(img) -> img` interface, instantiate it from
  `PvViewerApp.__init__`.
* **Add a beamline dialog**: subclass `QDialog`, set class attrs
  above, export it from `beamlines/<bl>/__init__.py` `__all__`.
* **Add a bottom panel** (log tail, status widget, chat, …): return
  it from the beamline's `provide_bottom_panels(parent)`.
* **New processor pipeline**: edit `pipelines/processors.json` or
  write your own `--proc-config path.json`.

## Dependencies

* `numpy`, `PyQt5`, `pyqtgraph`, `pvapy` — hard deps for the viewer.
* `beamline-agent` — optional. Without it the AI dock just doesn't
  mount; nothing else breaks.
* `h5py`, `Pillow` — HDF5 viewer and TIFF export.
* `xanes-gui`, `mosalign` — pulled in by the `bl32ID` extra.

## Known gotchas

* **`caput_bg` in bl_gui is fire-and-forget**; pystream dialogs use
  blocking `caput -c` because the user needs to know the write
  landed. Don't mix patterns inside one dialog.
* **Singleton dialogs persist across close**. `closeEvent` should
  only clear per-session state if the user explicitly asked. The
  QGMax closeEvent fix was to *stop* killing timers on close — that
  was silently disabling auto-mode.
* **Image coordinates vs sensor coordinates**. `img.shape` from the
  queue reflects display-side decimation (`display_bin`) and the
  user's flip/transpose. Anything that needs real sensor pixels
  must undo `_apply_view_ops` first — see
  `DetectorControlDialog._roi_to_sensor`.
* **The pump is throttled by `max_fps`**. If you set `--max-fps 10`
  the queue drops frames; plugins only see 10 fps. Recording lives
  *before* the throttle so TIFFs still capture at camera rate.
* **`EPICS_CA_ADDR_LIST` must be exported in the shell** on
  cross-machine setups. pystream inherits the env for the subprocess
  caget/caput calls in dialog code.

## Future / open questions

* Replace the subprocess `caget` / `caput -c` calls in dialogs with a
  shared in-process PV hub (bmsg was the first attempt; reverted —
  needs re-attempting against a specific pain point, not pre-emptive
  refactor).
* Decide whether per-plugin preferences should move into
  `viewer_config.json` or stay in each plugin's own `.pystream_*`
  file. Current state is mixed.
