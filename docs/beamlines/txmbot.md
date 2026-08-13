# Röntgen — AI Agent

LLM chat assistant embedded in PyStream that can read live beamline state
through a tool catalog and, with an explicit Yes/No confirmation, run
allowlisted IOC-restart scripts.

## Where it lives

**Always visible** as a bottom panel in pystream's central splitter —
regardless of which beamline (or no beamline) is active. Drag the
splitter handle above it to change its height. Hide/show from the View
menu; state persists across restarts.

This is a change from earlier versions where the agent was a bl32ID-only
toolbar button. It is now a **core pystream feature**; beamlines
contribute tools and prompt-body content, but the widget itself,
protocol handling, history, and settings all live in
[src/pystream/agent.py](../../src/pystream/agent.py).

## Configuration

Click **⚙ Settings** on the panel to open the config dialog:

- **Protocol** — Anthropic Messages API or OpenAI Chat Completions.
- **Base URL** + **API key** — your Gateway credentials. Stored locally
  only, never committed to the repo.
- **Model** — click *Connect / refresh models* after entering URL + key
  to populate the dropdown.
- **Agent name** — free-form; default `Röntgen`. Substituted into the
  system prompt as `{name}` so the agent introduces itself with your
  chosen alias.
- **System prompt** — full editable prompt. Uses placeholders:
  - `{name}` — the configured agent name
  - `{beamline}` — value of `ACTIVE_BEAMLINE` from
    [beamline_config.py](../../src/pystream/beamline_config.py); falls
    back to `"this beamline"` when `None`
  - `{beamline_addendum}` — the active beamline's contribution (see
    below); empty when no beamline is active or the beamline doesn't
    provide one
- **Show tool calls** — verbose transcript vs. compact.

## Beamline-specific tools and prompt

The agent's tools and beamline-specific prompt body are contributed by
the active beamline through the `provide_agent_context()` hook in that
beamline's `__init__.py`. The hook returns a dict of:

| Key | What it does |
|---|---|
| `tool_specs_anthropic` | Anthropic-format tool schemas |
| `tool_specs_openai` | OpenAI-format tool schemas |
| `get_tool` | Callable `name → implementation function` |
| `write_tools` | Set of tool names that need Yes/No confirmation |
| `is_destructive` | Function that classifies a bash command as risky |
| `system_prompt_addendum` | Text spliced into the prompt at `{beamline_addendum}` |

Beamline with no hook (or hook returning `{}`) → pure chat, no tools, no
addendum. That's the bl19BM state today.

## What bl32ID contributes

When `ACTIVE_BEAMLINE = 'bl32ID'`, the agent gets:

- Read EPICS PVs, motors, and detector image stats.
- Diagnose stuck PVs, motors, or frozen detector streams.
- Read markdown notes, PV aliases, and per-plugin settings from
  `~/.pystream/`.
- Fetch registered web docs and live status pages (including the 32-ID
  IOC control panel at `http://164.54.102.6:5100/`).
- List recent XANES2D HDF5 master files and read their metadata.
- Restart an IOC by running a user-registered script — **gated by a
  Yes/No dialog** that the model cannot bypass.

Every tool call shows up in the transcript so you can audit what
produced any number the agent quotes. Contributions live in
[src/pystream/beamlines/bl32ID/agent_tools.py](../../src/pystream/beamlines/bl32ID/agent_tools.py).

## User-editable files

All under `~/.pystream/` (auto-created on first launch, never
overwritten):

| File | Purpose |
|---|---|
| `agent_settings.json` | Protocol, Gateway URL, API key, model, agent name, system prompt |
| `agent_history_dock.json` | Full conversation history — restored on next launch |
| `docs/*.md` | Reference notes the agent can read/search |
| `pv_aliases.json` | Friendly PV names + `$(P)$(M)` macros |
| `doc_urls.json` | Static reference URLs |
| `status_pages.json` | Live status page URLs |
| `ioc_scripts.json` | IOC restart allowlist — empty by default |

Settings were previously stored under an `AgentDialog` key inside
`~/.pystream/bl32ID_settings.json`. On first run after the refactor,
`load_settings()` transparently migrates that block to
`agent_settings.json`; no user action needed.

The **security boundary for write actions** is `ioc_scripts.json`. Only
IOCs listed there can be restarted, and each restart still pops a
confirmation dialog.

**Credentials**: API keys live only in `~/.pystream/agent_settings.json`
(outside the git repo). `.gitignore` blocks `*_settings.json`,
`api_key*`, `credentials*`, `*.pem`, `*.key`, `ai_backends.json`, and
`secrets/`.

## Adding a new tool

Two axes: **per-beamline** (new tools for an existing beamline) or
**enable tools on a beamline that has none**.

### Add a tool to bl32ID

Edit [src/pystream/beamlines/bl32ID/agent_tools.py](../../src/pystream/beamlines/bl32ID/agent_tools.py):

1. Write a function `tool_my_thing(...) -> dict` that returns a dict
   (and catches its own exceptions, returning `{"error": ...}`).
2. Append an entry to the `TOOLS` list at the bottom with `name`,
   `description`, JSON `schema`, and `func`.
3. If the tool mutates state, also add its name to `WRITE_TOOLS` so it
   goes through the confirmation gate.

The core agent picks up new entries automatically on the next Send —
`provide_agent_context()` is queried per turn.

### Enable tools on another beamline

In that beamline's `__init__.py`, add a `provide_agent_context()`
function returning the six-key dict shown above. Any missing key
defaults to a safe value (no tools / no addendum). See bl32ID's
`__init__.py` for the reference implementation.
