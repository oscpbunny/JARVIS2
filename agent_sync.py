#!/usr/bin/env python3
"""One-command agent sync - keeps parallel agents collision-free.

Usage:
  agent_sync.py                 # human table: tree + lanes + health
  agent_sync.py --json          # machine-readable snapshot
  agent_sync.py --claim "..."   # log a CLAIM before editing
  agent_sync.py --done "..."    # log a DONE after verifying

Structured 5W handoff (WHO/WHAT/WHEN/HOW/WHY + ASK) - preferred whenever the
other agent must act, because bare CLAIM/DONE lines drop the reasoning and the
receiver is forced to guess at risk:
  agent_sync.py --msg  --what "did X" --when "now" --how "method + verify" \
      --why "reason" --q "question for the other lane"
  agent_sync.py --ask --who "Kilo" --what "status of Y" --why "risk if ignored" \
      --q "when/how will you land it?"
Flags: --who owner | --what action+files | --when timing/urgency |
       --how method+verification | --why motivation | --q the question |
       --kind MSG|ASK (default ASK if --ask present else MSG)
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent
COORD = ROOT / "AGENTS_COORDINATION.md"
LANES = (
    ("always_online_jarvis.py", "integration"),
    ("subagent_swarm.py", "integration"),
    ("screen_recorder.py", "integration"),
    ("ambient_guardian.py", "integration"),
    ("backtalk/", "integration"),
    ("mac_input_driver.py", "driver"),
    ("ax_selected_text.py", "driver"),
    ("pillar_bridge.py", "driver"),
    ("legacy/speech_duplex.py", "driver"),
    ("vault_index.py", "perf"),
    ("jarvis_health.py", "perf"),
    ("agent_sync.py", "perf"),
    ("tests/test_parallel_safe.py", "perf"),
    ("jarvis_actions.py", "shared:integration-owner"),
    ("obsidian_rag.py", "shared:integration-owner"),
    ("obsidian_sync.py", "perf"),
    ("supervisor.py", "perf"),
    ("screen_vision.py", "perf"),
    ("code_inspector.py", "perf"),
    (".github/workflows/ci.yml", "perf"),
    ("jarvis_config.py", "shared: config — claim before edit"),
    ("AGENTS_COORDINATION.md", "coordination: all agents append-only"),
)
def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""
def lane_of(path: str) -> str:
    for prefix, lane in LANES:
        if path == prefix or path.startswith(prefix) or path.endswith(prefix):
            return lane
    return "unassigned"
def claims(n: int = 8):
    try:
        lines = COORD.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    # any dated bullet counts as a log entry (CLAIM/DONE/Ack/Added... all use
    # "- YYYY-MM-DD <who>: <msg>"; matching only keywords misses e.g. Kilo's
    # "Added timeout=5.0 ..." claim line and re-flags their files as unclaimed)
    log = [ln for ln in lines if re.match(r"^- \d{4}-\d{2}-\d{2} ", ln)]
    return log[-n:]
def unclaimed_edits():
    status = _git("status", "--short")
    if not status:
        return []
    log_text = "\n".join(claims(40)).lower()
    risky = []
    for line in status.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        f = parts[1].split(" -> ")[-1].strip().strip('"')
        if f == "AGENTS_COORDINATION.md":
            continue
        base = Path(f).name.lower()
        if base not in log_text and f.lower() not in log_text:
            risky.append(f"{f} [{lane_of(f)}]")
    return risky
def snapshot():
    status = _git("status", "--short")
    files = []
    for line in status.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        f = parts[1].split(" -> ")[-1].strip().strip('"')
        files.append({"path": f, "state": parts[0], "lane": lane_of(f)})
    try:
        sys.path.insert(0, str(ROOT))
        # pillar loading prints a "[pillars] active:" preamble at import time;
        # capture it so --json stays parseable for machine consumers.
        import contextlib, io
        _buf = io.StringIO()
        with contextlib.redirect_stdout(_buf):
            import jarvis_health as _h
            health = _h.check()
        _import_preamble = _buf.getvalue().strip()
    except Exception as e:
        health = {"ok": None, "warnings": [f"health probe failed: {e}"], "info": {}}
        _import_preamble = ""
    try:
        import vault_index as _v
        cache = _v.stats()
    except Exception:
        cache = {}
    return {"ok": (not unclaimed_edits()) and not health.get("warnings"), "files": files, "unclaimed_edits": unclaimed_edits(), "recent_claims": claims(), "health_warnings": health.get("warnings", []), "health_info": health.get("info", {}), "vault_cache": cache, "import_preamble": _import_preamble}
def cmd_claim(msg: str, kind: str = "CLAIM") -> int:
    msg = " ".join(msg.split())
    if not msg.upper().startswith(kind):
        msg = f"{kind} {msg}"
    line = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} Cline (perf lane): {msg}\n"
    try:
        open(COORD, "a", encoding="utf-8").write(line)
        print(f"logged: {line.strip()}")
        return 0
    except OSError as e:
        print(f"claim failed: {e}", file=sys.stderr)
        return 1

def cmd_msg(who: str, what: str, when: str = "", how: str = "", why: str = "",
            ask: str = "", kind: str = "MSG") -> int:
    """Structured 5W coordination message.

    Bare CLAIM/DONE lines lose the reasoning, so the other agent cannot
    judge risk or act without guessing. Every handoff answers the five W's
    and, when there is a request, ends with an explicit ASK (a question the
    receiver can act on). who=owner, what=action+files, when=timing/urgency,
    how=method/verify, why=motivation, ask=open question for the other lane.
    """
    who = " ".join(who.split()) or "Cline (perf lane)"
    parts = [f"{kind} by {who}: {' '.join(what.split())}"]
    if when:
        parts.append(f"WHEN: {' '.join(when.split())}")
    if how:
        parts.append(f"HOW: {' '.join(how.split())}")
    if why:
        parts.append(f"WHY: {' '.join(why.split())}")
    if ask:
        parts.append(f"ASK: {' '.join(ask.split())}")
    body = " | ".join(parts)
    line = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} {body}\n"
    try:
        open(COORD, "a", encoding="utf-8").write(line)
        print(f"logged: {line.strip()}")
        return 0
    except OSError as e:
        print(f"msg failed: {e}", file=sys.stderr)
        return 1

def _flagval(flag: str, default: str = "") -> str:
    """Pull '--flag value' out of argv (value may contain spaces if quoted).

    A flag used bare (next token is another --flag) returns the default, so a
    trigger flag never swallows a following flag as its value.
    """
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default

def main() -> int:
    if "--msg" in sys.argv or "--ask" in sys.argv:
        kind = _flagval("--kind", "ASK" if ("--ask" in sys.argv and "--msg" not in sys.argv) else "MSG")
        return cmd_msg(
            who=_flagval("--who", "Cline (perf lane)"),
            what=_flagval("--what", "(no what)"),
            when=_flagval("--when"),
            how=_flagval("--how"),
            why=_flagval("--why"),
            ask=_flagval("--q"),
            kind=kind,
        )
    if "--claim" in sys.argv:
        i = sys.argv.index("--claim")
        return cmd_claim(" ".join(sys.argv[i + 1:]) or "(no message)", "CLAIM")
    if "--done" in sys.argv:
        i = sys.argv.index("--done")
        return cmd_claim(" ".join(sys.argv[i + 1:]) or "(no message)", "DONE")
    snap = snapshot()
    if "--json" in sys.argv:
        print(json.dumps(snap, indent=2))
        return 0
    print("sync " + ("CLEAN" if snap["ok"] else "ATTENTION"))
    print("-- tree --")
    if not snap["files"]:
        print("  clean")
    for f in snap["files"]:
        print(f"  {f['state']:3} {f['path']} [{f['lane']}]")
    if snap["unclaimed_edits"]:
        print("UNCLAIMED (no CLAIM line):")
        [print(f"  - {u}") for u in snap["unclaimed_edits"]]
    print("health warnings:", snap["health_warnings"] or "none")
    print("recent claims:")
    [print(f"  {c[:120]}") for c in snap["recent_claims"][-5:]]
    print(f"vault cache: {snap['vault_cache']}")
    return 0
if __name__ == "__main__":
    sys.exit(main())
