# detectors

A multi-camera Python IOC + Qt GUI that **replaces** EPICS
areaDetector for the beamline's own cameras. Same PV surface, no C++
build, no synApps rebuild per camera. Published separately — see
<https://github.com/mittoalb/detector> and the standalone
[detectors documentation](https://detector.readthedocs.io/).

## Purpose in one sentence

Expose any supported scientific camera (Oryx, Kinetix, Orca Fire,
simulator) through the standard `<prefix>cam1:` / `<prefix>HDF1:` /
`<prefix>image1:` PVs so tomoscan and the GUIs don't care whether
the camera is driven by the vendor C++ IOC or by this Python one.

## Where it fits

```{mermaid}
flowchart LR
    CAM[Camera<br/>Oryx / Kinetix / Orca]
    SDK[Vendor SDK<br/>libSpinnaker / libpvcam / libdcamapi]
    DET[detectors IOC<br/>run_ioc.py]
    GUI[Qt GUI subprocess]
    PS[pystream]
    BG[bl_gui]
    TS[tomoscan]

    CAM -. USB3 / 10GigE / CXP .-> SDK
    SDK -- ctypes --> DET
    DET -. UNIX socket IPC .-> GUI
    DET -. CA cam1 / HDF1 .-> BG
    DET -. CA cam1 / HDF1 .-> TS
    DET -. PVA image1:ArrayData .-> PS
```

The detectors IOC presents **the same PV namespace** as the vendor
AreaDetector IOC. Clients (pystream, bl_gui, tomoscan) can target
either without code changes.

## Architecture

```{mermaid}
flowchart TB
    subgraph Driver ["Driver process (run_ioc.py)"]
        subgraph IOC ["DetectorIOC (caproto PVGroup)"]
            CAM1[cam1: PVs]
            HDF1[HDF1: PVs]
            TIFF1[TIFF1: PVs]
        end

        subgraph BK ["Camera backend (BaseCamera subclass)"]
            B1[TeledyneOryx]
            B2[TeledyneKinetix]
            B3[OrcaFireDCAM]
            B4[OrcaFireGenTL]
            B5[Simulator]
        end

        REG[core/registry.py<br/>@register / open_any]
        NTA[NTNDArray server<br/>pvAccess]
        H5P[HDF5 plugin<br/>writes /exchange/data]
        TFP[TIFF plugin]
        IPC[UNIX-socket JSON-RPC<br/>/tmp/detector_ioc_<prefix>.sock]
    end

    subgraph GUI ["Qt GUI subprocess"]
        CAP[ca_proxy<br/>CA + PVA client]
        IPCC[ipc_client<br/>full backend surface]
        QG[qt_gui.py]
    end

    B1 & B2 & B3 & B4 & B5 --> REG
    REG --> IOC
    IOC --> NTA
    IOC --> H5P
    IOC --> TFP
    IOC --> IPC
    IPC <--> IPCC
    IPCC --> QG
    CAP --> QG
```

The driver process owns the camera. The Qt GUI runs as a **separate
subprocess** that talks back through three channels: CA (for the
standard IOC PVs), PVA (for the live image stream), and a UNIX
socket for the full backend surface (every GenICam node on an Oryx,
every DCAM property on an Orca, every PVCAM param on a Kinetix).

The reason for the split: PVCAM registers signal handlers that
Qt's `QApplication` clobbers when they share a process. The driver
then silently starves the camera's DMA loop. Running Qt in a
separate process side-steps the issue uniformly, not just for PVCAM.

## Supported cameras

| Backend module                                            | Camera                        | SDK                            |
|-----------------------------------------------------------|-------------------------------|--------------------------------|
| `detectors.cameras.teledyne.oryx`                         | Teledyne FLIR Oryx            | Spinnaker C API (ctypes)       |
| `detectors.cameras.teledyne.kinetix`                      | Photometrics Kinetix          | PVCAM (ctypes)                 |
| `detectors.cameras.hamamatsu.orca_fire_dcam`              | Hamamatsu Orca Fire           | DCAM-API Lite + FireBird       |
| `detectors.cameras.hamamatsu.orca_fire_gentl`             | Hamamatsu Orca Fire           | Harvesters / GenTL + eGrabber  |
| `detectors.cameras.simulator`                             | synthetic frames              | none (built in)                |

Backends auto-register via the `@register` decorator in
`core/registry.py`. Adding a camera is a single new file under
`cameras/<vendor>/`, see the standalone docs for the skeleton.

## Data flow

```{mermaid}
sequenceDiagram
    participant SDK as Vendor SDK
    participant BK as Backend
    participant IOC as DetectorIOC
    participant NTA as PVA NTNDArray
    participant H5 as HDF5 plugin
    participant CL as Client (pystream / tomoscan)

    SDK-->>BK: frame callback (vendor thread)
    BK->>IOC: _notify_frame(np.ndarray, metadata)
    IOC->>NTA: publish throttled (~30 fps)
    IOC->>H5: enqueue (unthrottled)
    H5->>H5: write to /exchange/data (uint16)
    NTA-->>CL: NTNDArray on image1:ArrayData
    H5-->>CL: /exchange/data via tomoscan / pyqtstream
```

Frames land once in the IOC and fan out to the writers that are
enabled. The HDF5 writer never drops; the PVA stream drops frames
to keep display at ~30 fps.

## HDF5 layout from JSON

The `/exchange/data` layout (and dark / white dataset paths) is
driven by `detectors/hdf5_layout.json` — ships with the package,
read at every capture start. Edit the file to change which
`FrameType` goes to which dataset:

```json
{
  "frame_types": {
    "Projection": "/exchange/data",
    "FlatField":  "/exchange/data_white",
    "DarkField":  "/exchange/data_dark"
  }
}
```

No AreaDetector XML dependency. If the JSON is missing, the plugin
falls back to the historical hardcoded map so writing never fails.

The recording **metadata template** (`detectors/recording_metadata.json`)
is a separate concern — consumed by pystream's TIFF recording path to
build each recording's `metadata.json` sidecar.

## Startup / shutdown

```bash
python run_ioc.py --list-cameras
python run_ioc.py --camera teledyne.oryx --prefix ORYX: --gui
python run_ioc.py --gui-only --prefix ORYX:              # reattach GUI
pkill -TERM -u $USER -f "run_ioc.py.*--prefix ORYX:"      # graceful stop
```

`Ctrl-C` in the launch terminal is the intended shutdown; it releases
the camera SDK, cleans up the UNIX socket, and terminates the GUI
subprocess.

## Public API / extension points

* **New camera backend**: file under `cameras/<vendor>/`,
  subclass `BaseCamera`, add `@register`, implement `open / close /
  get_param / set_param / list_params / start_acquisition /
  stop_acquisition / acquire_frame`.
* **New plugin PV surface** (e.g. a `ROI1:` plugin): add a `PVGroup`
  under `server/`, wire it in `server/ioc.py`.
* **GUI tweak**: `gui/qt_gui.py` is standalone — can be run against
  any IOC prefix (`python -m detectors.gui.qt_gui --prefix ORYX:`).

## Dependencies

* `caproto` — EPICS CA server library.
* `pvapy` — pvAccess NTNDArray server.
* `PyQt5` — GUI subprocess only.
* `h5py`, `numpy`, `imageio` — HDF5 / TIFF writers.
* Vendor SDKs installed at **system level** (`/usr/local/hamamatsu_dcam/`,
  `/opt/pvcam/`, `/APSshare/epics/.../ADSpinnaker/...`). None of them
  are pip packages.

## Known gotchas

* **Exclusive camera access**. Spinnaker, PVCAM and DCAM all claim
  the camera per-process. Stop any running vendor C++ IOC
  (`32idbSP1`, `KTX1`, etc.) before starting the detectors Python
  IOC — and vice versa.
* **PVCAM default exposure resolution is seconds**. On first open
  the Kinetix backend forces `PARAM_EXP_RES` to microseconds; a
  10 ms exposure would otherwise round to 0.
* **DCAM needs `RTLD_GLOBAL`**. The backend does this; the FireBird
  frame-grabber kernel module can't resolve symbols otherwise and
  DCAM reports `NOCAMERA`.
* **Oryx `MaxSizeX_RBV` auto-updates with binning** (post-bin
  reported max). Clients that cache a value must re-read after a
  binning change — see pystream's `_apply_binning` and bl_gui's
  `_apply_cam_binning` for the correct sequence.
* **PVField `_to_str(None)` returned the literal `"None"`** before
  fixing — any downstream `mkdir` then created a `None/` directory
  in the cwd. Both HDF5 and TIFF plugins now refuse to write on an
  empty FilePath.

## Future / open questions

* MCP server wrapper exposing a subset of the backend surface so
  Claude Code / Desktop can drive motors + exposure + capture from
  outside pystream. Low priority until a second client actually
  wants it — see {doc}`beamline-agent` for the trade-off.
* Per-camera `recording_metadata.json` variants (one for Oryx, one
  for Kinetix, …) selected by the active backend — currently a
  single template with hardcoded Oryx PV names.
