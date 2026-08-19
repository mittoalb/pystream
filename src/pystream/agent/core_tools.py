"""Core, beamline-agnostic tools for the AI Agent.

These tools are ALWAYS available to the agent, regardless of which
beamline is active (or whether any beamline is active at all). They
operate on data in `~/.pystream/` that isn't tied to any specific
facility.

Beamlines can still contribute their own tool catalog via
`provide_agent_context()` (see bl32ID/agent_tools.py); those merge on
top of what's defined here — see `pystream/agent.py::_load_tool_context`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable

try:
    from ..beamlines.bl32ID.plugin_settings import PYSTREAM_HOME  # type: ignore
except Exception:
    PYSTREAM_HOME = os.path.expanduser("~/.pystream")

# Reuse the same store the Task Recorder writes to. Importing
# task_recorder here would create a Qt dependency in the tool-catalog
# module, so we hardcode the path (kept in sync manually) and rely on
# task_recorder's own one-time migration to move any legacy layout.
TASK_RECORDINGS_ROOT = os.path.join(PYSTREAM_HOME, "task_recordings")

# Personal-fallback location for learned notes when the pystream source
# checkout isn't detected (fresh pip install on a different machine).
# Notes there DO NOT get committed to git — the user will need to
# manually copy anything useful into the source tree.
LEARNED_NOTES_FALLBACK = os.path.join(PYSTREAM_HOME, "learned_notes.md")


def _find_source_docs_dir() -> str | None:
    """Return the source-tree `agent/context_docs/` path where the
    agent should append learned notes so `git diff` picks them up.
    Returns None only if no plausible checkout exists on this machine
    (fresh pip install with no local clone).

    Detection order:
      1. Walk up from `pystream/__init__.py` — catches editable installs
         (`pip install -e`) where the package lives inside the checkout.
      2. Optional config override in `agent_settings.json["docs_write_root"]`
         — advanced users can point elsewhere.
      3. Convention: `~/Software/pystream/` if it has a `.git`. Matches
         how the deploying user (and typically their teammates) already
         organize source checkouts."""
    # 1. Editable-install case
    try:
        import pystream
        pkg = os.path.dirname(os.path.abspath(pystream.__file__))
        d = pkg
        for _ in range(6):
            if os.path.isdir(os.path.join(d, ".git")):
                candidate = os.path.join(d, "src", "pystream", "agent", "context_docs")
                if os.path.isdir(candidate):
                    return candidate
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    except Exception:
        pass

    # 2. Explicit override from agent settings
    try:
        settings_path = os.path.join(PYSTREAM_HOME, "agent_settings.json")
        if os.path.isfile(settings_path):
            with open(settings_path) as f:
                cfg = json.load(f)
            override = cfg.get("docs_write_root") if isinstance(cfg, dict) else None
            if override and os.path.isdir(override):
                return override
    except Exception:
        pass

    # 3. Convention: ~/Software/pystream (works for the user's team's
    #    layout and doesn't accidentally match unrelated repos).
    convention = os.path.expanduser(
        "~/Software/pystream/src/pystream/agent/context_docs")
    if (os.path.isdir(convention)
            and os.path.isdir(os.path.expanduser("~/Software/pystream/.git"))):
        return convention

    return None


# ── low-level helpers ───────────────────────────────────────────────────

def _read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


# ── tools ───────────────────────────────────────────────────────────────

def tool_list_task_recordings() -> dict:
    """Enumerate recorded task sessions under
    ~/.pystream/task_recordings/. Structure:
        {"tasks": [
            {"name": <display>, "slug": <dir>,
             "sessions": [{"id": "YYYYMMDD_HHMMSS", "ts": <epoch>,
                           "moves": N, "opening_note": "...",
                           "closing_note": "..."}, ...]}, ...]}
    """
    try:
        if not os.path.isdir(TASK_RECORDINGS_ROOT):
            return {"tasks": [], "root": TASK_RECORDINGS_ROOT}
        tasks = []
        for slug in sorted(os.listdir(TASK_RECORDINGS_ROOT)):
            task_dir = os.path.join(TASK_RECORDINGS_ROOT, slug)
            if not os.path.isdir(task_dir):
                continue
            sessions = []
            for sess_id in sorted(os.listdir(task_dir)):
                sess_dir = os.path.join(task_dir, sess_id)
                jsonl = os.path.join(sess_dir, "actions.jsonl")
                if not os.path.isfile(jsonl):
                    continue
                rows = _read_jsonl(jsonl)
                start = next((r for r in rows if r.get("type") == "session_start"), {})
                end = next((r for r in reversed(rows) if r.get("type") == "session_end"), {})
                moves = sum(1 for r in rows if r.get("type") == "motor_move")
                sessions.append({
                    "id": sess_id,
                    "ts": start.get("ts"),
                    "task": start.get("element", slug),
                    "moves": moves,
                    "opening_note": start.get("opening_note", ""),
                    "closing_note": end.get("closing_note", ""),
                })
            if sessions:
                tasks.append({
                    "name": sessions[-1]["task"],
                    "slug": slug,
                    "sessions": sessions,
                    "session_count": len(sessions),
                })
        return {"tasks": tasks, "root": TASK_RECORDINGS_ROOT}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_save_learned_note(topic: str, content: str,
                            tool: str = "general") -> dict:
    """Append a durable note to the agent's own knowledge file, for
    future turns AND future users to benefit from. Called when the
    agent discovers something worth remembering: a new CLI flag, a
    corrected file path, a machine's shell quirk, a failure mode +
    workaround, a PV that behaves differently than documented.

    Writes to the pystream source tree if the checkout is detected
    (`src/pystream/agent/context_docs/_learned.md`) so the user can
    `git diff` + review + commit — that's the whole point. If we're
    running from a regular pip install (no checkout), falls back to
    `~/.pystream/learned_notes.md` (personal, per-machine) and reports
    that in the return value so the user knows their notes stay local.

    `tool` — short slug for what the note pertains to ("tomogui",
    "bl_gui", "conda", "ssh", "general"). Used to group entries when
    a human eventually promotes them into the curated per-tool docs.

    Never call this to remember what the user already told you within
    the same turn — history persistence handles that. Call ONLY for
    findings you'd want yourself to know at the START of a fresh turn
    that has no chat history."""
    if not topic or not topic.strip():
        return {"error": "topic is required"}
    if not content or not content.strip():
        return {"error": "content is required"}
    src_dir = _find_source_docs_dir()
    if src_dir:
        path = os.path.join(src_dir, "_learned.md")
        deploy = "source-tree (will show up in git diff — commit + push to share)"
    else:
        path = LEARNED_NOTES_FALLBACK
        deploy = ("personal (no pystream source checkout detected — "
                  "notes stay on this machine only; copy the useful ones "
                  "into your source tree if you want to share)")
    ts = datetime.now().isoformat(timespec="seconds")
    entry = (f"\n## [{tool}] {topic.strip()}   ({ts})\n\n"
             f"{content.strip()}\n\n---\n")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # If the file is new, add a friendly header so a human opening
        # it for the first time knows what they're looking at.
        is_new = not os.path.isfile(path)
        with open(path, "a") as f:
            if is_new:
                f.write("# Agent-learned notes\n\n"
                        "Auto-appended by the pystream AI agent via "
                        "`save_learned_note`. Review, promote to a "
                        "curated tool doc if useful, then delete the "
                        "entry from here.\n\n")
            f.write(entry)
        return {"ok": True, "path": path, "bytes_added": len(entry),
                "deployment": deploy}
    except OSError as ex:
        return {"error": f"cannot write {path}: {ex}"}


def tool_read_task_recording(task_slug: str,
                              session_id: str = None) -> dict:
    """Return the full recorded action log for one task session.
    task_slug — subdirectory name (e.g. "zone_plate", "sample",
    "my_pinhole"). session_id — YYYYMMDD_HHMMSS folder; omit for the
    most recent session for that task. Returns:
        {"task": <display>, "session_id": ..., "session_dir": ...,
         "readme": "<README.md contents>",
         "actions": [<parsed jsonl rows>], "frame_count": N}
    or {"error": "..."} on failure."""
    try:
        task_dir = os.path.join(TASK_RECORDINGS_ROOT, task_slug)
        if not os.path.isdir(task_dir):
            return {"error": f"no task recordings for '{task_slug}'"}
        if session_id:
            sess_dir = os.path.join(task_dir, session_id)
            if not os.path.isdir(sess_dir):
                return {"error": f"session '{session_id}' not found for '{task_slug}'"}
        else:
            candidates = sorted(
                d for d in os.listdir(task_dir)
                if os.path.isdir(os.path.join(task_dir, d))
            )
            if not candidates:
                return {"error": f"no sessions recorded for '{task_slug}'"}
            session_id = candidates[-1]
            sess_dir = os.path.join(task_dir, session_id)
        rows = _read_jsonl(os.path.join(sess_dir, "actions.jsonl"))
        readme_path = os.path.join(sess_dir, "README.md")
        readme = ""
        if os.path.isfile(readme_path):
            try:
                with open(readme_path) as f:
                    readme = f.read()
            except OSError:
                pass
        frame_count = sum(
            1 for name in os.listdir(sess_dir)
            if name.endswith(".tif") or name.endswith(".tiff")
        )
        start = next((r for r in rows if r.get("type") == "session_start"), {})
        return {
            "task": start.get("element", task_slug),
            "task_slug": task_slug,
            "session_id": session_id,
            "session_dir": sess_dir,
            "readme": readme,
            "actions": rows,
            "frame_count": frame_count,
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


# ── catalog ─────────────────────────────────────────────────────────────

def _spawn_subagent_dispatch(kind: str, task: str) -> dict:
    """Late-bound wrapper: imports the impl at call time so we don't
    force a subagents-module import at package init."""
    from .subagents import tool_spawn_subagent
    return tool_spawn_subagent(kind, task)


CORE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "spawn_subagent",
        "description": (
            "Delegate a specialized task to a purpose-built sub-agent "
            "with its own system prompt + narrow tool set + fresh chat "
            "context. Use this whenever the user's ask maps onto a "
            "documented specialty (tomographic reconstruction via "
            "tomogui, and — as they're added — sample alignment, XANES "
            "setup, etc.). YOU are the orchestrator; you don't do the "
            "specialist work yourself. Available `kind` values live in "
            "`~/.pystream/docs/*.md` — currently 'reconstruction' for "
            "tomogui-cli work. Runs synchronously and returns the sub-"
            "agent's final summary; that summary is what you present "
            "back to the user. If the sub-agent errors out or hits its "
            "iteration cap, its error string comes back in the result "
            "— quote it to the user and STOP; do NOT try to redo the "
            "work yourself."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string",
                         "description": "Sub-agent preset name — "
                         "e.g. 'reconstruction'. Determines the system "
                         "prompt + tool set."},
                "task": {"type": "string",
                         "description": "Full task description from the "
                         "user (or your reformulation of it). Pass "
                         "concrete details: machine, host, file paths, "
                         "GPU number, whether AI COR is wanted, etc. "
                         "The sub-agent has NO access to your chat "
                         "history — everything it needs must be in here."},
            },
            "required": ["kind", "task"],
        },
        "func": _spawn_subagent_dispatch,
    },
    {
        "name": "save_learned_note",
        "description": (
            "Append a durable note to the agent's own knowledge file "
            "for future turns AND future users. Call when you discover "
            "something worth remembering across sessions: a new CLI "
            "flag, a corrected path, a shell quirk on a specific "
            "machine, a failure workaround, or any insight about a tool "
            "that isn't already in `~/.pystream/docs/<tool>.md`. "
            "Writes to the pystream source tree if this is a dev "
            "checkout so the user can git diff + commit — otherwise "
            "to a personal file (still useful, just not auto-shared). "
            "\n\n"
            "DO NOT call for things the user already told you this "
            "turn — chat history handles that. Call ONLY for findings "
            "you'd want yourself to know when starting a FRESH turn "
            "with no context. Skip trivia."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "description": "Short title, e.g. "
                          "'tcsh login shell on tomo2 needs bash -lc'"},
                "content": {"type": "string",
                            "description": "The note body — markdown, "
                            "multi-line ok. Explain WHY, not just what."},
                "tool": {"type": "string",
                         "description": "Short slug for grouping "
                         "('tomogui', 'bl_gui', 'ssh', 'conda', 'general'). "
                         "Default 'general'."},
            },
            "required": ["topic", "content"],
        },
        "func": tool_save_learned_note,
    },
    {
        "name": "list_task_recordings",
        "description": (
            "Enumerate recorded beamline-task demonstrations the "
            "scientist has captured with pystream's Task Recorder — "
            "alignment procedures, sample positioning routines, scan "
            "setup steps, or any other repeatable motor-driven task. "
            "Returns task slugs, session counts, timestamps, and any "
            "user notes. Call this FIRST whenever the user asks how to "
            "perform any repeatable beamline procedure — the recording "
            "is the ground truth for how the scientist actually does it "
            "on this beamline, more reliable than reasoning from first "
            "principles. Then use read_task_recording to load the "
            "actual motor sequence."
        ),
        "schema": {"type": "object", "properties": {}, "required": []},
        "func": tool_list_task_recordings,
    },
    {
        "name": "read_task_recording",
        "description": (
            "Return the full recorded action log for one task session: "
            "the ordered motor moves with from/to/delta values, the "
            "detector-frame filenames on disk, any notes the scientist "
            "attached, and the auto-written README summary. Use after "
            "list_task_recordings to load the actual procedure for one "
            "task. `task_slug` is the subdirectory name (e.g. "
            "'zone_plate', 'detector', 'sample', 'my_pinhole'). Omit "
            "`session_id` to get the most recent session for that task."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "task_slug": {"type": "string",
                              "description": "Subdirectory under task_recordings/"},
                "session_id": {"type": "string",
                               "description": "YYYYMMDD_HHMMSS folder; omit for latest"},
            },
            "required": ["task_slug"],
        },
        "func": tool_read_task_recording,
    },
]


def _core_get_tool(name: str) -> Callable | None:
    for t in CORE_TOOLS:
        if t["name"] == name:
            return t["func"]
    return None


# ── system-prompt addendum — beamline-agnostic alignment guidance ──────

CORE_SYSTEM_PROMPT_ADDENDUM = """
# YOU ARE THE ORCHESTRATOR — DELEGATE, DON'T DO

