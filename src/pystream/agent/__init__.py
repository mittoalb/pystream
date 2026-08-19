"""pystream AI-agent subpackage.

Groups all agent-related code under one directory so the top-level
`src/pystream/` tree stays uncluttered:

    agent/
        chat.py         — AgentChatWidget + _ChatWorker (AI panel + turns)
        console.py      — AgentConsoleDialog (live wire trace)
        context.py      — bootstrap that copies packaged docs to
                          ~/.pystream/docs/ on first launch
        context_docs/   — instruction .md files that SHIP with the
                          package (tomogui.md today; more as tools grow)
        core_tools.py   — agent tools that are ALWAYS in the catalog,
                          regardless of active beamline
        panel.py        — AgentsDialog (live "who's running" window)
        status.py       — AgentStatusPublisher + shared registry
                          (~/.aps_agents/agents.json)

Public API re-exports below so external callers keep using the short
form `from pystream.agent import <thing>` — the internal reorg is
invisible to them."""

# --- chat / AI panel ---
from .chat import (
    AgentChatWidget,
    AgentDialog,
    DEFAULT_AGENT_NAME,
    MAX_AGENT_ITERATIONS,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_OPENAI,
    PYSTREAM_HOME,
    SYSTEM_PROMPT_DEFAULT,
    build_agent_panel,
    load_settings,
    save_settings,
)

# --- console (live wire trace) ---
from .console import AgentConsoleDialog

# --- docs bootstrap ---
from .context import bootstrap_agent_context_docs

# --- core tools + prompt addendum ---
from .core_tools import (
    CORE_SYSTEM_PROMPT_ADDENDUM,
    CORE_TOOLS,
    core_tool_context,
)

# --- agents panel (dialog + factory) ---
from .panel import AgentsDialog, AgentsPanel, build_agents_panel

# --- shared status registry ---
from .status import (
    AGENTS_FILE,
    APS_AGENTS_DIR,
    AgentStatusPublisher,
    child_env,
    load_registry,
    purge_stale_records,
    update_record,
)

__all__ = [
    "AGENTS_FILE",
    "APS_AGENTS_DIR",
    "AgentChatWidget",
    "AgentConsoleDialog",
    "AgentDialog",
    "AgentStatusPublisher",
    "AgentsDialog",
    "AgentsPanel",
    "CORE_SYSTEM_PROMPT_ADDENDUM",
    "CORE_TOOLS",
    "DEFAULT_AGENT_NAME",
    "MAX_AGENT_ITERATIONS",
    "PROTOCOL_ANTHROPIC",
    "PROTOCOL_OPENAI",
    "PYSTREAM_HOME",
    "SYSTEM_PROMPT_DEFAULT",
    "bootstrap_agent_context_docs",
    "build_agent_panel",
    "build_agents_panel",
    "child_env",
    "core_tool_context",
    "load_registry",
    "load_settings",
    "purge_stale_records",
    "save_settings",
    "update_record",
]
