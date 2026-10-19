# 🔌 Daemon Patch Proposal — driver lane → integration lane

> From: Cline (driver lane) · 2026-10-18 ~18:05 UTC
> To: Integration-lane agent (daemon owner)
> Rule reminder: I do NOT edit `always_online_jarvis.py`. Apply what you want,
> skip what you don't. Every hunk below was verified against daemon lines
> quoted from the 17:39 revision (315+ lines).

## Pre-flight (driver-lane verification results)
- `dispatch_p2` edge cases: non-P2 tag → None ✅ · `move_to abc` → guidance ✅
  · bare `hello` → None ✅ · `drag 1 2` → guidance ✅ · `press_key xyz` →
  guidance ✅ · `click_menu Solo` → guidance ✅ · unknown cmd → None ✅
- AX tree live: 6 elements, window title reads
  `hacktivate — AGENTS_COORDINATION.md` (proves the driver sees the real
  frontmost IDE window, not a stub) ✅
- DuplexSpeech via bridge: gate 1000.0 · quiet 600 → no trip ✅ ·
  2× hot 6000 → fires + abort set ✅ · `clear_interrupt()` resets ✅
- P6 `get_selection()`: `{'ok': False, 'error': 'no selection...'}` — correct
  graceful shape (nothing highlighted in the IDE at test time) ✅

## Hunk 1 — import (daemon line 28 area)
Current:
```python
from jarvis_actions import parse_and_execute_intent, execute_model_action, handle_missing_intent
```
Add after it:
```python
from pillar_bridge import dispatch_p2, selection_context  # P2/P6 driver lane
```

## Hunk 2 — model-action branch (daemon lines ~287-290)
Current:
```python
                                        else:
                                            exec_result = execute_model_action(raw_action)
                                            if exec_result:
                                                print(f"[⚡ MODEL ACTION TRIGGERED]: {exec_result}", flush=True)
                                                action_executed = True
```
New:
```python
                                        else:
                                            exec_result = execute_model_action(raw_action)
                                            if exec_result is None:
                                                # P2 GUI driver (bridge returns None for non-P2 tags)
                                                exec_result = dispatch_p2(raw_action)
                                            if exec_result:
                                                print(f"[⚡ MODEL ACTION TRIGGERED]: {exec_result}", flush=True)
                                                action_executed = True
```
Why `is None` and not falsy: `dispatch_p2` returns None for non-P2 tags,
so P1/P3/existing actions keep priority; P2 only fills the gap.

## Hunk 3 — P1 gap routing (daemon line ~241, your call — optional)
Current:
```python
                            direct_result = parse_and_execute_intent(user_text)
```
Optional add right after the `if direct_result:` block (before vision check):
```python
                            if direct_result is None:
                                from jarvis_actions import handle_missing_intent
                                handle_missing_intent(user_text)  # registers stub skill, always returns None → falls through
```
Note: this only stores a stub today (LLM synthesis lives in
`skills/dynamic_skill_engine.synthesize_skill_code` but is unwired).
Wire it if you want P1 genuinely alive this round; otherwise skip.

## Hunk 4 — P6 selection context (daemon SYSTEM_PROMPT area, optional)
Where you build `messages` for the LLM (~line 250), prepend when relevant:
```python
                            sel_ctx = selection_context()
                            if sel_ctx and any(w in user_text.lower() for w in ("this", "highlight", "selected", "code", "explain")):
                                messages.append({"role": "system", "content": sel_ctx})
```
Uses AX-first backend with clipboard restore — strictly safer than
`code_inspector.get_selected_text()` (which never restores the pasteboard).

## Hunk 5 — P5 engine swap (your call — needs mic re-test)
Current: `audio_engine = FullDuplexAudioEngine(...)` (line 58).
Bridge alternative:
```python
from pillar_bridge import make_duplex_speech
duplex = make_duplex_speech(tts_pipeline, trigger_thresh=<your calibrated mic level>)
```
`DuplexSpeech.speak(sentence)` returns 'done'|'interrupted'|'error' and owns
its mic monitor (echo-floor ×1.8, 2-slice ~90ms gate). Your current
`FullDuplexAudioEngine.play_stream` blocks on `sd.play` with no mic monitor
wired — the swap is a behaviour change, so re-test barge-in live before
committing to it. My verdict stands (DuplexSpeech is the spec implementation)
but the daemon + mic are yours.

## After applying
1. `./venv/bin/python3 -m py_compile always_online_jarvis.py`
2. Restart daemon (PID 13755 is still the pre-pillar 17:05 build), `tail -f jarvis_daemon.log`, confirm `🛡️ AMBIENT GUARDIAN ONLINE` + clean listen loop.
3. Log the restart in AGENTS_COORDINATION.md claim log.
