# bl_gui

A layout-driven Qt control panel. The scientist sees motor cards,
shutters, PV setpoints and readbacks; the developer sees a JSON file
describing all of them.

## Purpose in one sentence

Render a user-editable, per-beamline control panel of motors + PV
fields + valves + shortcut buttons, with CA monitors keeping every
readback live and an in-GUI edit mode that lets the scientist
rearrange panels and save the layout back to JSON.

## Where it fits

```{mermaid}
flowchart LR
    AD[AreaDetector IOC]
    MIOC[motor IOCs]
    VIOC[valve / shutter IOCs]
    EN[energy / optics IOCs]
    BG[bl_gui]
    LAY[layouts/*.json]
    USER[~/.bl_gui/layout.json]

    LAY -- bundled defaults --> BG
    USER -- overrides --> BG
    MIOC -. CA .-> BG
    VIOC -. CA .-> BG
    AD -. CA cam1 .-> BG
    EN -. CA .-> BG
    BG -. caput_bg .-> MIOC
    BG -. caput_bg .-> VIOC
    BG -. caput -c (apply bin) .-> AD
```

## Architecture

```{mermaid}
flowchart TB
    subgraph Process ["bl_gui process"]
        subgraph Win ["Win (QMainWindow)"]
            TOP[top bar<br/>beamline name + font slider + edit toggle]
            TABS[QTabWidget<br/>User Mode / Expert Mode / Alignment / ...]
            CANVAS[per-tab canvas<br/>free-positioned Panels]
        end

        subgraph State ["Runtime state"]
            PANELS[(self._panels<br/>panel_key -> Panel)]
            FIELDS[(self._pv_fields<br/>panel_key -> field_id -> PVField)]
            MOTORS[(self.mcs: list[MC])]
        end

        subgraph PVLayer ["PV layer"]
            PVE[PVEngine<br/>pvaccess.Channel + CA monitors]
            CAPUT[caput_bg<br/>ThreadPoolExecutor subprocess caput]
        end

        subgraph Edit ["Edit mode"]
            DRAG[drag + resize panels]
            RMB[right-click add / rename / delete widget]
            SAVE[_save_layout -> JSON]
            AUTO[5s autosave timer]
        end
    end

    LAY[layout.json] -- load on startup --> Win
    PVE -- updated(pv, value) --> FIELDS
    FIELDS -- user presses Enter --> CAPUT
    MOTORS -- user clicks button --> CAPUT
    SAVE -- writes --> LAY
    AUTO -- fires while in edit mode --> SAVE
```

Three layers to keep in mind:

* **Layout (declarative)**: `layouts/<beamline>.json` + user override at
  `~/.bl_gui/layout.json`. Describes tabs, panels, panel positions,
  PV fields and motor cards.
* **Runtime objects**: `Panel`, `MC` (motor card), `PVField`,
  `ValveField`. One `PVField` per editable value or readback.
* **PV plumbing**: `PVEngine` runs CA monitors in a background thread
  and emits a single `updated(pv_name, value)` signal; `caput_bg`
  handles writes via subprocess into a 16-worker pool.

## Layout schema (abridged)

Each tab contains panels; each panel contains rows. Row kinds:

| Kind    | Visual                | Writes a PV?                                     |
|---------|-----------------------|--------------------------------------------------|
| `sp`    | QLineEdit             | yes — Enter triggers `caput_bg(pv, text)`        |
| `rb`    | monospace QLabel      | no (readback only)                               |
| `cmb`   | QComboBox             | yes — selection triggers `caput_bg(pv, label)`   |
| `btn`   | QPushButton           | yes — click sends a preset value                 |
| `led`   | coloured ●            | no (readback, color-coded)                       |

Motor cards (`MC`) are a bigger composite: setpoint, readback, nudge
buttons, step size, limits. One per motor record.

## Data flow

