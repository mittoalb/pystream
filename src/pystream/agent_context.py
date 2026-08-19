"""Core agent-context bootstrap.

Ensures the AI agent (Röntgen and any spawned sub-agent) can find
project-specific "how do I drive this?" documentation by symlinking
every `AGENTS.md` file under `~/Software/*` into `~/.pystream/docs/`
where the existing `read_file` / `read_doc` / `bash: cat` tools can
find them.

This lives at pystream core level so the docs are available on any
beamline (or with no beamline). bl32ID's `bootstrap_knowledge_base`
still runs alongside — it seeds bl32ID-specific starter files
(`pv_aliases.json`, `ioc_scripts.json`, …) but no longer owns the
AGENTS.md symlinking that used to be inside its
`_link_known_reference_docs`. Both bootstraps are idempotent and
safe to call together at every startup.
"""

from __future__ import annotations

import glob
import logging
import os

try:
    from .beamlines.bl32ID.plugin_settings import PYSTREAM_HOME  # type: ignore
except Exception:
    PYSTREAM_HOME = os.path.expanduser("~/.pystream")

DOCS_DIR       = os.path.join(PYSTREAM_HOME, "docs")
SOFTWARE_ROOT  = os.path.expanduser("~/Software")
# README.md is broad — kept for backward compat with bl32ID's older
# convention. AGENTS.md is the canonical "instruction file for AI
# agents" convention; if both exist we prefer AGENTS.md.
CANDIDATE_FILENAMES = ("AGENTS.md", "README.md")

LOGGER = logging.getLogger(__name__)


def bootstrap_agent_context_docs() -> None:
    """Symlink every project's AGENTS.md (falling back to README.md) from
    `~/Software/<project>/` into `~/.pystream/docs/<project>_<tag>.md`.
    Idempotent; safe to call on every startup. Silently no-ops if
    `~/Software/` isn't present.
    """
    try:
        os.makedirs(DOCS_DIR, exist_ok=True)
    except OSError as e:
        LOGGER.debug("cannot create %s: %s", DOCS_DIR, e)
        return

    if not os.path.isdir(SOFTWARE_ROOT):
        return

    for project_dir in sorted(glob.glob(os.path.join(SOFTWARE_ROOT, "*"))):
        if not os.path.isdir(project_dir):
            continue
        project_name = os.path.basename(project_dir)
        for filename in CANDIDATE_FILENAMES:
            src_abs = os.path.join(project_dir, filename)
            if not os.path.isfile(src_abs):
                continue
            tag = filename.rsplit(".", 1)[0]
            dst = os.path.join(DOCS_DIR, f"{project_name}_{tag}.md")
            try:
                # Already the exact symlink we want → done.
                if os.path.islink(dst) and os.readlink(dst) == src_abs:
                    break
                # Some other file/link with the same name — don't clobber.
                if os.path.lexists(dst):
                    break
                os.symlink(src_abs, dst)
            except OSError as e:
                LOGGER.debug("failed to symlink %s → %s: %s",
                             src_abs, dst, e)
            break   # prefer AGENTS.md over README.md
