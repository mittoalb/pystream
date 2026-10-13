# beamline-agent

The AI layer. Chat dock + tool-use loop + sub-agent dispatch + status
monitor + image/HDF5 viewers. Hosted in-process by pystream; pluggable
into any Qt host via the `HostContext` protocol.

## Purpose in one sentence

Give the beamline scientist a chat panel that can read the current
frame, call tools (motor moves, PV writes, scan launches), spawn
specialist sub-agents (reconstruction, chemist, operator), and
remember what it learned — all without leaving pystream.

## Where it fits

```{mermaid}
flowchart LR
    USER[scientist]
    PS[pystream<br/>PvViewerApp]
    BA[beamline-agent dock]
    LLM[Anthropic / OpenAI API]
    TOOLS[bl32ID/agent_tools.py<br/>anthropic_tool_specs / openai_tool_specs]
    PROC[beamlines-procedures<br/>~/.pystream/procedures/*.md]
    SUB[sub-agents<br/>reconstruction / physicist / chemist / operator]
    IOCS[EPICS IOCs]

    USER -- chat --> BA
    PS -- HostContext --> BA
    BA -- messages --> LLM
    LLM -- tool_use --> BA
    BA -- calls --> TOOLS
    TOOLS --> IOCS
    BA -. reads at startup .-> PROC
    BA -. spawn_subagent .-> SUB
    SUB --> LLM
```

The chat panel lives inside pystream's process. Tools live in a
per-beamline `agent_tools.py`. Procedures ship as a separate package.

## Architecture

```{mermaid}
flowchart TB
    subgraph InProcess ["pystream process"]
        subgraph Chat ["Chat panel"]
            UI[QTextEdit + input + send]
            MSG[(message history)]
            RUN[run loop<br/>per-turn LLM round-trip]
        end

        subgraph ToolLoop ["Tool-use loop"]
            TRY[LLM: assistant message with tool_use]
            EXEC[execute tool call(s) in parallel]
            RES[tool_result back to LLM]
            NXT[next LLM turn]
        end

        subgraph HostAPI ["HostContext (from pystream)"]
            LF[live_frame()]
            FS[frame_signal (image_ready)]
            OB[open_hdf5_viewer / open_plugin]
            LP[list_plugins / is_destructive]
        end

        subgraph ConsolePanel ["Console"]
            WIRE[tool-call wire trace<br/>in-flight timer]
        end

        subgraph AgentsPanel ["Agents panel"]
            TREE[live tree of agent processes]
        end

        subgraph ImgView ["Image / HDF5 viewers"]
            PV[agent-only PNG/TIFF/NPY viewer]
            HV[HDF5 browser]
        end
    end

    subgraph External ["External"]
        LLMAPI[Anthropic or OpenAI]
        SUBP[sub-agent subprocess]
    end

    UI --> RUN
    RUN --> TRY
    TRY --> EXEC
    EXEC --> HostAPI
    EXEC --> WIRE
    EXEC -- spawn --> SUBP
    SUBP --> TREE
    EXEC --> RES
    RES --> NXT
    NXT --> TRY
    TRY <--> LLMAPI
```

* **Chat panel**: Qt widget mounted by `_agent_mount(host)` into
  pystream's bottom-splitter dock.
* **Tool-use loop**: per turn — build the request, call the LLM,
  if the response contains `tool_use` blocks execute them in parallel
  (each in its own thread), feed back the results, continue until
  the LLM returns a pure assistant message.
* **HostContext**: a protocol pystream fills in — the agent reaches
  for `host.live_frame()` instead of knowing anything about pyqtgraph
  or `self.image_view`. The agent would also mount cleanly into any
  non-pystream Qt host that implements the same protocol.
* **Sub-agents**: `spawn_subagent(kind, task)` launches a specialist
  in its own subprocess (reconstruction / physicist / chemist /
  beamline_operator). The main agent coordinates; the sub-agent
  does one thing well and returns.
* **Console** streams every tool call + result + in-flight timer so
  the scientist can audit what the agent did.
* **Agents panel** shows a live tree of all agent processes running
  on the beamline (main + spawned sub-agents + cross-machine workers).

## Data flow — one chat turn

```{mermaid}
sequenceDiagram
    participant User
    participant UI as Chat UI
    participant Agent as Agent loop
    participant Host as HostContext
    participant LLM as Anthropic / OpenAI
    participant Tool as agent_tools.py
    participant IOC as EPICS IOC

    User->>UI: types + Enter
    UI->>Agent: enqueue user message
    Agent->>LLM: messages + tool_specs
    LLM-->>Agent: assistant + tool_use blocks
    par per tool
        Agent->>Tool: execute(kwargs)
        Tool->>Host: live_frame() / open_hdf5_viewer()
        Tool->>IOC: caget / caput / move_motor
        IOC-->>Tool: result
        Tool-->>Agent: tool_result
    end
    Agent->>LLM: tool_results
    LLM-->>Agent: next assistant message
    Agent->>UI: append to chat
    UI->>User: visible reply
```

