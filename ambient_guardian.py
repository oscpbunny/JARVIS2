#!/usr/bin/env python3
"""Pillar 7 – Proactive Ambient Guardian & Background Build Watcher
Persistent background vigilance that:
  - Watches build artifact dirs (.build/, DerivedData/, .git/index) via FSEvents/watchdog
  - Intercepts swift build / compiler error logs, parses them into plain-English
  - Watches git worktree for commits and branch changes
  - Monitors system resource health (CPU / RAM spikes)
  - Waits for a natural cognitive pause (>3s keyboard idle) before alerting
  - Dispatches proactive spoken notifications through Jarvis TTS
"""
import os
import sys
import re
import time
import subprocess
import threading
import sqlite3
import psutil
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from jarvis_config import ROOT, HACKTIVATE_DIR, VAULT_DIR

HACKTIVATE = HACKTIVATE_DIR
VAULT = VAULT_DIR

# SQLite alert bus – shared with subagent_swarm bus
ALERT_DB = ROOT / "agent_bus.sqlite3"

# Keyboard-idle tracking (updated externally by main loop via update_keyboard_activity())
_last_keyboard_ts: float = time.time()
IDLE_GATE_SECS = 3.0        # only speak after this many seconds of no typing

# Global speak callback (set by the brain at startup: backtalk pillars
# passes mouth.say; the legacy always_online_jarvis passes speak_sentence)
_speak_callback = None

# ─── Alert Bus ───────────────────────────────────────────────────────────────

