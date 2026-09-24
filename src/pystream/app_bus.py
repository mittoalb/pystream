"""PystreamBus — the named signals pystream widgets use to talk to each other.

Lives on ``PvViewerApp`` as ``self.bus``; every dialog/plugin picks it
up via ``parent.bus``. Add new events here as they come up; do NOT
grow disk-based handshakes (``~/.pystream/*_request.json``) or peek at
other widgets' internals for the same purpose.

Note: ``PvViewerApp.image_ready`` already exists as the frame signal
and stays where it is — plugins connect to ``parent.image_ready``.
The bus carries only the signals that don't have a natural home yet.
"""

from __future__ import annotations

from PyQt5 import QtCore

from bmsg import AppBus


class PystreamBus(AppBus):
    # External optimization request from same-process clients
    # (e.g. XANES2D gui.py). Payload is the dict that used to go
    # into ~/.pystream/qgmax_request.json:
    #     {"cmd": "auto_enable"|"auto_disable"|None, "run_every": int, "ts": float}
    qgmax_trigger = QtCore.pyqtSignal(dict)

    # Coarse scan state so any plugin can react without polling PVs
    # or peeking at scan-dialog attributes. Values: "running",
    # "paused", "idle", "aborted".
    scan_state_changed = QtCore.pyqtSignal(str)
