# xanes_gui

PyQt5 orchestrator for XANES (X-ray Absorption Near Edge Structure)
scans at bl32ID. Covers 1D energy scans, 2D (XANES2D) scans, and the
QGMax interlock that keeps the beam optimised between energy points.

## Purpose in one sentence

Define an energy scan range (start / stop / step, or Δedge-based,
or imported CSV), execute it against the mono / undulator / zone-plate
chain, trigger QGMax between steps when configured, stream reference
curves and the live spectrum, and dump everything to HDF5.

## Where it fits

```{mermaid}
flowchart LR
    USER[scientist]
    XG[xanes_gui<br/>gui.py / gui_2d.py]
    HL[headless.py<br/>CLI]
    REMOTE[tomoscan remote host<br/>via SSH]
    SCRIPT[xanes_energy.py]
    IOCS[EPICS IOCs<br/>energy / undulator / ZP]
    PS[pystream]
    QG[QGMaxDialog in pystream]
    H5[HDF5 scan file]

    USER -- select element / range --> XG
    XG -- qgmax_request.json --> QG
    QG -- qgmax_response.json --> XG
    XG -- ssh exec --> REMOTE
    REMOTE -- runs --> SCRIPT
    SCRIPT -- CA + PVA --> IOCS
    IOCS -- image + attrs --> PS
    SCRIPT --> H5
    HL -- scripted CLI --> XG
```

The GUI is launched from the **pystream** conda env (which has PyQt5
+ pyepics + pvaccess + h5py). For 3D scans it SSHes into a `tomoscan`
env on the remote IOC host and runs `xanes_energy.py` there.

## Architecture

```{mermaid}
flowchart TB
    subgraph Process ["xanes_gui process"]
        subgraph UI ["Tabs"]
            SCAN[Scan Setup<br/>element / edge / range]
            PV[PV Settings<br/>EPICS / PVA / SSH / curves]
            PLOT[Live Spectrum<br/>pyqtgraph]
            REF[Reference Curves<br/>calibrated + simulated]
            TERM[Embedded Terminal<br/>script stdout/stderr]
        end

        subgraph Engine ["Scan engine"]
            SEQ[step sequencer]
            INT[QGMax interlock<br/>write ~/.pystream/qgmax_request.json]
            RUN[SSH exec xanes_energy.py]
            POLL[poll qgmax_response.json]
        end

        subgraph IO ["Config / state"]
            CFG[~/.xanes_gui/config.json]
            CURVES[Calibrated / Curves dirs]
            REQ[~/.pystream/qgmax_request.json]
            RSP[~/.pystream/qgmax_response.json]
        end
    end

    subgraph External ["External process (remote via SSH)"]
        SCRIPT[xanes_energy.py<br/>in tomoscan env]
        IOCS[(EPICS IOCs)]
        H5[(HDF5 scan file)]
    end

    SCAN --> SEQ
    SEQ --> INT
    INT --> REQ
    SEQ --> RUN
    RUN --> SCRIPT
    SCRIPT --> IOCS
    SCRIPT --> H5
    SEQ --> POLL
    POLL --> RSP
    CFG --> UI
    CURVES --> REF
    PLOT -. live PVA .-> IOCS
```

Three major subsystems:

* **GUI tabs** — scan setup, PV plumbing, live-spectrum plot,
  reference curves, embedded terminal.
* **Scan engine** — step sequencer that advances energy, triggers
  QGMax between steps, launches the actual acquisition script
  remotely over SSH.
* **IO** — all state lives in `~/.xanes_gui/config.json` and the
  curve directories; the QGMax interlock uses the shared
  `~/.pystream/qgmax_*.json` files.

## QGMax interlock

Between energy points the scan can require a beam re-optimisation
run by pystream's QGMax dialog. The protocol is a tiny file
handshake:

```{mermaid}
sequenceDiagram
    participant XG as xanes_gui
    participant REQ as ~/.pystream/qgmax_request.json
    participant QG as QGMaxDialog (pystream)
    participant RSP as ~/.pystream/qgmax_response.json

    XG->>REQ: write {cmd: "auto_enable", run_every: N, ts}
    QG->>REQ: poll (every 500 ms)
    QG->>RSP: ack {started_ts, started_at, auto_mode: true}
    Note over XG,QG: QGMax runs its own loop
    QG->>RSP: {last_completed_ts, completed_at}
    XG->>RSP: poll until last_completed_ts > started_ts
    XG->>REQ: next cmd / disable
```

The protocol is deliberately simple (one JSON file each way, polled
once per 500 ms). It survives either side restarting. The receiver
end lives in `pystream/beamlines/bl32ID/qgmax.py::QGMaxBackgroundWatcher`
and runs regardless of whether the QGMax dialog window is open.

The request / response files live under `~/.pystream/` — the same
directory pystream uses for everything else. Earlier versions wrote
to `~/.pystream_*` dotfiles; that path was deprecated.

## Headless mode

`xanes_gui/headless.py` exposes the scan logic without the GUI, for
scripted / batch runs:

```python
from xanes_gui.headless import write_qgmax_request, run_scan
write_qgmax_request("auto_enable", run_every=3)
run_scan(element="Co", edge="K", step_eV=1, ...)
```

`xanes_gui/cli.py` is the thin command-line wrapper around
`headless.py`. The GUI and the CLI share the same scan engine.

## Public API / extension points

* **New energy-range method**: add a tab-panel in `gui.py`, implement
  `build_energy_list()` → list of eV values, feed into the sequencer.
* **New reference curve source**: drop files in the curves dirs set
  in the PV Settings tab, they auto-populate the dropdown.
* **New remote execution target**: change the SSH / env / script-path
  in the PV Settings tab; nothing hardcoded in Python.

## Dependencies

* `PyQt5`, `pyqtgraph` — GUI.
* `pyepics`, `pvapy` — EPICS CA + PVA.
* `h5py` — scan file reader/writer.
* `numpy`, `scipy` — reference curve maths.
* No pystream code dependency. Interacts with pystream only through
  the `~/.pystream/qgmax_*.json` file handshake.

## Known gotchas

* **Launch from the pystream env**, not from a plain Python env. The
  pystream env has the SDKs; `xanes_gui`'s pyproject does not list
  them as hard deps.
* **SSH keys** to the remote tomoscan host must be set up ahead of
  time — the GUI doesn't handle password prompts.
* **Integer step sizes** are a guarantee of the engine, not of the
  user's input. The GUI validates and snaps to integer eV before
  firing a scan.
* **Reference curve files are not shipped** with the package — the
  user supplies them. Missing curves → the plot shows no reference,
  no crash.
* **`qgmax_request.json` is cross-process state**. If pystream was
  restarted but xanes_gui is still waiting on `qgmax_response.json`,
  the response won't arrive — restart xanes_gui or write a dummy
  response.

## Future / open questions

* Replace the file-based QGMax interlock with a dedicated EPICS PV
  so the handshake survives shared-filesystem issues and so a non-
  xanes_gui client (notebook, agent) can trigger QGMax uniformly.
* Direct in-process scan execution when running on the same host as
  the IOC (skip SSH); auto-detect vs force via a config switch.
