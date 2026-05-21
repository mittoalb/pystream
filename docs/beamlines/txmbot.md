# TXMBot — AI Agent

LLM chat assistant embedded in PyStream that can read live beamline state
through a tool catalog and, with an explicit Yes/No confirmation, run
allowlisted IOC-restart scripts. Appears as **AI** in the bl32ID toolbar.

The agent speaks to a Gateway using either the Anthropic Messages API or
the OpenAI Chat Completions protocol. The user picks protocol, fills in
the Gateway URL and API key, clicks **Connect / refresh models**, picks a
model, then chats.

## What the agent can do

- Read EPICS PVs, motors, and detector image stats.
- Diagnose stuck PVs, motors, or frozen detector streams.
- Read markdown notes, PV aliases, and per-plugin settings from
  `~/.pystream/`.
- Fetch registered web docs and live status pages.
- List recent XANES2D HDF5 master files and read their metadata.
- Restart an IOC by running a user-registered script — **gated by a
  Yes/No dialog** that the model cannot bypass.

Every tool call shows up in the transcript so you can audit what produced
any number the agent quotes.

## User-editable files

All under `~/.pystream/` (auto-created on first launch, never
overwritten):

| File | Purpose |
|---|---|
| `docs/*.md` | Reference notes the agent can read/search |
| `pv_aliases.json` | Friendly PV names + `$(P)$(M)` macros |
| `doc_urls.json` | Static reference URLs |
| `status_pages.json` | Live status page URLs |
| `ioc_scripts.json` | IOC restart allowlist — empty by default |
| `bl32ID_settings.json` | Gateway URL, API key, model, system prompt |

The **security boundary for write actions** is `ioc_scripts.json`. Only
IOCs listed there can be restarted, and each restart still pops a
confirmation dialog.

## Adding a new tool

Edit [src/pystream/beamlines/bl32ID/agent_tools.py](../../src/pystream/beamlines/bl32ID/agent_tools.py):

1. Write a function `tool_my_thing(...) -> dict` that returns a dict
   (and catches its own exceptions, returning `{"error": ...}`).
2. Append an entry to the `TOOLS` list at the bottom with `name`,
   `description`, JSON `schema`, and `func`.
3. If the tool mutates state, also add its name to `WRITE_TOOLS` so it
   goes through the confirmation gate.

Both protocol dispatchers pick up new entries automatically.