def _init_alert_table():
    conn = sqlite3.connect(ALERT_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS guardian_alerts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            category  TEXT,
            message   TEXT,
            spoken    INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _queue_alert(category: str, message: str):
    """Queue a proactive alert. The delivery loop speaks it when the user is idle."""
    conn = sqlite3.connect(ALERT_DB)
    conn.execute(
        "INSERT INTO guardian_alerts (timestamp, category, message) VALUES (?, ?, ?)",
        (time.time(), category, message)
    )
    conn.commit()
    conn.close()
    print(f"[🛡️  GUARDIAN ALERT QUEUED] [{category}] {message}", flush=True)


def get_pending_alerts():
    conn = sqlite3.connect(ALERT_DB)
    rows = conn.execute(
        "SELECT id, category, message FROM guardian_alerts WHERE spoken = 0 ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()
    return rows


def mark_alert_spoken(alert_id: int):
    conn = sqlite3.connect(ALERT_DB)
    conn.execute("UPDATE guardian_alerts SET spoken = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


# ─── Keyboard Idle Gate ──────────────────────────────────────────────────────

def update_keyboard_activity():
    """Call this from the main voice loop on every detected keystroke / audio chunk."""
    global _last_keyboard_ts
    _last_keyboard_ts = time.time()


def _is_user_idle() -> bool:
    return (time.time() - _last_keyboard_ts) > IDLE_GATE_SECS


# ─── Swift / Xcode Build Error Parser ────────────────────────────────────────

_BUILD_ERROR_RE = re.compile(
    r"(?P<file>[^/\n]+\.swift):(?P<line>\d+):\d+:\s+error:\s+(?P<msg>[^\n]+)"
)
_BUILD_WARNING_RE = re.compile(
    r"(?P<file>[^/\n]+\.swift):(?P<line>\d+):\d+:\s+warning:\s+(?P<msg>[^\n]+)"
)
_TEST_PASS_RE = re.compile(r"Test Suite .* passed at")
_TEST_FAIL_RE = re.compile(r"Test Suite .* failed at")
_BUILD_SUCCESS_RE = re.compile(r"\*\* BUILD SUCCEEDED \*\*")
_BUILD_FAIL_RE = re.compile(r"\*\* BUILD FAILED \*\*")


def parse_build_output(text: str) -> str | None:
    """Parse swift build / xcodebuild output into a plain-English summary."""
    if _BUILD_SUCCESS_RE.search(text):
        return "Build succeeded."

    errors = _BUILD_ERROR_RE.findall(text)
    if _BUILD_FAIL_RE.search(text) or errors:
        if errors:
            f, line, msg = errors[0]
            extra = f" and {len(errors)-1} more" if len(errors) > 1 else ""
            return f"Build failed. Error in {f} on line {line}: {msg[:80]}{extra}."
        return "Build failed with unknown errors."

    passes = len(_TEST_PASS_RE.findall(text))
    fails  = len(_TEST_FAIL_RE.findall(text))
    if passes > 0 or fails > 0:
        if fails == 0:
            return f"All {passes} test suite{'s' if passes > 1 else ''} passed."
        return f"{fails} test suite{'s' if fails > 1 else ''} failed, {passes} passed."

    warnings = _BUILD_WARNING_RE.findall(text)
    if warnings:
        f, line, msg = warnings[0]
        return f"Build warning in {f} on line {line}: {msg[:80]}."

    return None


# ─── FSEvents File Watcher ────────────────────────────────────────────────────

class BuildWatchHandler(FileSystemEventHandler):
    """Watches .build/, DerivedData/, and compiler log outputs."""

    COMPILER_LOG_SUFFIX = ".log"
    _debounce: dict = {}

    def _debounced(self, path: str, window: float = 4.0) -> bool:
        now = time.time()
        if now - self._debounce.get(path, 0) < window:
            return False
        self._debounce[path] = now
        return True

    def on_modified(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if not self._debounced(str(p)):
            return

        # Compiler log files
        if p.suffix in (".log", ".txt") and ("build" in p.parts or "DerivedData" in p.parts):
            try:
                tail = p.read_text(errors="ignore")[-3000:]
                summary = parse_build_output(tail)
                if summary:
                    _queue_alert("build", summary)
            except Exception:
                pass

    def on_created(self, event):
        """Triggered when new build artifacts appear."""
        p = Path(event.src_path)
        if p.name == "all-product-headers.yaml":
            _queue_alert("build", "New build started for your project.")


class GitWatchHandler(FileSystemEventHandler):
    """Watches .git/index for commit / branch changes."""
    _last_branch = ""

    def on_modified(self, event):
        p = Path(event.src_path)
        if p.name in ("HEAD", "COMMIT_EDITMSG", "index"):
            try:
                result = subprocess.run(
                    ["git", "-C", str(HACKTIVATE), "log", "--oneline", "-1"],
                    capture_output=True, text=True, timeout=3
                )
                msg = result.stdout.strip()
                if msg:
                    _queue_alert("git", f"New commit: {msg[:80]}.")
            except Exception:
                pass


# ─── System Health Monitor ───────────────────────────────────────────────────

def _system_health_loop():
    """Periodically check CPU and RAM. Alert if sustained high usage."""
    HIGH_CPU = 90.0
    HIGH_RAM = 85.0
    cpu_spike_count = 0
    last_cpu_alert = 0.0
    last_ram_alert = 0.0
    COOLDOWN = 600.0  # 10 minutes between duplicate alerts

    while True:
        now = time.time()
        cpu = psutil.cpu_percent(interval=5)
        mem = psutil.virtual_memory()
        ram = mem.percent
        available = mem.available
        total = mem.total

        # FIX: macOS aggressively caches memory, so high percent is normal.
        # Only alert if memory is actually low (use available memory, not total).
        ram_pressure = 100.0 - (available / total * 100.0) if total > 0 else 0.0

        if cpu > HIGH_CPU:
            cpu_spike_count += 1
            if cpu_spike_count >= 3 and (now - last_cpu_alert > COOLDOWN):
                _queue_alert("system", f"CPU has been above {HIGH_CPU:.0f}% for 15 seconds. Consider closing heavy apps.")
                last_cpu_alert = now
                cpu_spike_count = 0
        else:
            cpu_spike_count = 0

        # FIX: Only alert if RAM is truly low (less than 10% free), not just cached
        if ram_pressure > HIGH_RAM and (now - last_ram_alert > COOLDOWN):
            _queue_alert("system", f"RAM usage is at {ram:.0f}%. Consider closing heavy apps.")
            last_ram_alert = now

        time.sleep(10)


# ─── Alert Delivery Loop ──────────────────────────────────────────────────────

def _delivery_loop():
    """
    Continuously checks for pending alerts.
    Only delivers them when the user has been keyboard-idle for IDLE_GATE_SECS.
    """
    _init_alert_table()
    while True:
        time.sleep(1.5)
        if not _is_user_idle():
            continue
        alerts = get_pending_alerts()
        for alert_id, category, message in alerts:
            if not _is_user_idle():
                break
            # Deliver via speak callback or print
            if _speak_callback:
                try:
                    _speak_callback(message)
                except Exception:
                    pass
            else:
                print(f"[🛡️  GUARDIAN SPEAKS]: {message}", flush=True)
            mark_alert_spoken(alert_id)
            time.sleep(2.0)  # gap between sequential alerts


# ─── Terminal Build Output Watcher (tail -f approach) ────────────────────────

def _terminal_log_watcher():
    """
    Watches jarvis_daemon.log for swift build output piped through terminal.
    Users can pipe: swift build 2>&1 | tee -a jarvis_daemon.log
    """
    log_path = ROOT / "jarvis_daemon.log"
    last_size = log_path.stat().st_size if log_path.exists() else 0

    while True:
        time.sleep(3)
        try:
            if not log_path.exists():
                continue
            current_size = log_path.stat().st_size
            if current_size <= last_size:
                continue
            with open(log_path, "r", errors="ignore") as f:
                f.seek(last_size)
                new_text = f.read()
            last_size = current_size
            summary = parse_build_output(new_text)
            if summary:
                _queue_alert("build", summary)
        except Exception:
            pass


# ─── Public API ──────────────────────────────────────────────────────────────

_observer = None
_threads_started = False


def start_guardian(speak_fn=None):
    """
    Start the Ambient Guardian.
    speak_fn: callable(text: str) – the Jarvis TTS function to call for proactive alerts.
    """
    global _speak_callback, _observer, _threads_started
    if _threads_started:
        return
    _threads_started = True

    if speak_fn:
        _speak_callback = speak_fn

    _init_alert_table()

    # FSEvents observers
    _observer = Observer()

    # Watch hacktivate .build directory
    build_dir = HACKTIVATE / ".build"
    if not build_dir.exists():
        build_dir.mkdir(parents=True, exist_ok=True)
    _observer.schedule(BuildWatchHandler(), str(build_dir), recursive=True)

    # Watch DerivedData
    derived = Path.home() / "Library/Developer/Xcode/DerivedData"
    if derived.exists():
        _observer.schedule(BuildWatchHandler(), str(derived), recursive=False)

    # Watch git index
    git_dir = HACKTIVATE / ".git"
    if git_dir.exists():
        _observer.schedule(GitWatchHandler(), str(git_dir), recursive=False)

    _observer.start()

    # Background threads
    threading.Thread(target=_delivery_loop,       daemon=True, name="GuardianDelivery").start()
    threading.Thread(target=_system_health_loop,  daemon=True, name="GuardianHealth").start()
    threading.Thread(target=_terminal_log_watcher, daemon=True, name="GuardianLogTail").start()

    print("[🛡️  AMBIENT GUARDIAN ONLINE] Watching build, git, system health.", flush=True)


def stop_guardian():
    global _observer
    if _observer:
        _observer.stop()
        _observer.join()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def demo_speak(msg):
        print(f"[SPEAK] {msg}")

    start_guardian(speak_fn=demo_speak)
    print("Guardian running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_guardian()
