#!/usr/bin/env python3
"""Obsidian Second Brain 24/7 Sync & Memory Digest for Jarvis."""
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

from jarvis_config import VAULT_DIR, ROOT
from jarvis_log import get_logger

_slog = get_logger("obsidian_sync")

VAULT_PATH = VAULT_DIR
AGENT_DIR = ROOT
# Legacy mirror path (kept for tail-compat). Unbounded appends here stopped:
# jarvis_log RotatingFileHandler in logs/ is the record; this file only keeps
# the last N lines so existing `tail -f obsidian_sync.log` keeps working.
SYNC_LOG = AGENT_DIR / "obsidian_sync.log"
_SYNC_LOG_KEEP = 200

def log(msg):
    # Console style preserved (Phase 7 convention: print human line + _slog).
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    _slog.info("%s", msg)
    try:
        if SYNC_LOG.exists():
            with open(SYNC_LOG, "r", encoding="utf-8", errors="ignore") as f:
                tail = f.readlines()[-(_SYNC_LOG_KEEP - 1):]
        else:
            tail = []
        with open(SYNC_LOG, "w", encoding="utf-8") as f:
            f.writelines(tail)
            f.write(line + "\n")
    except OSError:
        pass  # rotating logs/ copy already captured it; never raise

def check_vault_connection():
    if not VAULT_PATH.exists():
        log(f"Notice: Obsidian Vault at {VAULT_PATH} not accessible or waiting for mount.")
        return False
    return True

def get_today_daily_note():
    today = datetime.now().strftime("%Y-%m-%d")
    daily_folder = VAULT_PATH / "Daily"
    note = daily_folder / f"{today}.md"
    return note

def append_task_to_daily_note(task_text):
    if not check_vault_connection():
        return False
    note = get_today_daily_note()
    note.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%H:%M")
    entry = f"- [ ] `{timestamp}` #jarvis-task {task_text}\n"
    
    with open(note, "a", encoding="utf-8") as f:
        f.write(entry)
    log(f"Recorded task to Daily Note: {task_text}")
    return True

if __name__ == "__main__":
    log("Running Obsidian Second Brain 24/7 sync check...")
    connected = check_vault_connection()
    if connected:
        log(f"Connected to Obsidian Second Brain at {VAULT_PATH}")
    else:
        log("Vault watcher in standby.")
