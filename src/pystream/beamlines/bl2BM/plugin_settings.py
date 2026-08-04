"""
Shared settings persistence for bl32ID plugins.

Stores all plugin settings in a single JSON file.
Each plugin gets its own section keyed by class name.
"""

import json
import os
import logging
from typing import Any, Dict, Optional

SETTINGS_FILE = os.path.expanduser("~/.pystream_bl32ID_settings.json")

_logger = logging.getLogger(__name__)


def _load_all() -> dict:
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_all(data: dict):
    try:
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
