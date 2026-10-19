#!/usr/bin/env python3
"""Central logging for JARVIS2 — one call per module, stdlib only.

Usage — at the top of any pillar module, replacing ``print(...)``::

    from jarvis_log import get_logger
    log = get_logger(__name__)
    log.info("daemon online")
    log.warning("ollama timeout, using fallback")
    log.error("crash prevented: %s", exc)

What you get:
  - Console (stderr): human-readable, keeps the existing ``[emoji TAG]``
    style so terminal output looks the same as before.
  - ``logs/<module>.log``: rotating file (5 MB × 3 backups by default),
    with timestamps + level, so disks stop filling up.
  - Levels + directory + rotation sizes all come from ``jarvis_config``
    (env-overridable: ``JARVIS_LOG_LEVEL``, ``JARVIS_LOG_DIR``,
    ``JARVIS_LOG_MB``, ``JARVIS_LOG_COUNT``).

Design notes:
  - Stdlib ``logging`` only — no loguru dependency, so the module works in
    bare CI venvs and as a hard dependency of every pillar.
  - Idempotent: calling ``get_logger(name)`` twice returns the same logger
    without adding duplicate handlers.
  - Never raises into the voice loop: log-directory creation failures fall
    back to console-only logging.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

try:
    from jarvis_config import LOG_BACKUPS, LOG_DIR, LOG_LEVEL, LOG_MAX_MB
except ImportError:  # standalone use without the config module
    from pathlib import Path as _Path

    LOG_LEVEL, LOG_DIR, LOG_MAX_MB, LOG_BACKUPS = "INFO", _Path("logs"), 5, 3

_CONFIGURED: set[str] = set()

_CONSOLE_FMT = logging.Formatter("%(message)s")
_FILE_FMT = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _level() -> int:
    try:
        return getattr(logging, str(LOG_LEVEL).upper())
    except AttributeError:
        return logging.INFO


def get_logger(name: str) -> logging.Logger:
    """Return the module logger for *name*, wiring console + file once."""
    logger = logging.getLogger(name)
    if name in _CONFIGURED:
        return logger
    _CONFIGURED.add(name)

    logger.setLevel(_level())
    if logger.handlers:  # configured externally (tests, embedding app)
        return logger
    logger.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_CONSOLE_FMT)
    logger.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        short = name.rsplit(".", 1)[-1]
        fh = RotatingFileHandler(
            LOG_DIR / f"{short}.log",
            maxBytes=max(1, LOG_MAX_MB) * 1024 * 1024,
            backupCount=max(0, LOG_BACKUPS),
            encoding="utf-8",
        )
        fh.setFormatter(_FILE_FMT)
        logger.addHandler(fh)
    except OSError:
        logger.warning("log dir %s unwritable; console-only logging", LOG_DIR)

    return logger


def set_level(level: str) -> None:
    """Change verbosity at runtime (e.g. voice command 'debug mode')."""
    lvl = getattr(logging, str(level).upper(), logging.INFO)
    for name in _CONFIGURED:
        logging.getLogger(name).setLevel(lvl)
