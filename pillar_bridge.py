#!/usr/bin/env python3
"""Driver-lane handoff bridge (Cline) — single import point for P2/P5/P6.

Integration lane (daemon owner) needs exactly ONE line::

    from pillar_bridge import dispatch_p2, selection_context, make_duplex_speech

plus ONE dispatch branch inside the daemon's action router::

    res = dispatch_p2(raw_action)
    if res:
        ...speak res...

This module never touches the daemon, skill engine, swarm, recorder, or
guardian. Every entry point degrades gracefully (returns {"ok": False} or
None instead of raising) so the voice loop can never die from here.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Pillar 2 — GUI computer-use driver (mac_input_driver.py, driver lane)
# --------------------------------------------------------------------------

try:
    import mac_input_driver as _drv  # type: ignore

    _P2_OK = True
except Exception:  # pragma: no cover
    _drv = None  # type: ignore
    _P2_OK = False


def _p2_wrap(fn_name: str, *args, **kwargs) -> dict:
    """Call a driver fn, normalising to {"ok": bool, ...}."""
    if not _P2_OK:
        return {"ok": False, "error": "mac_input_driver unavailable"}
    try:
        return getattr(_drv, fn_name)(*args, **kwargs)
    except Exception as e:  # never raise into the voice loop
        return {"ok": False, "error": f"{fn_name}: {e}"}


def dispatch_p2(action_tag: str) -> str | None:
    """Route a raw '[ACTION: ...]' tag to the P2 driver.

    Returns a speakable result string, or None if not a P2 action.
    """
    m = re.search(r"\[ACTION:\s*([^\]]+)\]", action_tag, re.IGNORECASE)
    if not m:
        return None
    parts = m.group(1).strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "move_to":
        nums = re.findall(r"-?\d+\.?\d*", arg)
        if len(nums) < 2:
            return "I need coordinates like: move_to 800 450."
        r = _p2_wrap("move_to", float(nums[0]), float(nums[1]))
        return "Cursor moved." if r.get("ok") else f"Move failed: {r.get('error')}"
    if cmd in ("click", "click_at"):
        nums = re.findall(r"-?\d+\.?\d*", arg)
        r = _p2_wrap("click", float(nums[0]), float(nums[1])) if nums \
            else _p2_wrap("click")
        return "Clicked." if r.get("ok") else f"Click failed: {r.get('error')}"
    if cmd in ("double_click", "doubleclick"):
        r = _p2_wrap("click", clicks=2)
        return "Double-clicked." if r.get("ok") else f"Click failed: {r.get('error')}"
    if cmd == "drag":
        nums = re.findall(r"-?\d+\.?\d*", arg)
        if len(nums) < 4:
            return "I need drag coordinates like: drag 100 200 400 500."
        r = _p2_wrap("drag", *[float(n) for n in nums[:4]])
        return "Dragged." if r.get("ok") else f"Drag failed: {r.get('error')}"
    if cmd in ("press_key", "press", "key"):
        found = re.findall(r"\d+", arg)
        if not found:
            return "I need a keycode like: press_key 36."
        r = _p2_wrap("press_key", int(found[0]))
        return "Key pressed." if r.get("ok") else f"Key failed: {r.get('error')}"
    if cmd in ("type_keys", "type_gui"):
        r = _p2_wrap("type_keys", arg)
        return f"Typed {arg!r}." if r.get("ok") else f"Type failed: {r.get('error')}"
    if cmd in ("click_element", "click_button", "click_text"):
        app, label = None, arg
        if "|" in arg:  # "App Name | label"
            app, label = [s.strip() for s in arg.split("|", 1)]
        r = _p2_wrap("click_element", label, app_name=app)
        return f"Clicked {label}." if r.get("ok") else f"Couldn't find {label}."
    if cmd in ("click_menu", "menu"):
        bits = [b.strip() for b in arg.split("|")]
        if len(bits) < 2:
            return "I need a path like: click_menu Safari | File | New Window."
        r = _p2_wrap("click_menu", bits[0], bits[1:])
        return "Menu clicked." if r.get("ok") else f"Menu failed: {r.get('error')}"
    if cmd in ("visual_click", "see_and_click", "find_and_click"):
        r = _p2_wrap("visual_click", arg)
        return "Found it and clicked." if r.get("ok") else f"Couldn't see {arg}."
    if cmd in ("davinci_page", "resolve_page"):
        r = _p2_wrap("davinci_page", arg.strip().title() or "Edit")
        return f"Switched to the {arg} page." if r.get("ok") else "Page switch failed."
    if cmd in ("davinci_render", "render_4k"):
        r = _p2_wrap("davinci_render_youtube_4k")
        return "Render flow started." if r.get("ok") else "Render flow needs a hand."
    return None


P2_ACTIONS: dict[str, Callable[..., dict]] = {}
if _P2_OK:
    for _name in (
        "screen_bounds", "screen_has_changed", "focus_app_window",
        "capture_perf", "ax_perf",
        "current_cursor", "move_to", "click",
        "press_key", "type_keys", "get_ax_tree", "find_element",
        "click_element", "drag", "click_menu",
        "visual_click", "davinci_page", "davinci_render_youtube_4k",
        "ensure_front",
        "get_menubar_items", "get_dock_apps",
    ):
        if hasattr(_drv, _name):
            P2_ACTIONS[_name] = getattr(_drv, _name)


def p2_status() -> dict:
    """Health check the integration lane can log at boot."""
    if not _P2_OK:
        return {"ok": False, "error": "mac_input_driver import failed"}
    try:
        x, y = _drv.current_cursor()
        return {"ok": True, "cursor": (x, y), "actions": sorted(P2_ACTIONS)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Pillar 6 — selected-code inspector (ax_selected_text.py, driver lane)
# --------------------------------------------------------------------------

try:
    from ax_selected_text import get_selected_text as _gst  # type: ignore
    from ax_selected_text import selection_context  # type: ignore

    _P6_OK = True
except Exception:  # pragma: no cover
    _P6_OK = False

    def selection_context(label: str = "highlighted code") -> str:  # type: ignore
        return ""

    def _gst(*a: Any, **k: Any) -> dict:  # type: ignore
        return {"ok": False, "error": "ax_selected_text unavailable"}


def get_selection() -> dict:
    """Safe wrapper: {"ok", "text", "backend"} — never raises."""
    try:
        return _gst()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Pillar 5 — full-duplex barge-in (legacy/speech_duplex.py, driver lane)
# --------------------------------------------------------------------------

def _load_duplex_class() -> Any | None:
    path = ROOT / "legacy" / "speech_duplex.py"
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("driver_speech_duplex", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        return mod.DuplexSpeech
    except Exception:
        return None


def make_duplex_speech(tts_pipeline: Any, trigger_thresh: float | None = None,
                       **kwargs: Any) -> Any | None:
    """Build the spec-grade DuplexSpeech engine (echo-floor + 2-slice gate).

    Returns None if the module can't load — caller falls back to its
    existing engine. `trigger_thresh` should be the daemon's calibrated
    mic level so speaker leakage never trips barge-in.
    """
    cls = _load_duplex_class()
    if cls is None:
        return None
    engine = cls(tts_pipeline, **kwargs)
    if trigger_thresh is not None:
        try:
            engine.configure(trigger_thresh=trigger_thresh)
        except Exception:
            pass
    return engine


def p5_verdict() -> str:
    """One-line guidance for the integration lane's P5 choice."""
    return (
        "legacy/speech_duplex.DuplexSpeech (echo-floor + 2-slice gate, ~90ms, "
        "45ms TTS slicing, pure-logic self-test) supersedes "
        "voice_bargein.FullDuplexAudioEngine (sd.stop() + blocking sd.play, "
        "no mic monitor wired). Swap via make_duplex_speech()."
    )


if __name__ == "__main__":
    print("P2:", p2_status())
    print("P6:", get_selection())
    print("P5:", p5_verdict())
    print("P5 loads:", _load_duplex_class() is not None)
