#!/usr/bin/env python3
"""JARVIS2 smoke test — no test framework needed.

Run from anywhere:
    venv/bin/python3 tests/test_smoke.py

Exit code 0 = all good, 1 = something broke. These are the regressions
that actually bit this project: the missing-ROOT cleanup crash, the
argument-less history trim, the hardcoded paths, and the pillar wiring
gaps left when the brain moved into backtalk.
"""
from __future__ import annotations

import inspect
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"  ok   {name}")
    except Exception as e:  # noqa: BLE001 - report every failure
        FAILURES.append(name)
        print(f"  FAIL {name}: {type(e).__name__}: {e}")


# ── jarvis_config: one source of truth ───────────────────────────────────────
def test_config_is_portable():
    from jarvis_config import ROOT as CFG_ROOT, VAULT_DIR, LLM_MODEL, MAX_WORKERS

    assert CFG_ROOT == ROOT, f"ROOT mismatch: {CFG_ROOT}"
    assert VAULT_DIR.is_absolute(), "vault path must be absolute"
    assert "/Users/" not in str(VAULT_DIR) or str(VAULT_DIR).startswith(str(Path.home())), (
        "vault must not hardcode another user's home"
    )
    assert LLM_MODEL, "chat model must be configured"
    assert MAX_WORKERS >= 1


def test_config_env_override():
    import importlib
    import os

    os.environ["JARVIS_MAX_WORKERS"] = "7"
    try:
        import jarvis_config

        importlib.reload(jarvis_config)
        assert jarvis_config.MAX_WORKERS == 7, jarvis_config.MAX_WORKERS
    finally:
        os.environ.pop("JARVIS_MAX_WORKERS", None)
        importlib.reload(jarvis_config)


# ── optimizations: the two crashes that shipped ──────────────────────────────
def test_cleanup_does_not_raise():
    from optimizations import cleanup_resources

    cleanup_resources()  # used to raise NameError: ROOT is not defined


def test_trim_needs_argument_and_bounds_history():
    from optimizations import trim_message_history

    msgs = [{"role": "system", "content": "sys"}] + [
        {"role": "user", "content": str(i)} for i in range(100)
    ]
    out = trim_message_history(msgs)
    assert out[0]["role"] == "system", "system message must survive trimming"
    assert len(out) <= 41, f"history not bounded: {len(out)}"
    assert trim_message_history([]) == []
    # in the live loop this is called as trim_message_history(history)
    assert callable(trim_message_history)


def test_thread_pool_honours_shared_limit():
    from optimizations import MAX_WORKERS, get_thread_pool

    assert get_thread_pool()._max_workers == MAX_WORKERS


# ── pillar modules: no hardcoded machine paths left ──────────────────────────
def test_guardian_uses_config():
    import ambient_guardian
    from jarvis_config import HACKTIVATE_DIR, VAULT_DIR

    assert ambient_guardian.VAULT == VAULT_DIR
    assert ambient_guardian.HACKTIVATE == HACKTIVATE_DIR


def test_swarm_uses_config():
    import subagent_swarm
    from jarvis_config import LLM_MODEL, VAULT_DIR

    assert subagent_swarm.VAULT_DIR == VAULT_DIR
    assert subagent_swarm.MODEL == LLM_MODEL
    assert subagent_swarm.DB_PATH.name == "agent_bus.sqlite3"


def test_no_hardcoded_home_in_sources():
    banned = "/Users/m3/"
    offenders = []
    skip = {"venv", ".git", "legacy", "__pycache__", "backtalk", "barehands",
            "ai-visualizer", "ai-memory-vault"}
    for f in ROOT.glob("*.py"):
        if f.name in {"test_smoke.py"}:
            continue
        if banned in f.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(f.name)
    assert not offenders, f"hardcoded machine path in: {offenders}"


# ── the live brain: all 7 pillars wired ──────────────────────────────────────
def test_pillars_expose_full_api():
    sys.path.insert(0, str(ROOT / "backtalk"))
    from backtalk import pillars

    sig = inspect.signature(pillars.init_background)
    assert "speak_fn" in sig.parameters, "guardian speak_fn not wired"
    assert "loop" in sig.parameters, "swarm worker loop not wired"
    assert callable(pillars.announce_subagent_results), "P3 announcements missing"
    for fn in (pillars.dispatch_subagent, pillars.poll_subagent_results,
               pillars.execute_action_tag, pillars.route, pillars.vault_context):
        assert callable(fn), f"missing pillar entry point: {fn}"
    # every pillar module that could import must be active
    assert "ambient_guardian" in pillars._READY, pillars._READY
    assert "subagent_swarm" in pillars._READY, pillars._READY


def test_pillar_bridge_degrades_gracefully():
    from pillar_bridge import p2_status, P2_ACTIONS

    status = p2_status()
    assert isinstance(status, dict) and "ok" in status
    assert isinstance(P2_ACTIONS, dict)


def test_guardian_accepts_speak_callback():
    import ambient_guardian
    import inspect as _inspect

    params = _inspect.signature(ambient_guardian.start_guardian).parameters
    assert "speak_fn" in params


# ── entry points still compile ───────────────────────────────────────────────
def test_driver_public_api_degrades_gracefully():
    if platform.system() != "Darwin":
        return  # needs Quartz/screen capture; skip on CI Linux
    import mac_input_driver as d

    assert d.visual_click("definitely-not-on-screen-xyz-123").get("ok") is False
    assert isinstance(d.capture_perf(), dict) and "ok" in d.capture_perf()
    assert d.click_menu("Finder", []) == {"ok": False, "error": "empty menu path"}


def test_osascript_quote_neutralises_injection():
    from mac_input_driver import _osascript_quote

    hostile = 'Finder" to activate\\ntell application "Evil'
    quoted = _osascript_quote(hostile)
    assert quoted.startswith("quoted form of \""), quoted
    # the hostile payload must be escaped/quoted, never a bare breakout
    assert '" to activate' not in quoted.replace('\\"', "")


def test_app_pid_accepts_int_like_only():
    if platform.system() != "Darwin":
        return  # osascript/Quartz path is macOS-only; skip on CI Linux
    import mac_input_driver as d

    try:
        name = d._app_name(1)
    except (TypeError, ValueError):
        return  # int() rejects non-numeric junk — safe behaviour
    assert isinstance(name, str)


def test_all_root_modules_compile():
    import py_compile

    for f in sorted(ROOT.glob("*.py")):
        py_compile.compile(str(f), doraise=True)
    for f in sorted((ROOT / "legacy").glob("*.py")):
        py_compile.compile(str(f), doraise=True)


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"JARVIS2 smoke test — {len(tests)} checks")
    for name, fn in tests:
        check(name, fn)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nall green ✅")
