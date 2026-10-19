# backtalk: talk to your local AI agent out loud.
# Copyright (C) 2026 oscpbunny
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 7-pillar bridge — backtalk's doorway to the full Jarvis stack.

backtalk is the single brain now. This module reaches out of the
backtalk package into the repo root and wires in the seven abilities
that used to live only in always_online_jarvis.py:

  P1 dynamic skills   (jarvis_actions -> skills/dynamic_skill_engine)
  P2 GUI control      (pillar_bridge -> mac_input_driver)
  P3 subagent swarm   (subagent_swarm -> async SQLite bus)
  P4 screen recall    (screen_recorder -> Quartz/Vision OCR)
  P5 barge-in         (already in mouth/ears)
  P6 code inspector   (code_inspector / ax_selected_text)
  P7 ambient guard    (ambient_guardian -> FSEvents + psutil)

Every import is guarded and every call wrapped: a pillar whose dep is
missing simply disables itself and logs once. The voice line must never
crash because a pillar is absent.

`route()` is the single entry brain.py calls before the LLM. It returns
(speak_or_None, context_or_None):
  - speak set    -> answer locally, DO NOT call the LLM, just say it.
  - context set  -> inject into the LLM prompt (code / vault) and stream.
  - both None    -> plain LLM turn, nothing matched.
Routing order and keywords mirror always_online_jarvis.main_loop so
spoken behavior is identical however the request arrives.
"""
import asyncio
import sys
from pathlib import Path

from backtalk.vlog import log
from backtalk import learning

# The repo root is three levels up from backtalk/backtalk/pillars.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _try_import(name):
    """Import a root-level pillar module, or None if its deps are absent."""
    try:
        return __import__(name)
    except Exception as e:                       # pragma: no cover
        log(f"[pillars] {name} unavailable: {e!r}")
        return None


_jarvis_actions = _try_import("jarvis_actions")
_screen_vision = _try_import("screen_vision")
_obsidian_rag = _try_import("obsidian_rag")
_subagent_swarm = _try_import("subagent_swarm")
_pillar_bridge = _try_import("pillar_bridge")
_screen_recorder = _try_import("screen_recorder")
_code_inspector = _try_import("code_inspector")
_ambient_guardian = _try_import("ambient_guardian")

_READY = [n for n, m in (
    ("jarvis_actions", _jarvis_actions), ("screen_vision", _screen_vision),
    ("obsidian_rag", _obsidian_rag), ("subagent_swarm", _subagent_swarm),
    ("pillar_bridge", _pillar_bridge), ("screen_recorder", _screen_recorder),
    ("code_inspector", _code_inspector), ("ambient_guardian", _ambient_guardian),
) if m is not None]
log("[pillars] active: " + (", ".join(_READY) if _READY
                             else "none (plain chat brain)"))


# ─── Startup: background subsystems (bus, screen recorder, guardian) ─────────
_swarm_started = False


def init_background(speak_fn=None, loop=None):
    """Bring up always-on background pillars once. Safe, non-blocking.

    speak_fn: the mouth's say(). The guardian NEEDS it — without a speak
              callback its proactive alerts queue in the bus and are
              never voiced (this connection was missing when the brain
              moved into backtalk).
    loop:     the running asyncio loop. P3's swarm_worker_loop is a
              coroutine and nothing else schedules it, so without this
              every dispatched audit/synthesis/web task would sit
              'pending' forever.

    Each subsystem starts its own daemon thread. A failure in any one is
    logged and swallowed so the voice line still comes up.
    """
    global _swarm_started
    if _subagent_swarm is not None:
        try:
            _subagent_swarm.init_bus()
        except Exception as e:
            log(f"[pillars] subagent bus init failed: {e!r}")
        if loop is not None and not _swarm_started:
            _swarm_started = True
            try:
                loop.call_soon_threadsafe(_start_swarm_worker, loop)
            except Exception as e:
                _swarm_started = False
                log(f"[pillars] swarm worker schedule failed: {e!r}")
    if _screen_recorder is not None:
        try:
            _screen_recorder.start_daemon()
        except Exception as e:
            log(f"[pillars] screen recorder start failed: {e!r}")
    if _ambient_guardian is not None:
        try:
            _ambient_guardian.start_guardian(speak_fn=speak_fn)
        except Exception as e:
            log(f"[pillars] ambient guardian start failed: {e!r}")


def _start_swarm_worker(loop):
    """Schedule P3's worker loop on the live event loop (loop-thread only)."""
    if _subagent_swarm is None:
        return
    try:
        loop.create_task(_subagent_swarm.swarm_worker_loop())
        log("[pillars] P3 swarm worker loop started")
    except Exception as e:
        log(f"[pillars] swarm worker task failed: {e!r}")


