# Architecture

Technical overview of the beamline software stack at APS 32-ID, written
for software and AI engineers joining the project. Each component gets
its own page below with its internal design, data flow, extension
points and known gotchas; this page is the map that connects them.

```{toctree}
:maxdepth: 1

pystream
bl_gui
detectors
beamline-agent
beamlines-procedures
xanes_gui
```

## The stack

```{mermaid}
flowchart TB
    subgraph Hardware
        CAM[Camera<br/>Oryx / Kinetix / Orca]
        MOT[Motors]
        SHUT[Shutters / valves]
    end

    subgraph IOCs ["EPICS IOCs (CA / PVA)"]
        AD[AreaDetector C++ IOC<br/>32idbSP1 Oryx]
        DET[detectors Python IOC<br/>run_ioc.py]
        MIOC[motor IOCs]
        TS[tomoscan IOC]
    end

    subgraph Clients ["Client applications"]
        PS[pystream<br/>live viewer + plugins]
        BG[bl_gui<br/>layout-driven control panel]
        XG[xanes_gui<br/>energy scan orchestrator]
    end

    subgraph Agent ["AI layer (in-process in pystream)"]
        BA[beamline-agent<br/>chat + tool-use loop]
        BP[beamlines-procedures<br/>markdown knowledge base]
    end

    CAM --> AD
    CAM --> DET
    MOT --> MIOC
    SHUT --> MIOC

    AD -. PVA image1:ArrayData .-> PS
    DET -. PVA image1:ArrayData .-> PS

    AD -. CA cam1 / HDF1 .-> BG
    AD -. CA cam1 .-> PS
    DET -. CA cam1 / HDF1 .-> BG
    MIOC -. CA .-> BG
    MIOC -. CA .-> PS
    TS -. CA .-> BG
    TS -. CA .-> XG

    PS === BA
    BA -. reads at startup .-> BP
    BA -. calls back into pystream .-> PS

    XG -. file handshake<br/>~/.pystream/qgmax_request.json .-> PS
```

Three layers:

1. **IOCs** — EPICS servers in front of each piece of hardware. Two camera
   paths coexist: the vendor **AreaDetector** C++ IOC and the in-house
   **detectors** Python IOC. Both speak the same `cam1:` / `HDF1:` / `image1:`
   PVs so clients don't care which one is running.
2. **Clients** — Qt applications that talk to IOCs over Channel Access
   (control / small values) and pvAccess (image stream). Clients never
   call each other directly; they coordinate through PVs or through
   small file handshakes.
3. **AI layer** — the agent is embedded inside pystream's process, uses
   pystream's host context to touch the live frame + plugin dispatcher,
   and reads its procedure library from a separately-shipped package.

## Who owns what

| Component                                                     | Repo                                             | What it exists for                                                                 |
|---------------------------------------------------------------|--------------------------------------------------|------------------------------------------------------------------------------------|
| [pystream](pystream.md)                                       | `pystream`                                       | Live image viewer + beamline-specific control dialogs                              |
| [bl_gui](bl_gui.md)                                           | `bl_gui`                                         | Generic layout-driven PV panel; drives motors / valves / cam parameters            |
| [detectors](detectors.md)                                     | `detectors`                                      | Multi-camera Python IOC replacing AreaDetector (Oryx/Kinetix/Orca via ctypes SDK)  |
| [beamline-agent](beamline-agent.md)                           | `beamline-agent`                                 | In-process AI chat + sub-agent dispatch + status monitor + image/HDF5 viewers      |
| [beamlines-procedures](beamlines-procedures.md)               | `beamlines-procedures`                           | Hand-authored markdown procedures the agent reads at run time                      |
| [xanes_gui](xanes_gui.md)                                     | `xanes_gui`                                      | Energy-scan GUI + headless CLI; triggers QGMax interlock between steps             |
| tomoscan                                                      | *upstream, APS*                                  | Fly / step scan sequencer; writes `/exchange/data` HDF5 via AD's HDF5 plugin       |

## Shared conventions

A few patterns show up repeatedly across the stack:

**PV namespace**. Camera-side PVs follow AreaDetector conventions:
`<prefix>cam1:…` for the detector, `<prefix>HDF1:…` for the file writer,
`<prefix>image1:ArrayData` for the live PVA stream. Both the vendor
IOC (`32idbSP1:`) and the detectors Python IOC (user-chosen prefix
via `run_ioc.py --prefix`) use the same names so clients can target
either.

**Stream vs control**. Images move over **pvAccess** (NTNDArray on
`image1:ArrayData`). Everything else — setpoints, readbacks, motor
positions, HDF5 file paths, status — moves over **Channel Access**.
Clients that need both open two subscriptions.

**Config and state in `~/.pystream/`**. Per-user state (viewer config,
layout settings, procedures copy, QGMax request / response files)
lives under `~/.pystream/`. Nothing user-specific is baked into the
packages.

**Cross-process coordination via file handshake**. When two clients
need to coordinate (xanes_gui triggering a QGMax optimization in
pystream, for instance) they do it by writing a tiny JSON file to
`~/.pystream/`. No sockets, no RPC. The receiver polls the file. This
pattern is simple and survives either side restarting; the trade-off
is a few hundred ms of latency and reliance on a shared filesystem.

**Agent is in-process, tools are inline**. The AI agent lives inside
pystream's event loop and calls Python functions directly (no MCP, no
RPC). This is intentional: tools need cheap access to the current
image, PV cache, Qt widgets, and plugin dispatcher. See
{doc}`beamline-agent` for the trade-off discussion.

## Where to go next

* Reading in order below gives the clearest picture.
* Each page is self-contained; you can skip to the one you need.
* The gotchas sections are the thing most worth reading before
  touching a component — most are documented because they ate a day
  of debugging the first time.