## Tool definitions — the inline pattern

Tools are not MCP. They are plain Python functions registered in
`pystream/beamlines/<bl>/agent_tools.py`:

```python
# anthropic_tool_specs() returns a list of {name, description, input_schema}
# dicts for the Anthropic Messages API. openai_tool_specs() does the
# equivalent for OpenAI's function-calling schema. get_tool(name)
# resolves a tool name to the Python callable the agent invokes.
```

The agent calls these Python functions **directly in-process**. Why
not MCP?

| In-process (today)                                       | MCP server                                  |
|----------------------------------------------------------|---------------------------------------------|
| Microsecond call latency                                 | Tens of ms (stdio) per call                 |
| Shares pystream state: `self.image_view`, bus, widgets   | Needs a bridge for every host-side touch    |
| One Python process to deploy                             | Second process to launch and keep alive     |
| Tools lock-in to the beamline-agent runtime              | Reusable by Claude Code / Desktop / others  |
| Simple to write and debug                                | Standardised schema; versionable discovery  |

The current design optimises for the in-process case because that is
the only consumer today. If a second client ever needs the same
tools, an MCP wrapper is a 1-day job that exposes a subset — stateless
tools (motor move, caget, caput, run_tomoscan) over MCP, leaving the
state-dependent tools (live_frame, open_plugin) in-process only.

## Sub-agent dispatch

```python
spawn_subagent("reconstruction", task="reconstruct scan 42, slice 300")
```

Spawns `beamline_agent.subagents.<kind>` in a child process with its
own LLM session and its own tools. Progress + logs stream back to the
Agents panel. The main agent chooses the sub-agent kind based on the
task (`reconstruction`, `physicist`, `chemist`, `beamline_operator`
today).

## Instruction docs

A tree of `context_docs/*.md` ships inside the package and is
auto-deployed to `~/.pystream/docs/` on first launch. These are the
agent's own operating instructions — tone, tool preferences, safety
rules, "never caput without reading first". Edit the deployed copy
to tune the agent's behaviour on a running system; the package copy
is the baseline that'll replace the deployed one if the user wipes
`~/.pystream/`.

The scientist's **domain** knowledge (motor conventions, procedures,
sample recipes) lives in {doc}`beamlines-procedures`, not here.

## Learned-note store

`save_learned_note(topic, note)` writes a markdown fragment back into
the `beamline-agent` git checkout. Pushing the repo (`git push`)
propagates the note so every machine that pulls picks it up. Pattern
is deliberate: the human can review and curate the `.ai.md` twin
before merging it into their canonical `.md`.

## Public API / extension points

* **Add a tool**: write the function in `agent_tools.py`, declare it
  in `anthropic_tool_specs()` and `openai_tool_specs()`, make
  `get_tool` resolve its name.
* **Add a sub-agent kind**: new module under
  `beamline_agent/subagents/<kind>.py`; wire it into the dispatcher.
* **Add a status panel**: expose a `QWidget` and mount it alongside
  the chat via the beamline's `provide_bottom_panels(parent)`.
* **Switch provider**: `~/.pystream/ai_backends.json` picks Anthropic
  vs OpenAI vs local; same tool specs round-trip either way.

## Dependencies

* `anthropic` and/or `openai` Python SDK (depending on configured
  backend).
* `PyQt5` — the chat panel is a Qt widget.
* `beamlines-procedures` — optional; absent → no procedures section
  in the system prompt, agent still runs.
* `pystream` — optional at the package level; the agent only needs a
  valid `HostContext`, but today only pystream provides one.

## Known gotchas

* **The agent sees whatever pystream's live frame contains**. That
  is post-decimation, post-flip, post-flat-field. Agent tools that
  need raw sensor pixels have to undo pystream's view ops (see the
  pystream page).
* **Tool calls fire on a worker thread** (so the GUI stays
  responsive) but touching Qt widgets must happen on the main
  thread. HostContext helpers that create widgets dispatch back
  through `QMetaObject.invokeMethod`.
* **Keep tool side-effects local** when possible — the console
  logs each tool call verbatim, so a tool that touches the file
  system shows up as a line the scientist can audit.
* **Destructive tools** (anything that moves hardware) are
  classified in `WRITE_TOOLS` and funneled through
  `_bash_is_destructive`. Don't skip the classification; the agent
  double-checks before firing.

## Future / open questions

* MCP wrapper for a stateless tool subset — only if a second
  client actually wants it.
* Shared memory for frame hand-off to sub-agents (recon in
  particular — currently round-trips a numpy array via pickle).
* Persistent per-sample context store (what the sample is, what we
  did last session) — currently only free-form learned notes.