```{mermaid}
sequenceDiagram
    participant IOC
    participant PVE as PVEngine
    participant Field as PVField
    participant Win

    Note over PVE,IOC: startup
    Win->>PVE: monitor_many([list of all PVs the layout mentions])
    PVE->>IOC: subscribe pv1
    PVE->>IOC: subscribe pv2
    PVE->>IOC: subscribe pv3

    Note over IOC,Field: steady state
    IOC-->>PVE: value update
    PVE->>Win: updated(pv, value)
    Win->>Field: update_value(value)
    Field->>Field: setText + dirty-colour check

    Note over Field,IOC: user types + Enter
    Field->>Field: _on_sp_return
    Field->>IOC: caput_bg (subprocess)
    IOC-->>PVE: value echo
    PVE->>Win: updated(pv, value)
    Win->>Field: clears dirty style
```

## Edit mode

Click **Edit** in the top bar. State flips:

* All read-only labels and buttons are temporarily disabled so clicks
  go into panel-move / resize instead of user actions.
* Right-click menus on panels / motors / PVFields expose
  rename / add row / delete.
* A QTimer autosaves `layout.json` every 5 seconds while in edit mode.
* Click Edit again (or close the window) → final save, timer stopped.

## Camera binning

bl_gui's camera section has `Bin X` / `Bin Y` setpoint fields hooked to
a special `_apply_cam_binning` handler. PVField's default `caput_bg`
is disconnected; the handler owns the full sequence:

1. `MinX=0, MinY=0`
2. `BinX, BinY`
3. 200 ms sleep (let the Oryx driver update `MaxSizeX/Y_RBV`)
4. caget fresh `MaxSizeX_RBV / MaxSizeY_RBV`
5. `SizeX, SizeY = new MaxSize`

Each write uses `caput -c` on a background thread so the GUI stays
responsive and the writes serialize cleanly. See `_apply_cam_binning`
in `main_window.py` for the detailed rationale (race condition with
the fire-and-forget pool, Oryx auto-rescales MaxSize after binning,
etc.).

## Autosave

Two separate "autosaves" to keep straight:

* **Edit-mode layout autosave** — writes the JSON layout every 5 s
  while edit mode is on, so a crash or forced close doesn't lose the
  user's rearrangement.
* **Snapshot autosaver** — a periodic PV-value snapshot (hourly) that
  captures the current motor / shutter / cam state, useful for
  reproducing a past configuration.

## Public API / extension points

* **Add a new row to a panel**: edit the layout JSON (or do it in
  edit mode and let the autosave write it).
* **Add a new row kind**: implement a `PVField` subclass in
  `pv_field.py`, add the kind to `_build_inner`.
* **Add a new tab**: `+ Tab` button in edit mode, or add the tab name
  to `_DEFAULT_TABS` and run `_build_all_panels(tab_name)`.
* **New beamline**: fork `layouts/<bl>.json`, point `bl_gui --layout`
  at it.

## Dependencies

* `PyQt5`, `pvapy` — hard.
* No pystream dependency; bl_gui runs standalone.
* Uses system `caput` from EPICS base for writes (subprocess).

## Known gotchas

* **Each tab builds its own camera panel** with its own `cam_binx` /
  `cam_biny` fields. Any handler that walks `_pv_fields.values()`
  must disambiguate with `self.sender()` or it'll always drive the
  first-registered tab (User Mode). See `_apply_cam_binning` for
  the pattern.
* **PVField `returnPressed` default fires `caput_bg`**. If you connect
  a custom handler on top, both fire — handlers that need to own the
  write path should `disconnect()` first (see `_apply_cam_binning`).
* **`caput_bg` is unordered** (16-worker pool). If writes must land
  in order (anything that cross-constrains PVs — binning + size,
  min + size, trigger-mode + exposure), use a single background
  thread with blocking `caput -c` or you'll race.
* **Layout JSON format drifts** when new row kinds are added.
  Backward-compat: unknown kinds load as `?? <kind>` labels (visible
  to the user; nothing crashes).

## Future / open questions

* The subprocess `caput` could move to pyepics for lower latency and
  no fork overhead. Trade-off: pyepics has its own init/cleanup
  gotchas and would need to coexist with pvaccess monitors.
* The layout schema could grow a per-row "role" (motor / shutter /
  cam-geometry) to make the AI agent's `list_pvs_for_motor` lookup
  trivial.
