#!/usr/bin/env python3
"""Unified 24/7 Supervisor for fullstack-agent."""
import os
import sys
import time
import subprocess
import signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / "venv" / "bin" / "python3"

from jarvis_log import get_logger

_slog = get_logger("supervisor")

# name -> {"proc": Popen, "log": file handle}   (handles are closed on restart)
SERVICES: dict = {}
# name -> [timestamps of recent exits]          (crash-loop detection)
RESTARTS: dict = {}
MAX_RESTARTS = 5          # give up after this many exits...
RESTART_WINDOW = 60.0     # ...within this many seconds
BACKOFF_BASE = 2.0        # first retry delay; doubles per consecutive crash

def log(msg):
    print(f"[supervisor] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)
    _slog.info("%s", msg)

def _spawn(name: str, args: list, cwd: Path, log_path: Path):
    """Start one service with its output appended to its own log file.

    The log handle lives in SERVICES so it is closed when the child dies —
    the old code leaked one fd per restart.
    """
    fh = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            [str(PYTHON)] + args,
            cwd=str(cwd),
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    except Exception:
        fh.close()
        raise
    SERVICES[name] = {"proc": proc, "log": fh}
    return proc


def start_visualizer():
    proc = _spawn("visualizer", ["server.py", "--no-open"],
                  ROOT / "ai-visualizer", ROOT / "ai-visualizer" / "face.log")
    log(f"Started ai-visualizer (PID {proc.pid}) at http://127.0.0.1:8790 (log: ai-visualizer/face.log)")


def start_barehands():
    proc = _spawn("barehands", ["server.py", "--no-open"],
                  ROOT / "barehands", ROOT / "barehands" / "hands.log")
    log(f"Started barehands gesture stage (PID {proc.pid}) at http://127.0.0.1:8794/stage.html (log: barehands/hands.log)")

def shutdown(sig, frame):
    log("Shutting down all supervised services...")
    for name, entry in list(SERVICES.items()):
        proc = entry["proc"]
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            entry["log"].close()
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    log("Initializing 24/7 Agent Subsystems...")
    start_visualizer()
    start_barehands()
    
    log("All services running. Entering watch loop...")
    while True:
        for name, entry in list(SERVICES.items()):
            proc = entry["proc"]
            poll = proc.poll()
            if poll is None:
                continue

            # The child died: close its log handle before any respawn.
            entry["log"].close()

            now = time.time()
            recent = [t for t in RESTARTS.get(name, []) if now - t <= RESTART_WINDOW]
            recent.append(now)
            RESTARTS[name] = recent

            if len(recent) > MAX_RESTARTS:
                # Crash loop (e.g. port already held): stop thrashing.
                log(f"ERROR: {name} exited {len(recent)} times within "
                    f"{int(RESTART_WINDOW)}s (last exit code {poll}). "
                    f"Giving up on it; other services keep running.")
                del SERVICES[name]
                continue

            delay = BACKOFF_BASE * (2 ** (len(recent) - 1))
            log(f"WARNING: Service {name} exited with code {poll}. "
                f"Restarting in {delay:.0f}s (attempt {len(recent)}/{MAX_RESTARTS})...")
            time.sleep(delay)
            if name == "visualizer":
                start_visualizer()
            elif name == "barehands":
                start_barehands()
        time.sleep(3)