async def announce_subagent_results(speak, interval: float = 4.0):
    """P3: voice every completed background task. Runs for the whole session.

    speak: the mouth's say() (thread-safe queue). poll_subagent_results
    marks each task notified, so nothing is ever said twice.
    """
    if _subagent_swarm is None:
        return
    while True:
        try:
            for line in poll_subagent_results():
                log("[pillars] " + line)
                speak(line)
        except Exception as e:
            log(f"[pillars] subagent announce error: {e!r}")
        await asyncio.sleep(interval)


def reset_idle_timer():
    """P7: call on every user turn to keep the guardian's idle gate fresh."""
    if _ambient_guardian is not None:
        try:
            _ambient_guardian.update_keyboard_activity()
        except Exception:
            pass


# ─── P3: subagent dispatch + result polling ─────────────────────────────────
def dispatch_subagent(task_type, text):
    """Queue a background worker (audit / synthesis / web). Returns task id."""
    if _subagent_swarm is None:
        return None
    try:
        return _subagent_swarm.dispatch_task(task_type, text)
    except Exception as e:
        log(f"[pillars] dispatch_subagent failed: {e!r}")
        return None


def poll_subagent_results():
    """Drain completed background tasks into speakable strings."""
    if _subagent_swarm is None:
        return []
    out = []
    try:
        for task in _subagent_swarm.get_completed_unnotified_tasks():
            tid = task["id"] if isinstance(task, dict) else task[0]
            body = task["result"] if isinstance(task, dict) else task[-1]
            out.append(f"Background task {tid} finished: {body}")
            _subagent_swarm.mark_task_notified(tid)
    except Exception as e:
        log(f"[pillars] poll_subagent failed: {e!r}")
    return out


# ─── P2: [ACTION:...] tag execution (GUI + app control) ─────────────────────
def execute_action_tag(tag):
    """Run a raw '[ACTION: ...]' tag. Returns a speakable result or None.

    Routes to the P2 GUI driver first (click / menu / visual_click / keys),
    then falls back to the classic app-control engine (open / close / type).
    """
    if _pillar_bridge is not None:
        try:
            res = _pillar_bridge.dispatch_p2(tag)
            if res:
                return res
        except Exception as e:
            log(f"[pillars] p2 dispatch failed: {e!r}")
    if _jarvis_actions is not None:
        try:
            return _jarvis_actions.execute_model_action(tag)
        except Exception as e:
            log(f"[pillars] model action failed: {e!r}")
    return None


# ─── P6: selected-code inspection context ───────────────────────────────────
def selected_code_context(text):
    """If code is highlighted and the ask is about it, return a prompt block.

    Returns None when nothing is selected or the utterance is unrelated, so
    the normal LLM path runs untouched.
    """
    if _code_inspector is None:
        return None
    try:
        code = _code_inspector.get_selected_text()
    except Exception:
        return None
    if not code:
        return None
    return (f"The user highlighted this code in their editor:\n"
            f"```\n{code[:1500]}\n```\nUser question: {text}\n"
            f"Explain concisely in a couple of spoken sentences.")


# ─── P4: temporal screen recall ─────────────────────────────────────────────
def temporal_recall(text):
    """Answer 'what was I doing ... earlier' from the OCR screen log."""
    if _screen_recorder is None:
        return None
    try:
        return _screen_recorder.query_temporal_recall(text)
    except Exception as e:
        log(f"[pillars] temporal_recall failed: {e!r}")
        return None


# ─── Vision: what's on screen right now ─────────────────────────────────────
def vision_query(text):
    """Describe the active window / screen. Returns None if vision is down.

    The vision feedback loop: a stored correction for a similar earlier
    query is injected, so a misread the user already corrected is never
    repeated on the same screen.
    """
    if _screen_vision is None:
        return None
    try:
        ans = _screen_vision.analyze_screen(prompt=text)
    except Exception as e:
        log(f"[pillars] vision_query failed: {e!r}")
        return None
    if not ans:
        return None
    prior = learning.recall_correction("vision", text)
    if prior:
        ans = f"{ans}\n(Note: you previously corrected me — {prior})"
    return ans


