"""Centralised logging with coloured terminal output.

Usage
-----
    from xraysource.logger import get_logger, configure_logging
    log = get_logger(__name__)
    log.info("hello")

The first call to `configure_logging()` sets a StreamHandler on the
root of the package with a ColorFormatter. Subsequent calls adjust
the level. Colours are auto-detected: a TTY on stderr gets ANSI
colours; a pipe/file does not. Honours the standard `NO_COLOR` env
var (https://no-color.org) and `FORCE_COLOR=1` for the opposite.

CLI: `xraysource --log-level debug ...` (see cli.py).
GUI: the log level is inherited from the environment; a menu action
lets the user change it.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_PACKAGE_LOGGER = "xraysource"

# ANSI escape sequences
_RESET = "\033[0m"
_BOLD  = "\033[1m"
_DIM   = "\033[2m"
_COLOURS = {
    logging.DEBUG:    "\033[36m",       # cyan
    logging.INFO:     "\033[32m",       # green
    logging.WARNING:  "\033[33m",       # yellow
    logging.ERROR:    "\033[31m",       # red
    logging.CRITICAL: "\033[1;97;41m",  # bold white on red
}
_LEVEL_TAG = {
    logging.DEBUG:    "DEBUG",
    logging.INFO:     " INFO",
    logging.WARNING:  " WARN",
    logging.ERROR:    "ERROR",
    logging.CRITICAL: "CRIT ",
}


def _want_colour(stream) -> bool:
    """True when it makes sense to emit ANSI colours to `stream`."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR", "").lower() in ("1", "true", "yes"):
        return True
    try:
        return bool(stream and hasattr(stream, "isatty") and stream.isatty())
    except Exception:
        return False


class ColorFormatter(logging.Formatter):
    """Formatter that colours the level + logger-name field.

    Format:  HH:MM:SS  LEVEL  logger.name  message
    """

    def __init__(self, use_colour: bool):
        super().__init__(datefmt="%H:%M:%S")
        self.use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        tag = _LEVEL_TAG.get(record.levelno, record.levelname)
        name = record.name
        msg = record.getMessage()
        # Strip the "xraysource." prefix from names for brevity
        if name.startswith(_PACKAGE_LOGGER + "."):
            name = name[len(_PACKAGE_LOGGER) + 1:]
        elif name == _PACKAGE_LOGGER:
            name = "-"
        if self.use_colour:
            colour = _COLOURS.get(record.levelno, "")
            line = (f"{_DIM}{ts}{_RESET} "
                    f"{colour}{tag}{_RESET} "
                    f"{_DIM}{name:>14s}{_RESET}  {msg}")
        else:
            line = f"{ts} {tag} {name:>14s}  {msg}"
        # Attach exception info the standard way
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def get_logger(name: str = _PACKAGE_LOGGER) -> logging.Logger:
    """Return a logger. `name=__name__` is the recommended pattern."""
    return logging.getLogger(name)


def configure_logging(level: str | int = "INFO",
                       stream=None,
                       use_colour: Optional[bool] = None) -> logging.Logger:
    """Install (or reconfigure) the package-wide handler.

    Parameters
    ----------
    level : level name ("DEBUG", "INFO", ...) or numeric level.
    stream : output stream (default sys.stderr).
    use_colour : force colour on/off; None auto-detects.

    Returns the package root logger. Safe to call more than once.
    """
    if stream is None:
        stream = sys.stderr
    if use_colour is None:
        use_colour = _want_colour(stream)
    if isinstance(level, str):
        level = level.upper()
        num = logging.getLevelName(level)
        if not isinstance(num, int):
            num = logging.INFO
        level = num

    root = logging.getLogger(_PACKAGE_LOGGER)
    # Remove old handlers we installed, keep others alone
    for h in list(root.handlers):
        if getattr(h, "_xraysource_owned", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ColorFormatter(use_colour=use_colour))
    handler._xraysource_owned = True  # type: ignore[attr-defined]
    handler.setLevel(level)
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False   # do not spill to Python's root logger
    return root


class QtLogHandler(logging.Handler):
    """Optional Qt handler: forwards records to a callback in the GUI.

    The GUI installs one of these to pipe log messages into a status
    bar or a log panel. Callback signature: callback(level_num, text).
    """

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        try:
            self.callback(record.levelno, msg)
        except Exception:
            pass