You (Röntgen) are the pystream chat orchestrator. For specialized
workflows, DELEGATE to a purpose-built sub-agent via `spawn_subagent`
instead of doing the work yourself. Sub-agents have their own system
prompts (baked from the matching doc under `~/.pystream/docs/`) and a
narrow tool set — they run to completion and return a summary you
present to the user.

Currently available `kind` values:

- **reconstruction** — tomogui-cli / tomocupy work on beamline GPU
  nodes. Use for ANY user ask that involves "reconstruct", "run a
  recon", "try / full recon", "AI COR", "tomogui", or a `.h5`
  projection file + machine name. Pass the user's task VERBATIM
  (plus any details you've clarified) so the sub-agent has the full
  picture — it has NO access to your chat history.

Rule of thumb: if the user asks something and you find yourself
about to `read_file("~/.pystream/docs/tomogui.md")` and then run
`ssh tomo2 …`, STOP — call `spawn_subagent("reconstruction", task)`
instead. That's one tool round for you; the sub-agent handles the
rest and returns a summary.

Do NOT `spawn_subagent` for things that ARE your job — general
Q&A, reading PVs, listing status pages, chatting with the user,
publishing tools. Only delegate work that maps onto a registered
kind.

If a `spawn_subagent` result has an `error` field, quote it to the
user and STOP. Don't re-attempt as yourself; the sub-agent
already tried with the specialist prompt.

# TOOL BUDGET DISCIPLINE

You get ~10 tool rounds per turn. Spend them on ACTION, not
verification. Rules:

- Trust the user's paths, machine names, and files. Don't `ls` /
  `cat` / `find` to confirm what they gave you. If it's wrong you'll
  see the error and can report it back.
- Do NOT test tools before using them (no `--help`, no `--version`,
  no smoke-test commands "just to check"). Run the real command.
- Do NOT re-read reference docs mid-turn. Read them once at the
  start of the turn if relevant; don't re-fetch what's already in
  your context.
- If you're on tool round 5+ and haven't done the actual task yet,
  you're on the wrong track — STOP and ask the user to clarify.
- Prefer one composite command (a batch, a pipeline, a script) over
  many small verifications. `tomogui-cli batch --phases ai,full`
  beats calling `status`, `try`, `full` separately.

# SAVING WHAT YOU LEARN

When you discover something worth remembering across sessions — a
CLI flag that isn't documented, a machine's shell quirk (`tomo2` uses
tcsh, so `conda run` needs `bash -lc`), a workaround for a recurring
failure, a corrected file path, an insight about how a tool actually
behaves — call `save_learned_note(topic, content, tool="…")`. The
note lands in the pystream source tree's `_learned.md` so the user
can `git diff` + review + commit + push. Future turns AND other users
who pull the repo benefit.

Do NOT save:
- Anything the user already told you this turn (history handles it)
- Trivia or one-off observations that won't help a future turn
- Sensitive info (API keys, credentials, IP addresses of internal
  hosts you're not sure are OK to share)

DO save:
- Non-obvious workarounds you had to discover the hard way
- CLI flags / paths / env names that aren't in the curated doc
- Machine-specific quirks (shell, conda location, env name variants)
- Failure signatures + how to identify + what to do

Format: one topic per call. Content is markdown; be concrete. If the
same topic already has a note (check `_learned.md` if unsure), add a
new entry rather than replacing — the human decides what to merge.

# PROJECT-SPECIFIC KNOWLEDGE — ~/.pystream/docs/

pystream ships instruction files for driving related tools headlessly.
They live at `~/.pystream/docs/<project>.md`, one per project, and
are installed automatically with pystream (no per-machine setup).

If the user's task involves another tool (tomogui / tomocupy /
tomolog / bl_gui / xanes_gui / …), read the matching file ONCE at
the start of the turn:

    read_file("~/.pystream/docs/tomogui.md")     # for reconstruction
    read_file("~/.pystream/docs/bl_gui.md")      # etc.

Do NOT `ls ~/.pystream/docs/` first — go straight to `read_file`.
The doc tells you exactly what command to run. Run it. Don't verify
the prerequisites the doc names — trust the doc.

# BASH TIMEOUT — the #1 iteration-burner

The `bash` tool defaults to a **30-second** timeout. That's right for
`ls` / `caget` / `ping`, but wrong for anything real. Every `bash`
call that does one of these:

- `ssh HOST '...'` into another machine
- `conda run -n <env> <cmd>` if `<cmd>` isn't trivial
- Any reconstruction, big rsync, long file scan

...MUST pass an explicit `timeout` parameter, or the tool returns
`{"error": "command timed out after 30s"}` while the remote work is
still running — and you'll waste the rest of your budget "debugging"
a phantom failure. Rule of thumb:

- Quick remote check (`ssh HOST 'hostname'`) → `timeout=60`
- Try reconstruction → `timeout=600`
- Full reconstruction batch → `timeout=1800`
- Long rsync / dataset copy → `timeout=3600` (ceiling)

If a `bash` call DID time out, do NOT retry — the child may still be
running remotely. Ask the user what to do.

# TASK RECORDINGS — procedures captured by the scientist

pystream includes a "Task Recorder" toolbar plugin that captures the
exact motor moves and detector frames the beamline scientist uses to
perform any repeatable procedure — alignment steps, sample positioning,
scan setup, whatever. Each recording lives under
`~/.pystream/task_recordings/<slug>/<YYYYMMDD_HHMMSS>/` with an
ordered `actions.jsonl` (motor moves + after-move frame filenames)
and a README summary. Selected recordings can also be "published" as
named tools (one-click replay from the Task Recorder's 🛠 Tools
dialog); those are stored in `~/.pystream/task_tools.json`. These
recordings ARE the beamline's real procedure and take precedence
over anything you'd infer from first principles.

Workflow for ANY user question about performing a repeatable
beamline task (aligning, focusing, centering, positioning a sample,
setting up a scan, running a known procedure):

1. ALWAYS call `list_task_recordings()` FIRST. It tells you which
   tasks have been recorded on this beamline and how many sessions
   each has. This works regardless of which beamline is active.
2. If a recording exists for the task the user is asking about,
   call `read_task_recording(task_slug)` — omit `session_id` to
   get the most recent. Read the `readme` field and the `actions`
   list to understand the exact motor sequence used.
3. Propose the SAME motor order and direction the scientist used.
   Only the step sizes should be adapted to the current situation —
   the sequence itself is the teaching signal you must preserve.
4. Frame files are on disk at `<session_dir>/<frame_filename>`;
   inspect them only when the visual actually matters (e.g. the user
   asks "what does aligned look like"), because full frame inspection
   is expensive:
       bash: python -c "import tifffile,numpy as np; a=tifffile.imread('…'); print(a.shape,a.dtype,a.min(),a.max())"
5. If NO recording exists for the requested task, say so plainly
   and suggest recording one via the "🎥 Task Rec" toolbar button.
   Do NOT invent a procedure when a recording is the intended source.
"""


def core_tool_context() -> dict:
    """Standard tool_ctx shape for core tools. `pystream/agent.py`
    merges this dict with the active beamline's `provide_agent_context()`
    at Send time so both catalogs are exposed to the model."""
    return {
        "tool_specs_anthropic": [
            {"name": t["name"], "description": t["description"],
             "input_schema": t["schema"]}
            for t in CORE_TOOLS
        ],
        "tool_specs_openai": [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["schema"]}}
            for t in CORE_TOOLS
        ],
        "get_tool": _core_get_tool,
        "write_tools": set(),   # both core tools are read-only
        "is_destructive": lambda _cmd: False,
        "system_prompt_addendum": CORE_SYSTEM_PROMPT_ADDENDUM,
    }