def record_vision_correction(text, correction):
    """Store the user's correction about what is on screen (feedback loop)."""
    try:
        learning.record_correction("vision", text, correction)
    except Exception as e:
        log(f"[pillars] record_vision_correction failed: {e!r}")


# ─── Obsidian vault context injection ───────────────────────────────────────
def vault_context(text):
    """High-confidence note snippets relevant to the request, or ''."""
    if _obsidian_rag is None:
        return ""
    try:
        return _obsidian_rag.search_vault(text) or ""
    except Exception as e:
        log(f"[pillars] vault_context failed: {e!r}")
        return ""


# ─── The router: one call before the LLM ────────────────────────────────────
# Keyword sets, verbatim from always_online_jarvis.main_loop so behavior
# is identical whether the turn arrives by voice, typed, or the old brain.
_CODE_TRIGGERS = ("highlighted code", "selected code", "explain this code",
                  "explain this selection", "explain this", "what is this code")
_AUDIT_TRIGGERS = ("audit the code", "audit my code", "audit code",
                   "security audit")
_SYNTH_TRIGGERS = ("synthesize my vault", "synthesize vault",
                   "synthesize notes")
_WEB_TRIGGERS = ("scout web", "check url", "fetch url", "web research",
                 "scout url")
_VISION_TRIGGERS = ("what do you see", "see my screen", "on my screen",
                    "which app", "see antigravity", "see the id", "see id")
_RECALL_TRIGGERS = ("what was i", "what were you", "recall", "remember",
                    "an hour ago", "hours ago", "minutes ago", "this morning",
                    "earlier today", "before lunch", "yesterday")


def route(text):
    """Decide how to answer an utterance. Returns (speak, context).

    speak    -> say this verbatim, skip the LLM.
    context  -> inject into the LLM prompt, then stream the model reply.
    Neither  -> plain LLM turn.

    Order matches the old brain: code inspect, subagent dispatch, vision,
    temporal recall, direct action — then vault context for the LLM path.
    """
    clean = (text or "").strip().lower()
    if not clean:
        return None, None
    reset_idle_timer()

    # P6 — selected-code inspection (context, not a direct answer).
    if any(w in clean for w in _CODE_TRIGGERS):
        ctx = selected_code_context(text)
        if ctx:
            return None, ctx

    # P3 — subagent delegation (fire-and-forget, speak the confirmation).
    if any(w in clean for w in _AUDIT_TRIGGERS):
        tid = dispatch_subagent("audit", text)
        if tid is not None:
            return "Dispatching code audit to background subagent. I'll alert you when it completes.", None
    if any(w in clean for w in _SYNTH_TRIGGERS):
        tid = dispatch_subagent("synthesis", text)
        if tid is not None:
            return "Subagent researching your second brain. Continuing to listen.", None
    if any(w in clean for w in _WEB_TRIGGERS):
        tid = dispatch_subagent("web", text)
        if tid is not None:
            return "Web scout subagent dispatched. I will report back shortly.", None

    # Vision — what's on screen right now.
    if any(w in clean for w in _VISION_TRIGGERS):
        vis = vision_query(text)
        if vis:
            return vis, None

    # P4 — temporal screen recall.
    if any(w in clean for w in _RECALL_TRIGGERS):
        recall = temporal_recall(text)
        if recall:
            return recall, None

    # P1/P2 — fast direct action + dynamic skill fallback.
    act = direct_action(text)
    if act:
        return act, None

    # Nothing matched a local answer: enrich with vault context and let
    # the LLM stream.
    vc = vault_context(text)
    if vc:
        return None, ("Relevant notes from the user's second brain:\n"
                      f"{vc}\n\nAnswer the user's request: {text}")
    return None, None


def direct_action(text):
    """Fast local intents that need no LLM. Speakable string or None."""
    if _jarvis_actions is None:
        return None
    try:
        return _jarvis_actions.parse_and_execute_intent(text)
    except Exception as e:
        log(f"[pillars] direct_action failed: {e!r}")
        return None