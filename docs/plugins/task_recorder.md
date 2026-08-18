# Task Recorder

Records the motor moves you make while performing any repeatable
beamline task — alignment, sample positioning, scan setup, whatever
has a defined motor set — paired with a detector frame after each
move. You can then LOAD a past recording, REPLAY it as an automated
procedure, and PUBLISH the good ones as named **tools** for one-click
future runs. The AI agent also reads every recording and can describe
the exact procedure back to you.

**Beamline-agnostic core feature.** The recorder engine, browser,
replay engine, published-tools store, and AI-agent core tools all
live in `pystream` core — every beamline gets them. Beamlines
OPTIONALLY pre-populate the task dropdown by exposing
`provide_task_templates()`; without that hook the dialog falls back
to a free-text task name + manual PV table.

## Where it lives

Top toolbar → **🎥 Task Rec** (next to *HDF5 Viewer*).

## The workflow — teach, refine, publish, execute

1. **Define the task**: pick a task template (or type a free-text name),
   confirm the motor list, and edit the auto-filled Context text on
   the right — that context is your saved description of what the task
   does and why. Auto-saved to `~/.pystream/task_contexts.json`.
2. **Record**: press ● Start, perform the procedure through whichever
   GUI you normally use. The recorder passively watches the motor RBVs
   and captures a detector frame after each move burst settles. Stop
   when done. Iterate until a replay runs cleanly.
3. **Publish**: 📂 Load the good session → **★ Publish as tool** → give
   it a name. Re-publish under the same name to overwrite (e.g. after
   a PV change or hardware reconfiguration).
4. **Execute**: 🛠 Tools → ▶ Run on the row you want. One click, same
   confirmation dialog + progress + abort as manual replay.

## Session directory layout

```
~/.pystream/task_recordings/
    <task_slug>/                       # e.g. zone_plate, sample, my_new_task
        <YYYYMMDD_HHMMSS>/             # one session per demonstration
            actions.jsonl              # append-only event log
            frame_0000_start.tif       # initial detector state
            frame_0001.tif             # state after 1st move burst
            frame_0002.tif             # state after 2nd move burst
            …
            README.md                  # auto-written on Stop
```

One detector frame per move burst — not one per RBV callback and not
a before/after pair, so recording storage stays modest even for long
sessions. The `frame_0000_start.tif` capture at Session Start gives
the agent a baseline of the initial state.

## Persistent state

| File / dir | What it stores |
|---|---|
| `~/.pystream/task_recordings/` | All recorded sessions, keyed by task slug |
| `~/.pystream/task_contexts.json` | Per-task Context editor text (auto-saved override on top of curated defaults) |
| `~/.pystream/task_tools.json` | Published tools: name → source session + motor snapshot |

**Legacy migration**: if `~/.pystream/alignment_examples/`,
`alignment_contexts.json`, or `alignment_tools.json` still exist from
before this feature was renamed, they are moved automatically to the
new names on first import (only if the destination doesn't already
exist; no data loss). One-time and idempotent.

## bl32ID task templates

`bl32ID/task_templates.py` curates the beamline's standard tasks:

| Order | Task (slug) | Motors monitored | Focus |
|---|---|---|---|
| 1 | Detector (`detector`) | Det Focus (Z), Det Rotation | Focus & rotation |
| 2 | Zone Plate (`zone_plate`) | ZP X, ZP Y, ZP Focus (Z) | Position & focus |
| 3 | Phase Ring (`phase_ring`) | Phase Ring X, Phase Ring Y | Position |
| 4 | Condenser (`condenser`) | Cond X, Cond Y, Cond Z, Cond Pitch | Positions & angles |
| 5 | Pinhole (`pinhole`) | Pinhole X, Pinhole Y | Position |
| 6 | Beam Stop (`beam_stop`) | Beamstop X, Beamstop Y | Position |
| — | Sample (`sample`) | Sample Top X, Sample Top Z, Rotary | Per-scan positioning |
| 7 | Final Joint Refinement (`final_joint_refinement`) | *all 15 optics axes* | Joint refinement across all elements |

Motor PVs mirror the beamline's `txmOptics.substitutions` file
(`db/txmOptics.template` macros in the txmOptics EPICS module).
Motors marked `x` in that file (`CONDENSER_YAW`, all `FURNACE_*`) are
omitted — no hardware. Detector rotation isn't in the substitutions
file; the PV `32idbTXM:nf:m2` is picked up from bl_gui's Queensgate#4
panel — verify on the live beamline.

Each task also carries a **context string** that auto-fills the
dialog's Context editor on the right the moment you pick the task
(and any edits you make override the default, auto-saved per task).

## Recording a session

1. Pick a task from the dropdown. Motor list + Context populate
   automatically. Uncheck any motor you don't want captured; edit the
   Context on the right if you want to add specifics.
