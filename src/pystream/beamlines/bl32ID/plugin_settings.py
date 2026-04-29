"""
Shared settings persistence for bl32ID plugins.

Stores all plugin settings in a single JSON file under ``~/.pystream/``.
Each plugin gets its own section keyed by class name.

Also exposes ``PYSTREAM_HOME`` — the canonical directory under the user's
home for *every* pystream user-config file (settings, agent knowledge
base, IOC allowlist, QGMax handshake, etc.). Other modules build their
paths from this constant.

Importing this module triggers a one-time migration of legacy
``~/.pystream_*`` files into ``~/.pystream/``. The migration is
idempotent and silently skips if already done.
"""

import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

PYSTREAM_HOME = os.path.expanduser("~/.pystream")
SETTINGS_FILE = os.path.join(PYSTREAM_HOME, "bl32ID_settings.json")

_logger = logging.getLogger(__name__)


# ── one-time legacy migration ──────────────────────────────────────────

_LEGACY_FILES = {
    # old path → new path inside PYSTREAM_HOME
    "~/.pystream_bl32ID_settings.json":  "bl32ID_settings.json",
    "~/.pystream_pv_aliases.json":       "pv_aliases.json",
    "~/.pystream_doc_urls.json":         "doc_urls.json",
    "~/.pystream_status_pages.json":     "status_pages.json",
    "~/.pystream_ioc_scripts.json":      "ioc_scripts.json",
    "~/.pystream_qgmax_request.json":    "qgmax_request.json",
    "~/.pystream_qgmax_response.json":   "qgmax_response.json",
}
_LEGACY_DOCS_DIR = "~/.pystream_docs"
_NEW_DOCS_DIR_NAME = "docs"


def _migrate_legacy_paths() -> None:
    """Move ~/.pystream_*  →  ~/.pystream/*  on first run.
    No-op once migrated; safe to call multiple times."""
    try:
        os.makedirs(PYSTREAM_HOME, exist_ok=True)
        for old, new_rel in _LEGACY_FILES.items():
            old_path = os.path.expanduser(old)
            new_path = os.path.join(PYSTREAM_HOME, new_rel)
            if os.path.isfile(old_path) and not os.path.exists(new_path):
                try:
                    shutil.move(old_path, new_path)
                except Exception:
                    pass
        old_docs = os.path.expanduser(_LEGACY_DOCS_DIR)
        new_docs = os.path.join(PYSTREAM_HOME, _NEW_DOCS_DIR_NAME)
        if os.path.isdir(old_docs) and not os.path.exists(new_docs):
            try:
                shutil.move(old_docs, new_docs)
            except Exception:
                pass
    except Exception:
        pass  # best-effort; never block startup on a migration glitch


_migrate_legacy_paths()


# ── settings I/O ───────────────────────────────────────────────────────

def _load_all() -> dict:
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_all(data: dict):
    try:
        os.makedirs(PYSTREAM_HOME, exist_ok=True)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        _logger.error(f"Failed to save settings: {e}")


def load_settings(plugin_name: str) -> dict:
    """Load settings for a plugin. Returns empty dict if none saved."""
    return _load_all().get(plugin_name, {})


def save_settings(plugin_name: str, settings: dict):
    """Save settings for a plugin (merges with existing file)."""
    data = _load_all()
    data[plugin_name] = settings
    _save_all(data)
