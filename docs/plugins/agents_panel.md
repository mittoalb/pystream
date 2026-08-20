# Agents Panel

Live "who's running" view for every AI agent the beamline is running —
pystream's Röntgen, any subagent it spawns, and cross-machine workers
(e.g. a `tomogui-batch` on a GPU host). Compact card list, indented
under parents so the tree is visible at a glance.

Opened from pystream's top toolbar via the **👥 Agents** button; ships
as a non-modal standalone window with an explicit dark palette so it
reads as a monitor / status console (leave it open on a second
monitor while you work).

**Ships with `beamline-agent`, not pystream.** Install with
`pip install pystream[ai]` (or `pip install beamline-agent`); without
it, no 👥 button — pystream still runs. The registry file format
below is stable, so any code that already writes to
`~/.aps_agents/agents.json` (including cross-machine workers) shows
up here as soon as somebody with beamline-agent opens the panel.

## What you see

Each agent that publishes to the shared registry renders as one card:

```
● Röntgen                      pystream01 · main            1m 42s
  calling tool: read_pv
─────────────────────────────────────────────────────────────
    ○ recon_subagent           pystream01 · subagent        0m 08s
      dispatch to gpu01
─────────────────────────────────────────────────────────────
      ● tomogui-batch          gpu01 · worker               0m 04s
        recon 3/12 (AI COR)
        ▓▓▓░░░░░░░░ 25%
```

- **Left border color + dot**: state indicator
  - green = running, blue = waiting, gray = idle, purple = starting,
  - slate = done, red = error, orange = stale (no update in TTL window)
- **Name** and **host · kind** metadata
- **Activity**: one-line summary the agent published (truncated to 100 chars)
- **Progress bar**: shown only when the agent reports `(done, total)`
- **Elapsed**: time since the agent started
- **Tooltip**: full record (id, parent, timestamps) on hover

Indentation shows parent → child. Roots surface at zero indent; when
a parent has already been purged, its orphaned children promote to
roots so they stay visible.

## The shared registry

Single JSON file: `~/.aps_agents/agents.json`, dict of
`{agent_id: record}`. Each record:

```json
{
  "id":         "Röntgen-pystream01-42137-a3f9",
  "name":       "Röntgen",
  "kind":       "main",
  "parent":     null,
  "host":       "pystream01",
  "state":      "running",
  "activity":   "calling tool: read_pv",
  "progress":   null,
  "started_ts": 1755600000,
  "updated_ts": 1755600102,
  "ttl_s":      120,
  "linger_s":   0
}
```

- **`state`**: `starting` / `running` / `waiting` / `idle` / `done` /
  `error`. The panel synthesizes `stale` for records whose
  `updated_ts + ttl_s < now`.
- **`ttl_s`**: agent-owned freshness budget. The panel dims the card
  once expired; the record is still there so a crashed agent doesn't
  silently disappear.
- **`linger_s`**: after `finish()` / `error()`, the record stays in
  the file (and the view) for this long, so completions and failures
  don't blink past the user.

Atomic writes via tempfile + rename — the same crash-safe pattern
already used by `task_recorder.py` and the plugin-settings machinery.

## Cross-machine

`~/.aps_agents/` sits under the user's home directory, which at APS
is normally NFS-mounted on every beamline host. tomogui-batch on
gpu01 writes to the same file pystream on pystream01 reads — no
network code, no daemon. If a host doesn't share home, add an SSH
relay later; the registry format is the API.

## Publishing status from your own code

Any Python that wants to show up in the panel imports one helper:

```python
from beamline_agent.status import AgentStatusPublisher

# For a short-lived subagent — context manager marks state on entry,
# and finish/error on exit (including on unhandled exceptions).
with AgentStatusPublisher(
    name="recon_subagent",
    kind="subagent",
    ttl_s=30,
) as pub:
    pub.activity("dispatching to gpu01")
    ...
    pub.progress(3, 12, "recon 3/12 (AI COR)")
    ...
    pub.finish("12 recons in 6m 40s")
```

For long-lived agents (the AI panel's Röntgen, which lives as long
as pystream), construct once and keep a reference:

```python
self._status_pub = AgentStatusPublisher(
    name="Röntgen", kind="main", ttl_s=120, linger_s=0)
self._status_pub.idle("waiting for message")
# ... later ...
self._status_pub.activity("thinking: how do I align the zone plate?")
```

Methods:

| Method | Meaning |
|---|---|
| `activity(text)` | Set `state=running` + update activity line |
| `waiting(text="")` | Set `state=waiting` (blocked on IO/user/peer) |
| `idle(text="idle")` | Set `state=idle` (alive but nothing to do) |
| `progress(done, total, text="")` | Attach a fraction (renders a progress bar) |
| `finish(summary="")` | Set `state=done`, close the record |
| `error(text)` | Set `state=error`, close the record |

## Spawning subagents that show up as children

Before spawning a subprocess, set an env-var so the child inherits
its parent id automatically:

```python
import subprocess, os
from beamline_agent.status import AgentStatusPublisher, child_env

subprocess.Popen(
    ["ssh", "gpu01", "tomogui-batch", "--folder", "/data/scan_00042"],
    env={**os.environ, **child_env(pub.id)},
)
```

Inside the child (e.g. the `tomogui-batch` CLI), a
`AgentStatusPublisher(name="tomogui-batch", parent=None)` will
auto-pick up `APS_AGENT_PARENT_ID` from the environment. No wiring
needed on the child side beyond calling the constructor.

## Refresh model

- **QFileSystemWatcher** on the registry file + its directory
  → repaint as soon as any agent writes.
- **1 s fallback QTimer** → guarantees liveness on NFS mounts where
  inotify events are unreliable, and keeps the elapsed-time labels
  ticking.

The **⟳** button in the panel header forces an immediate reload if
anything ever looks stuck.

## What's NOT in this panel (yet)

- Graphical node-and-edge diagram (Tier 2). The card list carries
  the same information more densely; the diagram is a future upgrade
  when the tree gets wide enough that the tabular view stops working.
- Historical timeline (which agent ran when, who called whom).
  Records purge after `linger_s`; nothing keeps a persistent log.
  Add a JSONL sink to the same registry writes if that becomes
  interesting later.
- Interactive control (kill an agent, promote a subagent to fresh
  chat). Status-only for now.