2. Click **● Start recording**.
3. Do the task through whichever GUI you normally use (bl_gui, MEDM,
   caput on the command line — all fine, the recorder subscribes to
   `.RBV` and doesn't care who wrote the setpoint).
4. Optional: **📸 Snapshot** for a checkpoint frame outside a move;
   **📝 Add note** to annotate what you just did.
5. Click **■ Stop recording**. Add an optional closing note when
   prompted.

## Browsing + replaying past sessions

**📂 Load** opens a three-pane browser:

- **Left**: every task with recorded sessions.
- **Middle**: sessions for the selected task (newest first), with
  move count and opening-note preview.
- **Right**: the README + a compact action log for the selected
  session.

Two actions on the selected session:

- **▶ Run this task** — replays the exact motor sequence with
  `caput -c`. Motors that moved together in a recorded burst are
  commanded concurrently. Each step blocks on DMOV before the next
  starts. Failures are logged and the replay continues — hit **■ Abort**
  to stop after the current step. 60 s per-motor timeout as a safety.
- **★ Publish as tool** — promotes the session to a named tool in
  the Tools dialog. Prompt gives a default name (the task's display
  name) plus an optional description; publishing an existing name
  prompts to overwrite (that's how you update a tool after a PV
  change or hardware reconfiguration).

**Absolute positions.** Replay commands the exact `to` values from
the recording — safe when the beamline is in a similar state as when
recorded (usually the case for alignment/positioning procedures).
Read the confirmation dialog's motor list before pressing Yes.

## Published tools (🛠 Tools)

Click **🛠 Tools** in the main dialog to open the Tools list. Every
published tool is one row: name, source task, session id, move count,
and per-row buttons:

- **▶ Run** — same confirmation + replay as browser-Run
- **ℹ** — motors, source session, published timestamp, description
- **✕** — remove the tool from the store (source recording on disk
  is kept)

Broken tools (source recording deleted) surface a warning when Run
is pressed rather than silently trying to replay a missing session.

## How the AI agent uses recordings

Two read-only, beamline-agnostic tools registered in
[agent_core_tools.py](../../src/pystream/agent_core_tools.py):

| Tool | Purpose |
|---|---|
| `list_task_recordings()` | Enumerate every task with recorded sessions |
| `read_task_recording(task_slug, session_id=None)` | Load one session (defaults to latest) |

These are ALWAYS in the agent's catalog — regardless of which
beamline is active or whether any beamline is active at all. The
core prompt tells the agent to call `list_task_recordings()` first
whenever the user asks how to perform any repeatable beamline
procedure, then use the recorded sequence as a template.

## Event schema (actions.jsonl)

Line-delimited JSON; one row per event.

```json
{"ts":..., "type":"session_start", "element":"Zone Plate",
 "motors_monitored":[{"label":"ZP X","pv":"32idbTXM:mcs2:c1:m13"}, …],
 "opening_note":"…", "move_threshold":1e-4, "burst_ms":400,
 "start_frame":"frame_0000_start.tif"}

{"ts":..., "type":"motor_move",
 "motors":[{"pv":"…","label":"ZP X","from":1.234,"to":1.500,"delta":0.266}, …],
 "frame":"frame_0001.tif",
 "duration_s":2.3}

{"ts":..., "type":"snapshot",  "tag":"good", "frame":"snap_0007.tif"}
{"ts":..., "type":"note",      "text":"trying finer step now"}
{"ts":..., "type":"session_end","closing_note":"…","elapsed_s":312.4,
 "moves":12,"frames":13}
```

The `"element"` key in `session_start` is kept as the JSONL field
name for backward compat with existing recordings — semantically it's
the task display name.

## Tunables

- **`move_threshold`** (default `1e-4` motor units) — RBV changes
  smaller than this are ignored (filters encoder chatter).
- **`burst_ms`** (default `400` ms) — how long the recorder waits
  after the last RBV callback before deciding a move burst has
  settled and writing the row. Higher = merges more concurrent motion
  into one row; lower = more rows.

Both are per-session; tweak by calling `TaskRecorder.start(...,
move_threshold=…, burst_ms=…)` directly. The dialog uses the defaults.

## Adding task-template pre-population on a new beamline

In your beamline package's `__init__.py`:

```python
def provide_task_templates() -> dict[str, dict]:
    return {
        "My Mirror alignment": {
            "context": "Align the mirror after energy change.\n\n…",
            "motors":  [{"label": "Pitch", "pv": "BL:mir:pitch"},
                        {"label": "Roll",  "pv": "BL:mir:roll"}],
        },
        "My Slits alignment": {
            "context": "…",
            "motors":  [{"label": "H gap", "pv": "BL:slt:hgap"}, …],
        },
    }
```

The Task Recorder queries this hook every time it's opened; tasks
appear in insertion order in the dropdown. Every beamline also
automatically gets a "— free-text —" fallback entry so one-off
tasks don't require code changes. The bare-list form
`{"Task Name": [{"label","pv"}, …]}` is also accepted for backward
compat but omits the auto-filled context.
