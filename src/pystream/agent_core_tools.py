"""Core, beamline-agnostic tools for the AI Agent.

These tools are ALWAYS available to the agent, regardless of which
beamline is active (or whether any beamline is active at all). They
operate on data in `~/.pystream/` that isn't tied to any specific
facility — currently just the task-recordings store fed by
pystream's Task Recorder.

Beamlines can still contribute their own tool catalog via
`provide_agent_context()` (see bl32ID/agent_tools.py); those merge on
top of what's defined here — see `pystream/agent.py::_load_tool_context`.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

try:
    from .beamlines.bl32ID.plugin_settings import PYSTREAM_HOME  # type: ignore
except Exception:
    PYSTREAM_HOME = os.path.expanduser("~/.pystream")

# Reuse the same store the Task Recorder writes to. Importing
# task_recorder here would create a Qt dependency in the tool-catalog
# module, so we hardcode the path (kept in sync manually) and rely on
# task_recorder's own one-time migration to move any legacy layout.
TASK_RECORDINGS_ROOT = os.path.join(PYSTREAM_HOME, "task_recordings")


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

CORE_TOOLS: list[dict[str, Any]] = [
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
