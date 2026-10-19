#!/usr/bin/env python3
"""Read-only health probe for JARVIS2 — no daemons touched, never raises.

Checks:
  - agent_bus.sqlite3 / screen_memory.sqlite3 sizes (128M screen DB was the flag)
  - logs/*.log + legacy *.log sizes
  - pillars._READY (live brain wiring) without starting background threads
  - ollama models reachable (short timeout, optional)
  - vault_index cache stats

Usage:
  venv/bin/python3 jarvis_health.py
  venv/bin/python3 jarvis_health.py --json
Exit 0 = checked (even with warnings), 1 = probe itself crashed (shouldn't).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WARN_DB_MB = 200       # screen_memory alert threshold
WARN_LOG_MB = 20       # single log file alert threshold
WARN_BUS_MB = 50


def _size(p: Path) -> int:
    try:
        return p.stat().st_size if p.exists() else -1
    except OSError:
        return -1


def _mb(n: int) -> float:
    return round(n / 1024 / 1024, 1) if n >= 0 else -1


def check() -> dict:
    out: dict = {"ok": True, "warnings": [], "info": {}}

    def warn(msg: str):
        out["warnings"].append(msg)

    # DB sizes
    for name in ("agent_bus.sqlite3", "screen_memory.sqlite3"):
        sz = _size(ROOT / name)
        out["info"][name + "_mb"] = _mb(sz)
        if name.startswith("screen") and sz > WARN_DB_MB * 1024 * 1024:
            warn(f"{name} { _mb(sz)}MB > {WARN_DB_MB}MB — run screen_recorder.prune_db()")
        if name.startswith("agent") and sz > WARN_BUS_MB * 1024 * 1024:
            warn(f"{name} {_mb(sz)}MB > {WARN_BUS_MB}MB — vacuum / prune old tasks")

    # task queue counts (read-only query, short timeout so we never block swarm)
    try:
        conn = sqlite3.connect(ROOT / "agent_bus.sqlite3", timeout=2.0)
        try:
            for status in ("pending", "running", "completed"):
                try:
                    n = conn.execute(
                        "SELECT COUNT(*) FROM task_queue WHERE status=?", (status,)
                    ).fetchone()[0]
                    out["info"][f"tasks_{status}"] = n
                except Exception:
                    pass
        finally:
            conn.close()
    except Exception as e:
        out["info"]["task_counts"] = f"unavailable: {e}"

    # log sizes
    big_logs = []
    for logf in list((ROOT / "logs").glob("*.log")) + list(ROOT.glob("*.log")):
        try:
            sz = logf.stat().st_size
            if sz > WARN_LOG_MB * 1024 * 1024:
                big_logs.append(f"{logf.name} {_mb(sz)}MB")
        except OSError:
            pass
    out["info"]["oversize_logs"] = big_logs
    if big_logs:
        warn("oversize logs: " + ", ".join(big_logs))

    # live brain wiring — import only, NEVER init_background()
    try:
        sys.path.insert(0, str(ROOT / "backtalk"))
        from backtalk import pillars as _p
        ready = sorted(getattr(_p, "_READY", []))
        out["info"]["pillars_ready"] = ready
        for need in ("ambient_guardian", "subagent_swarm"):
            if need not in ready:
                warn(f"pillar {need} not wired in live brain")
    except Exception as e:
        warn(f"pillars import failed: {e}")

    # ollama quick ping (2s, optional)
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            out["info"]["ollama"] = f"up ({r.status})"
    except Exception as e:
        out["info"]["ollama"] = f"down: {type(e).__name__}"

    # vault cache
    try:
        import vault_index as _vi
        out["info"]["vault_cache"] = _vi.stats()
        out["info"]["vault_dir"] = str(_vi.VAULT_DIR)
    except Exception as e:
        out["info"]["vault_cache"] = f"unavailable: {e}"

    out["ok"] = not out["warnings"]
    return out


def main() -> int:
    report = check()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print("JARVIS health " + ("OK ✅" if report["ok"] else "WARNINGS ⚠️"))
        for k, v in report["info"].items():
            print(f"  {k}: {v}")
        for w in report["warnings"]:
            print(f"  ⚠️ {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
