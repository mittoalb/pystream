# TXMBot — AI Agent Plugin

An LLM-powered chat assistant embedded in pystream that can answer
questions, observe live beamline state, and (with explicit user
confirmation) take recovery actions.

## Overview

TXMBot is a generic chat panel that talks to a Gateway speaking either the
**Anthropic Messages API** protocol or the **OpenAI Chat Completions**
protocol. The user picks the protocol, supplies the Gateway URL and an API
key, and selects from the models the Gateway exposes.

The agent has access to a tool catalog that lets it observe and (where
explicitly authorized) act on the beamline:

- **Live state** — read EPICS PVs, motors, detector image stats
- **Device health** — diagnose stuck PVs, motors, frozen detector streams
- **Local knowledge base** — markdown docs, PV alias / macro table,
  per-plugin settings
- **Web docs** — registered URLs (vendor docs, wikis) fetched on demand
- **Data** — list and inspect recent XANES2D HDF5 master files
- **IOC recovery** — restart IOCs via user-allowlisted scripts, behind a
  Yes/No confirmation dialog

Tool calls are visible in the chat transcript so the user can see exactly
what the agent did to reach a conclusion.

The plugin appears in the bl32ID toolbar as **AI**.

## Quickstart

1. Click **AI** in the bl32ID toolbar.
2. In the **Gateway** group:
   - Pick **Protocol** (Anthropic Messages API or OpenAI Chat Completions).
   - Enter the Gateway base URL.
     - Anthropic gateways usually take the bare host:
       `https://gateway.example.com`
     - OpenAI gateways usually expect `/v1`:
       `https://gateway.example.com/v1`
   - Enter your API key (saved locally — see
     [Privacy & Storage](#privacy-storage) below).
3. Click **Connect / refresh models** — populates the **Model** dropdown
   from the Gateway.
4. Pick a model. Type a question, press Enter, or click **Send**.

Settings persist across sessions in `~/.pystream/bl32ID_settings.json` under
the `AgentDialog` key.

## Architecture

### Chat vs Agent

TXMBot is **always agentic** — the chat loop is a multi-turn agent loop.
If the model decides to call a tool, the worker executes it, surfaces the
call in the transcript, and feeds the result back to the model. The loop
runs up to `MAX_AGENT_ITERATIONS = 10` per user turn before forcibly
returning. If the model doesn't need a tool (e.g. for a generic question),
the loop runs once and returns immediately.

### Threading

Each chat turn spawns a `_ChatWorker(QThread)` that does the network call.
The GUI thread stays responsive — you can keep operating the rest of
pystream while the model is replying.

A turn in flight disables **Send** until it returns; you can't pile up
overlapping requests.

### Confirmation gate

Tools that mutate state (currently only `restart_ioc`) are wrapped in a
synchronous Yes/No confirmation dialog before they run. The dialog is
created on the GUI thread; the worker thread blocks on the user's answer
via `QMetaObject.invokeMethod(..., BlockingQueuedConnection, ...)`.

The model **cannot bypass** the dialog — confirmation lives in Qt code,
not in the system prompt. If the user clicks **No**, the tool returns
`{"error": "user denied the action", "denied": true}` and the agent moves
on.

## Tool Catalog

19 tools across six categories:

### Live state (read-only)

| Tool | Purpose |
|---|---|
| `read_pv(pv_name)` | Read any EPICS PV value |
| `read_motor(motor_pv)` | Read motor RBV (`.RBV` with fallback) |
| `get_detector_image_stats(detector_pv)` | Min/max/mean/std/percentiles of the current detector frame (no acquire) |

### Device health (read-only)

| Tool | Purpose |
|---|---|
| `check_pv_health(pv_name)` | Connected? alarm severity? value age? Returns one-sentence diagnosis |
| `check_motor_health(motor_pv)` | Decodes `.MSTA` bits — comm error, at limit, slip/stall, fault |
| `check_detector_stream(detector_pv)` | Verifies PVA `uniqueId` is advancing — distinguishes idle vs wedged |

### Network diagnostics (read-only, no sudo)

| Tool | Purpose |
|---|---|
| `ping(host, count)` | Reachability + packet loss + RTT |
| `tcp_check(host, port)` | TCP connect — distinguishes 'host down' / 'firewalled' / 'port not listening' |
| `dns_lookup(host)` | Resolve hostname, plus reverse DNS |
| `list_status_pages()` | Registered live web status URLs (then `fetch_url` to read) |

### Local knowledge base (read-only)

| Tool | Purpose | Source file |
|---|---|---|
| `list_docs()` | List markdown docs the user maintains | `~/.pystream/docs/*.md` |
| `read_doc(name)` | Read one doc (truncated at 20K chars) | same |
| `search_docs(query)` | Substring search across all docs | same |
| `list_pv_aliases()` | Friendly PV names + EPICS macros | `~/.pystream/pv_aliases.json` |
| `resolve_pv(template)` | Expand `$(P)$(M).RBV`-style macros | uses macros from above |
| `list_plugins()` | Pystream plugins with persisted settings | `~/.pystream/bl32ID_settings.json` |
| `get_plugin_settings(name)` | Read one plugin's settings (sensitive fields redacted) | same |

### Web docs (read-only)

| Tool | Purpose | Source file |
|---|---|---|
| `list_url_docs()` | Registered documentation URLs | `~/.pystream/doc_urls.json` |
| `fetch_url(url)` | HTTP GET, HTML auto-stripped to plain text (truncated at 30K chars) | — |

### Data (read-only)

| Tool | Purpose |
|---|---|
| `list_recent_scans(save_dir, pattern, limit)` | Recent HDF5 master files, newest first |
| `read_scan_metadata(path)` | `scan_config` JSON + dataset shapes from a scan file |

### IOC recovery (write — gated)

| Tool | Purpose |
|---|---|
| `list_ioc_scripts()` | Allowlisted IOCs the agent may restart |
| `restart_ioc(ioc_name)` | Run the registered script — **pops a Yes/No dialog first** |

## Knowledge Base — User-Editable Files

When TXMBot opens for the first time, four user-editable files are
auto-created in `$HOME` if they don't already exist. The bootstrap **never
overwrites** existing content.

All user-config lives under a single `~/.pystream/` directory:

```
~/.pystream/
    docs/                            ← markdown reference notes
        README.md                      (created on bootstrap)
    pv_aliases.json                  ← friendly names + EPICS macros
    doc_urls.json                    ← URL list for static reference docs
    status_pages.json                ← URL list for LIVE status pages
    ioc_scripts.json                 ← IOC restart allowlist
    bl32ID_settings.json             ← persisted plugin settings
    qgmax_request.json               ← QGMax handshake (XANES2D ↔ QGMax)
    qgmax_response.json              ← QGMax handshake (XANES2D ↔ QGMax)
```

Legacy files at `~/.pystream_*` and `~/.pystream_docs/` (the old layout)
are migrated automatically on first launch — no manual move required.

### `~/.pystream/docs/`

Drop any number of markdown files here. The agent reads them via
`list_docs` / `search_docs` / `read_doc`. One topic per file works best.

```markdown
# Condensers (32-ID TXM)

Three condensers are configured in optics_config.json: Sigray (focal
43.2 mm, NA 5.21 mrad), Sigray2 (focal 96.9 mm, NA 2.45 mrad), Zeiss
(focal 287.0 mm, NA 1.48 mrad).
...
```

### `~/.pystream/pv_aliases.json`

Maps friendly names and EPICS-style `$(P)$(M)` macros to real PV strings.

```json
{
  "aliases": {
    "zp_z":       "32id:m1",
    "energy_rbv": "32id:TXMOptics:Energy_RBV"
  },
  "macros": {
    "P": "32id:",
    "M": "m1"
  }
}
```

The agent calls `list_pv_aliases` before guessing PV names, and
`resolve_pv("$(P)$(M).RBV")` to expand macros.

### `~/.pystream/doc_urls.json`

Maps friendly names to documentation URLs the agent may fetch on demand.

```json
{
  "links": {
    "areadetector":  "https://areadetector.github.io/areaDetector/",
    "synapps_motor": "https://github.com/epics-modules/motor",
    "txm_wiki":      "https://confluence.aps.anl.gov/display/.../TXM"
  }
}
```

The agent calls `list_url_docs` first to see what's available, then
`fetch_url(url)` to pull a specific page. Pages are HTML-stripped to
plain text and truncated at 30K characters.

### `~/.pystream/status_pages.json`

Maps friendly names to **live** status pages — areaDetector status pages,
IOC procServ web view, motor controller status, vendor health endpoints.
Distinct from `~/.pystream/doc_urls.json` (reference material).

```json
{
  "pages": {
    "ad_camera_status":  "http://camserver.aps.anl.gov:8080/status",
    "mcs_procserv_web":  "http://iocserver:30001",
    "motor_controller":  "http://newport:8080/status.json"
  }
}
```

The agent calls `list_status_pages()` to discover what's available, then
`fetch_url(<url>)` to read the current content. HTML is auto-stripped to
plain text.

### `~/.pystream/ioc_scripts.json`

**This is the security boundary for write actions.** Only IOCs listed
here can be restarted. Empty by default.

```json
{
  "scripts": {
    "ioc-32idb-mcs": {
      "path": "~/scripts/restart_mcs.sh",
      "description": "Restart MCS soft IOC (procServ telnet)"
    },
    "ioc-32idb-cam": {
      "path": "~/scripts/restart_cam.sh",
      "description": "Restart areaDetector camera IOC"
    }
  }
}
```

The script can do anything you want — telnet to procServ, `ssh host sudo
systemctl restart …`, `caput` to a reboot PV. The agent never constructs
a command; it only invokes the path you registered.

When the agent calls `restart_ioc("ioc-32idb-mcs")`:

1. The dispatcher looks up `ioc-32idb-mcs` in the allowlist.
2. **Pystream pops a Yes/No QMessageBox** showing the IOC name and saying
   it will run the registered script.
3. If you click **Yes**, the script runs via
   `subprocess.run([script], shell=False, timeout=30)` and the
   `returncode` + `stdout` + `stderr` come back to the agent.
4. If you click **No**, the call returns `{"error": "user denied the
   action"}` and the agent gets that as a tool result.

Anything not in the allowlist file is rejected unconditionally — the
model cannot run an arbitrary script.

## Where the Agent Gets Information

When the model answers, the information comes from one of three sources,
in priority order:

1. **Tools** (live, called per-question) — PVs, image stats, local docs,
   PV aliases, plugin settings, scan files, URL fetches. **The only
   source of authoritative, current info.** Every tool call shows up in
   the transcript as `⏵ tool_name(args)` followed by `↳ <result>`, so you
   can audit exactly which tool produced any number the agent quotes.
2. **System prompt** (frozen string sent every turn) — the short
   paragraph in the dialog's "System prompt" section, always in context.
3. **Model training data** — general physics, EPICS knowledge,
   programming. Not specific to your beamline.

If the agent answers without a preceding tool call, the answer came from
the system prompt or training data. If you want it to ground answers in
local state, ask a question that requires a tool: *"what's the ZP motor
position right now"*, *"is the detector still streaming"*, *"how many
condensers are configured"*.

## Privacy & Storage

- The Gateway URL, API key, last-used model, and system prompt are
  persisted to `~/.pystream/bl32ID_settings.json` under the `AgentDialog`
  key. That file lives in your home directory — **not** inside any git
  repo, so it cannot be accidentally committed.
- The plugin makes HTTP calls only to the Gateway URL you entered, and
  to URLs returned by `fetch_url`. No telemetry, no third-party endpoints.
- Sensitive fields in plugin settings (`api_key`, `password`, `secret`,
  `token`) are redacted before being shown to the model via
  `get_plugin_settings`.

## Installation

The plugin is part of `pystream`. The two SDKs it depends on are declared
in `pyproject.toml` and installed automatically:

```
pip install .                # picks up anthropic + openai
```

If you `git pull` on a machine that has pystream installed via plain `pip
install` (not `pip install -e .`), reinstall to pick up code changes:

```
pip install .
```

If pystream is installed in **editable mode** (`pip install -e .`), no
reinstall is needed after `git pull` — restart pystream and the new code
is picked up.

## Configuration Reference

| Setting | Where stored | How to change |
|---|---|---|
| Gateway base URL | `~/.pystream/bl32ID_settings.json` | Dialog field |
| Gateway protocol | same | Dropdown |
| API key | same (plain text, user-only file) | Dialog field |
| Selected model | same | Dropdown after Connect |
| System prompt | same | Collapsible field in dialog |
| Reference docs | `~/.pystream/docs/*.md` | Edit files directly |
| PV aliases / macros | `~/.pystream/pv_aliases.json` | Edit JSON |
| Doc URLs (static reference) | `~/.pystream/doc_urls.json` | Edit JSON |
| Status pages (live) | `~/.pystream/status_pages.json` | Edit JSON |
| IOC restart allowlist | `~/.pystream/ioc_scripts.json` | Edit JSON |

## Adding a New Tool

To extend the agent with a new capability, edit
`src/pystream/beamlines/bl32ID/agent_tools.py`:

```python
def tool_my_thing(arg1: str, arg2: int = 0) -> dict:
    """Always return a dict; wrap exceptions yourself."""
    try:
        # ... do work ...
        return {"result": "..."}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}

# At the bottom of the file, add an entry to TOOLS:
{
    "name": "my_thing",
    "description": "Tell the model when to use this tool. Be concrete.",
    "schema": {
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "..."},
            "arg2": {"type": "integer", "description": "..."},
        },
        "required": ["arg1"],
    },
    "func": tool_my_thing,
},
```

Both Anthropic and OpenAI dispatchers pick up new entries automatically;
no other files need changing.

To register a new **write tool** (one that mutates state), add its name
to the `WRITE_TOOLS` set at the top of the same file. The confirmation
dialog message can be customized in `_confirmation_message()` in
`agent.py`.

## Troubleshooting

### "404" or "Not found" on Connect

- Wrong protocol selected — Anthropic gateways serve `/v1/messages`, OpenAI
  gateways serve `/v1/chat/completions`. The two are not interchangeable.
- Wrong base URL prefix — try with and without a trailing `/v1`. The
  placeholder text in the URL field updates with the protocol selection
  to hint the typical shape.
- The error string from the Gateway is shown in the **conn_status** label
  next to the Connect button.

### "openai package missing" / "anthropic package missing"

The SDKs are declared as pystream dependencies but only installed on
`pip install`. If you copied source files manually:

```
pip install anthropic openai
```

### Tool calls not appearing in transcript

If the model answers without any tool calls visible, it didn't use any
tools — the answer came from training data or the system prompt. Either:
- The question doesn't require live state ("explain XANES" doesn't), or
- The model doesn't realize a tool would help — refine the system prompt
  to be more directive about tool usage.

### `restart_ioc` says "not in the allowlist"

The allowlist file is `~/.pystream/ioc_scripts.json`. Either:
- The IOC name doesn't match an entry in `scripts:`, or
- The file doesn't exist yet — it's auto-created empty on first AI
  dialog open; you must add entries manually.

### IOC restart script appears to do nothing

Check the tool result in the transcript — `returncode`, `stdout`, and
`stderr` are all reported. A non-zero `returncode` indicates the script
failed; the agent surfaces this in its reply.

## See Also

- [bl32ID overview](bl32ID.md)
- [QGMax](bl32ID.md#qgmax) — image-mean optimizer used by XANES2D and
  callable directly through the AI agent's `read_pv` tool to inspect its
  status PV
