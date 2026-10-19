# backtalk: talk to your local AI agent out loud.
# Copyright (C) 2026 oscpbunny
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The self-learning layer - Phase 2 of the unified brain.

Three real feedback loops, all local and durable:

1. Preference memory   - what the user likes, injected into every prompt so
                         the brain gets more personal with use.
2. Outcome reinforcement - every turn is scored (completed / interrupted /
                         corrected). A rising interruption rate means replies
                         are too long or off-target, so a brevity hint is
                         injected until it drops again.
3. Correction recall    - "no, actually the window is X" is stored and
                         recalled the next time a similar query arrives, so
                         the same misunderstanding is never repeated.

On top of that, a gesture self-tuner accumulates accept/reject telemetry
and computes an optimal detection threshold per gesture (Youden's J), ready
to be fed by the barehands client.

Everything is backed by one append-only JSONL replayed on load, so state
survives restarts and is safe to touch from any process. A single lock makes
it safe across the async brain and the thread-pooled pillar router.
"""
import json
import threading
import time
from pathlib import Path

# Same repo root jarvis_memory.jsonl lives in (backtalk/backtalk/learning.py
# -> three parents up).
LEARNING_PATH = Path(__file__).resolve().parent.parent.parent / "jarvis_learning.jsonl"

_lock = threading.RLock()
_events: list[dict] = []          # every event, in arrival order (replay log)

_prefs: dict[str, str] = {}       # key -> latest value (latest pref event wins)
_corrections: list[dict] = []     # domain -> query -> correction, in order
_turns: dict[str, dict] = {}      # id -> turn record (outcome events merged in)
_gestures: dict[str, list] = {}   # name -> [(confidence, accepted), ...]

_loaded = False


def _load():
    """Replay the JSONL into the in-memory aggregates. Idempotent."""
    global _loaded, _events
    if _loaded:
        return
    with _lock:
        _events = []
        if LEARNING_PATH.exists():
            for line in LEARNING_PATH.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                _events.append(ev)
                _apply(ev)
        _loaded = True


def _apply(ev: dict):
    """Fold one event into the aggregates. Caller holds the lock."""
    e = ev.get("e")
    if e == "pref":
        _prefs[ev["key"]] = ev["value"]
    elif e == "correction":
        _corrections.append(ev)
    elif e == "turn":
        _turns[ev["id"]] = dict(ev)
    elif e == "turn_outcome":
        t = _turns.get(ev["id"])
        if t is not None:
            t["outcome"] = ev["outcome"]
            if "reply" in ev:
                t["reply"] = ev["reply"]
            if "latency_ms" in ev:
                t["latency_ms"] = ev["latency_ms"]
    elif e == "gesture":
        _gestures.setdefault(ev["name"], []).append(
            (float(ev["confidence"]), bool(ev["accepted"])))


def _append(ev: dict):
    """Persist one event and fold it in."""
    _load()
    with _lock:
        _events.append(ev)
        _apply(ev)
        try:
            LEARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LEARNING_PATH, "a") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception:
            # Learning must never take the voice line down.
            pass


# ── Preferences ──────────────────────────────────────────────────────────

def set_preference(key: str, value: str):
    """Remember a durable user preference (latest value wins)."""
    key = str(key).strip().lower()
    if not key:
        return
    _append({"e": "pref", "key": key, "value": str(value).strip(),
             "ts": time.time()})


def preferences() -> dict:
    _load()
    with _lock:
        return dict(_prefs)


def preferences_block() -> str:
    """A prompt fragment listing known preferences, or '' if none."""
    prefs = preferences()
    if not prefs:
        return ""
    lines = "\n".join(f"- {k}: {v}" for k, v in sorted(prefs.items()))
    return ("\n\nKnown preferences of the user (honour these):\n" + lines)


# ── Turn outcome reinforcement ───────────────────────────────────────────

def begin_turn(utterance: str, route: str) -> str:
    """Register the turn now streaming. Returns its id.

    route: which path answered - 'direct' (a pillar answered without the
    LLM), 'llm+ctx' (LLM with pillar context), or 'llm' (plain chat).
    """
    _load()
    tid = f"{int(time.time() * 1000)}-{len(_turns) & 0xffff:04x}"
    rec = {"id": tid, "ts": time.time(), "utterance": (utterance or "")[:400],
           "route": route, "outcome": "pending", "reply": "", "latency_ms": 0}
    _append({"e": "turn", **rec})
    return tid


def complete_turn(tid: str, reply: str, latency_ms: int):
    """The stream finished on its own - a positive outcome."""
    _append({"e": "turn_outcome", "id": tid, "outcome": "completed",
             "reply": (reply or "")[:400], "latency_ms": int(latency_ms)})


def interrupt_turn(tid: str | None):
    """The user cut the reply off - a negative outcome."""
    if not tid:
        return
    _append({"e": "turn_outcome", "id": tid, "outcome": "interrupted"})


def mark_corrected(tid: str | None):
    """The user followed up correcting the last reply - negative + reusable."""
    if not tid:
        return
    _append({"e": "turn_outcome", "id": tid, "outcome": "corrected"})


def outcome_stats(window: int = 50) -> dict:
    """Completion / interruption / correction rates over recent turns."""
    _load()
    with _lock:
        turns = [t for t in _turns.values()
                 if t.get("outcome") in ("completed", "interrupted",
                                         "corrected")]
        turns.sort(key=lambda t: t.get("ts", 0))
        turns = turns[-window:]
    total = len(turns)
    if not total:
        return {"total": 0, "completed": 0, "interrupted": 0,
                "corrected": 0, "interrupt_rate": 0.0, "correct_rate": 0.0}
    completed = sum(1 for t in turns if t["outcome"] == "completed")
    interrupted = sum(1 for t in turns if t["outcome"] == "interrupted")
    corrected = sum(1 for t in turns if t["outcome"] == "corrected")
    return {"total": total, "completed": completed,
            "interrupted": interrupted, "corrected": corrected,
            "interrupt_rate": round(interrupted / total, 3),
            "correct_rate": round(corrected / total, 3)}


def brevity_hint() -> str:
    """Inject a concision nudge when recent turns keep getting cut off.

    Needs a little history to avoid flapping, and stops nagging once the
    rate falls back under the threshold.
    """
    s = outcome_stats()
    if s["total"] >= 6 and s["interrupt_rate"] > 0.34:
        return ("\n\nThe user has been cutting recent replies off. "
                "Lead with the direct answer in one or two sentences, "
                "then stop - do not volunteer detail they did not ask for.")
    return ""


# ── Correction recall (vision feedback loop) ─────────────────────────────

def record_correction(domain: str, query: str, correction: str):
    """Store a user correction so the same misunderstanding is not repeated."""
    _append({"e": "correction", "domain": domain or "general",
             "query": (query or "")[:300],
             "correction": (correction or "")[:400], "ts": time.time()})


def _tok(s: str) -> set:
    return {w for w in "".join(
        c.lower() if c.isalnum() else " " for c in (s or "")).split()
        if len(w) > 2}


def recall_correction(domain: str, query: str, min_overlap: float = 0.5):
    """Best stored correction for this query, or None.

    Fuzzy: picks the correction whose stored query shares the most content
    words with the incoming one, provided at least min_overlap of the
    incoming query's words are covered.
    """
    _load()
    with _lock:
        cands = [c for c in _corrections
                 if (c.get("domain") or "general") == (domain or "general")]
    if not cands:
        return None
    q = _tok(query)
    if not q:
        return None
    best, best_score = None, 0.0
    for c in cands:
        ct = _tok(c.get("query", ""))
        if not ct:
            continue
        score = len(q & ct) / len(q)
        if score > best_score:
            best, best_score = c, score
    if best is not None and best_score >= min_overlap:
        return best.get("correction", "") or None
    return None


# ── Gesture self-tuning ──────────────────────────────────────────────────

def record_gesture(name: str, confidence: float, accepted: bool):
    """Feed one gesture sample. Called by the tracker / barehands client."""
    if not name:
        return
    _append({"e": "gesture", "name": str(name).lower(),
             "confidence": float(confidence), "accepted": bool(accepted),
             "ts": time.time()})


def _tuned_threshold(samples: list) -> float | None:
    """Optimal accept/reject threshold maximising Youden's J (TPR - FPR).

    Returns None until both classes are observed.
    """
    if not samples or len(samples) < 6:
        return None
    pos = [c for c, ok in samples if ok]
    neg = [c for c, ok in samples if not ok]
    if not pos or not neg:
        return None
    cands = sorted({c for c, _ in samples})
    best_t, best_j = None, -1.0
    for t in cands:
        tpr = sum(1 for c in pos if c >= t) / len(pos)
        fpr = sum(1 for c in neg if c >= t) / len(neg)
        j = tpr - fpr
        if j > best_j:
            best_t, best_j = t, j
    return round(best_t, 3) if best_t is not None else None


def tuned_threshold(name: str) -> float | None:
    """The current optimal threshold for a gesture ('' until enough data)."""
    _load()
    with _lock:
        samples = list(_gestures.get(str(name).lower(), []))
    return _tuned_threshold(samples)


def gesture_report() -> dict:
    """Per-gesture sample count, accept rate, and tuned threshold."""
    _load()
    with _lock:
        snap = {k: list(v) for k, v in _gestures.items()}
    out = {}
    for name, samples in snap.items():
        n = len(samples)
        acc = (sum(1 for _, ok in samples if ok) / n) if n else 0.0
        out[name] = {"n": n, "accept_rate": round(acc, 3),
                     "threshold": _tuned_threshold(samples)}
    return out


# ── Reporting ────────────────────────────────────────────────────────────

def stats() -> dict:
    _load()
    with _lock:
        n_corr = len(_corrections)
        n_prefs = len(_prefs)
    s = outcome_stats()
    s["preferences"] = n_prefs
    s["corrections"] = n_corr
    s["gestures"] = len(gesture_report())
    return s


def spoken_summary() -> str:
    """A one-breath line for the voice console."""
    s = stats()
    if s["total"] == 0:
        return ("Learning layer is live but has no turns yet. "
                "I start scoring replies as soon as we talk.")
    return (f"Across {s['total']} recent turns I kept {s['completed']}, "
            f"was cut off {s['interrupted']}, corrected {s['corrected']}. "
            f"I know {s['preferences']} preferences and "
            f"{s['corrections']} corrections.")

