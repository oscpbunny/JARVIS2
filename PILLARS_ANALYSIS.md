# 🏛️ Seven Pillars — Implementation Analysis

> **Analysed:** 2026-10-18 · **Machine:** Apple Silicon M3 Pro, 18 GB · **Daemon:** `always_online_jarvis.py`
> **Method:** every module read line-by-line, compiled, and live-tested on this machine
> (CGEvent posting, AX trees, System Events selection capture, Ollama embeddings, SQLite bus round-trip).

---

## ⚠️ Headline finding: two parallel implementations, one broken merge

The directory contains **two interleaved pillar implementations written by two different
sessions** (file mtimes prove it — 16:59–17:27, interleaved minute-by-minute):

| Pillar | Set A — "spec-faithful" (17:11–17:24) | Set B — "minimal" (16:59–17:27) | Which the daemon imports |
|---|---|---|---|
| P1 Skill engine | — | `skills/dynamic_skill_engine.py` | B *(imported but never called)* |
| P2 GUI computer-use | `mac_input_driver.py` (20.9 KB, live-tested) | — | **neither — P2 is wired to nothing** |
| P3 Subagent swarm | `subagent_pool.py` (3-worker asyncio pool) | `subagent_swarm.py` (1 worker) | B |
| P4 Screen recall | `screen_recall.py` (**incomplete** — only the time parser exists) | `screen_recorder.py` (screencapture+swift-CLI OCR) | B |
| P5 Barge-in | `speech_duplex.py` (mic-monitor thread + echo floor) | `voice_bargein.py` (`sd.stop()`) | B |
| P6 Code inspector | `ax_selected_text.py` (AX-first, clipboard restore) | `code_inspector.py` (33 lines, clipboard only) | B |
| P7 Guardian | — | `ambient_guardian.py` (347 lines) | B |

The daemon (`always_online_jarvis.py`, 315 lines) wires **only Set B**, its boot banner
claims "ALL 7 PILLARS ONLINE ✅" for all seven — but **P2 is imported by nothing** and
**P1's entry point has zero call sites**. Worse: the **running process (PID 13755) started
at 17:05:47, before `screen_recorder.py` (17:25), `ambient_guardian.py` (17:26) and the
integrated daemon file itself (17:27) existed** — so the 7-pillar build has *never actually
run*. The live log shows only the bare listen loop.

---

## Pillar 1 — Self-Evolving Skill Engine · ❌ DEAD CODE

**Spec:** detect capability gap → LLM synthesises typed, idempotent `execute_skill(args)`
→ `py_compile` + sandboxed subshell verification → `importlib` hot-reload → Obsidian
manifest in `jarvis-skills/` with `#jarvis/skill #autonomous`.

**What exists:** `skills/dynamic_skill_engine.py` (64 lines) has honest plumbing —
`generate_skill()` writes `skills/dynamic_<name>.py`, `validate_skill()` does
`py_compile` + sandboxed import, `hot_reload()` uses `importlib`. `jarvis_actions.handle_missing_intent()`
generates a skill file per unknown intent.

**Why it's dead:**
1. **Zero call sites.** `always_online_jarvis.py` imports `handle_missing_intent` (line 28)
   but never invokes it anywhere in the 315-line daemon.
2. **No LLM synthesis.** `handle_missing_intent` writes a *hardcoded stub* —
   `return {'status':'executed','message':'Stub for: …'}`. Nothing is generated; the
   "skill" can never perform the requested task. The spec's core (capability synthesis
   from the code model) is absent.
3. **No capability-gap detection, no skill registry/router** that routes future intents
   to previously registered skills, no Obsidian manifesting, no session-salted anything.
4. Minor: skill names are the whole utterance truncated to 30 chars (`"convert_webp_i…"`),
   colliding and unreadable.

**Verdict:** scaffold exists; the pillar itself is not implemented. Needs: an LLM
synthesis loop, real gap detection (route-through on `parse_and_execute_intent` → None),
a registry consulted at intent time, a `skills/manifest.json`, and vault manifesting.
