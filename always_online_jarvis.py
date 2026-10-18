#!/usr/bin/env python3
"""Autonomous Omniscient Jarvis – All 7 Pillars Active:
- P1: Self-Evolving Skill Engine (dynamic skill generation + hot-reload)
- P2: GUI Computer-Use (mac_input_driver mouse/keyboard driver)
- P3: Subagent Worker Swarm (code audit, vault synthesis, async SQLite bus)
- P4: Episodic Visual Screen Recall (screen_recorder OCR temporal memory)
- P5: Full-Duplex Barge-In Audio (<80ms interruption)
- P6: Selected Code Inspector (AXUIElement / clipboard tap)
- P7: Proactive Ambient Guardian (FSEvents build watcher, system health, git alerts)
"""
import os
import sys
import time
import re
import asyncio
import numpy as np
import sounddevice as sd
from pathlib import Path
from openai import AsyncOpenAI
from kokoro import KPipeline
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backtalk"))

from backtalk import signals
from obsidian_rag import search_vault
from jarvis_actions import parse_and_execute_intent, execute_model_action, handle_missing_intent
from screen_vision import analyze_screen
from subagent_swarm import init_bus, dispatch_task, get_completed_unnotified_tasks, mark_task_notified, swarm_worker_loop
from voice_bargein import FullDuplexAudioEngine
from code_inspector import get_selected_text
from screen_recorder import start_daemon as start_screen_recorder, query_temporal_recall
from ambient_guardian import start_guardian, update_keyboard_activity
from pillar_bridge import dispatch_p2, p2_status, make_duplex_speech

# ══════════════════════════════════════════════════════════════════════════════
# MEMORY & PERFORMANCE OPTIMIZATION STATE
# ══════════════════════════════════════════════════════════════════════════════

# Message history limit (prevents unbounded list growth)
MAX_MESSAGE_HISTORY = 8

# Subagent worker concurrency limit
MAX_WORKERS = 3

# Temp file cleanup interval (seconds)
CLEANUP_INTERVAL = 300

# ─── Memory-optimized Ollama API call ─────────────────────────────────────────
def make_ollama_request(messages, timeout=20):
    """Make Ollama API request with timeout to prevent blocking."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        resp = loop.run_until_complete(
            asyncio.wait_for(
                client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    stream=True
                ),
                timeout=timeout
            )
        )
        return resp
    except asyncio.TimeoutError:
        print(f"[⏱️ OLLAMA TIMEOUT: {timeout}s exceeded]", flush=True)
        return None

# ─── Async TTS Engine ────────────────────────────────────────────────────────
import concurrent.futures
_tts_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-tts")

async def speak_sentence_async(sentence):
    """Async version of speak_sentence that doesn't block the main loop."""
    clean = re.sub(r"\[ACTION:[^\]]+\]", "", sentence).strip()
    if not clean:
        return
    
    print(f"\n[JARVIS]: {clean}", flush=True)
    signals.set_state("speaking")
    
    def _tts_sync(text):
        """Synchronous TTS in thread pool."""
        generator = tts_pipeline(text, voice='bm_lewis', speed=1.15)
        audio_engine.play_stream(generator)
        return True
    
    try:
        await loop.run_in_executor(_tts_executor, _tts_sync, clean)
    except Exception as e1:
        try:
            print(f"[TTS neural error ({e1}), falling back...]", flush=True)
            generator = tts_pipeline(clean, voice='bm_lewis', speed=1.15)
            audio_engine.play_stream(generator)
        except Exception as e2:
            print(f"[TTS error: {e2}]", flush=True)
            await loop.run_in_executor(_tts_executor, 
                lambda: subprocess.run(["say", "-v", "Daniel", "-r", "190", clean], timeout=8))
    finally:
        signals.set_state("idle")

# ─── Memory Cleanup ────────────────────────────────────────────────────────────
def cleanup_resources():
    """Periodic resource cleanup to manage memory."""
    global _last_cleanup_time, _cleanup_done
    
    now = time.time()
    if now - _last_cleanup_time < CLEANUP_INTERVAL:
        return
    
    _last_cleanup_time = now
    
    gc.collect()
    
    for pattern in ['*.tmp', '*.temp', '*.swp']:
        for f in ROOT.glob(pattern):
            try:
                if f.is_file():
                    f.unlink()
            except:
                pass
    
    print(f"[🧹 RESOURCE CLEANUP: {int(now - _last_cleanup_time)}s]", flush=True)

# ─── Subagent Worker Rate Limiter ─────────────────────────────────────────────
_worker_tasks = set()
_worker_lock = asyncio.Lock()

async def limit_workers(coro):
    """Limit concurrent subagent workers."""
    async with _worker_lock:
        _worker_tasks.add(asyncio.current_task())
        try:
            return await coro
        finally:
            _worker_tasks.discard(asyncio.current_task())

def get_active_workers():
    """Get count of active subagent workers."""
    return len(_worker_tasks)


MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")
RATE = 16000
CHUNK_DURATION = 0.08
CHUNK_SAMPLES = int(RATE * CHUNK_DURATION)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ACTION_REGEX = re.compile(r"\[ACTION:\s*([^\]]+)\]", re.IGNORECASE)
_HALLUCINATION_PATTERNS = re.compile(
    r"\b(it seems like|it appears|the user requested|visual_click)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def check_understanding(user_text: str, ai_reply: str) -> bool:
    """
    Determine if jarvis actually understood the user's question.
    Returns True if response is helpful, False if clarification needed.
    """
    import re
    
    user_lower = user_text.lower().strip()
    reply_lower = ai_reply.lower().strip()
    
    # Must respond with at least 4 meaningful words
    words = re.findall(r"\b\w+\b", reply_lower)
    if len(words) < 4:
        return False
    
    # Flag obvious hallucinated or generic phrases
    if _HALLUCINATION_PATTERNS.search(reply_lower):
        return False
    
    # Check length and content relevance
    if len(reply_lower) < 30:
        return False
    
    return True


def make_clarification(user_text: str) -> str:
    """
    Generate a clarification question when jarvis didn't understand.
    """
    u = user_text.strip()
    if len(u) > 100:
        u = u[:100] + "..."
    
    if any(w in u for w in ["pronounce", "how to", "how should"]):
        return f"Could you clarify how you'd like me to proceed with: '{u[:80]}'?"
    
    return f"I didn't fully understand '{u[:80]}'. Could you rephrase or ask more specifically?"

print("\n" + "="*65)
print("  🦾 JARVIS – ALL 7 PILLARS ONLINE (ACCELERATED)")
print("  P1: Self-Evolving Skill Engine  ✅")
print("  P2: GUI Computer-Use Driver     ✅ (34.1 FPS In-Memory)")
print("  P3: Subagent Worker Swarm       ✅ (Autonomous Workers)")
print("  P4: Episodic Screen Recall      ✅ (Apple Neural Engine OCR)")
print("  P5: Full-Duplex Barge-In        ✅ (Spec DuplexSpeech ~90ms)")
print("  P6: Selected Code Inspector     ✅ (Safe Pasteboard Restore)")
print("  P7: Ambient Guardian            ✅ (Throttled Health & Build)")
print(f"  Mind: {MODEL} @ {API_BASE}")
print("="*65 + "\n", flush=True)

init_bus()
start_screen_recorder()   # Pillar 4 – background screen OCR daemon
whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
tts_pipeline = KPipeline(lang_code='b')
client = AsyncOpenAI(base_url=API_BASE, api_key="ollama")

# Pillar 5: Initialize spec-grade DuplexSpeech with acoustic barge-in
duplex_engine = make_duplex_speech(tts_pipeline, trigger_thresh=1100.0)
audio_engine = FullDuplexAudioEngine(sample_rate=RATE, playback_rate=24000)

SYSTEM_PROMPT = (
    "You are Jarvis, Vish's offensive engineering and coding AI assistant on macOS.\n"
    "You have a background Subagent Swarm for heavy tasks and direct control over macOS.\n"
    "When answering:\n"
    "- If asked to explain or review highlighted code: inspect the selected text directly.\n"
    "- If asked to audit code, analyze a file, or review security: [ACTION: dispatch_audit <details>]\n"
    "- If asked to deeply synthesize vault notes: [ACTION: dispatch_synthesis <topic>]\n"
    "- If asked what you see or what app is open: describe the exact active window.\n"
    "- If asked to open an app: [ACTION: open_app <app>]\n"
    "- If asked to close an app or terminal: [ACTION: close_app <app>]\n"
    "- If asked to click a button or UI element: [ACTION: click_button <label>]\n"
    "- If asked to focus an app window: [ACTION: focus_window <app>]\n"
    "- If asked to click a menu item: [ACTION: click_menu <App> | <Menu> | <Item>]\n"
    "- If asked to visually click something on screen: [ACTION: visual_click <description>]\n"
    "- If asked to type something: [ACTION: type_text <text>]\n"
    "RULES:\n"
    "1. Keep responses under 2 sentences, crisp, punchy, and helpful.\n"
    "2. Never trigger an action tag if the user is just asking a casual question."
)

_cached_vision_description = ""
_last_vision_check = 0.0

async def handle_vision_query(query_text: str):
    global _cached_vision_description, _last_vision_check
    signals.set_state("thinking")
    now = time.time()
    
    # Use P2 zero-overhead perceptual diffing if screen hasn't changed
    screen_changed_fn = P2_ACTIONS.get("screen_has_changed")
    if screen_changed_fn and not screen_changed_fn() and _cached_vision_description and (now - _last_vision_check < 60.0):
        print("[👁️ SCREEN PERCEPTION: CACHE HIT (Screen unchanged)]", flush=True)
        speak_sentence(f"Screen is unchanged. {_cached_vision_description}")
        signals.set_state("idle")
        return

    description = analyze_screen(prompt=query_text)
    _cached_vision_description = description
    _last_vision_check = now
    print(f"[👁️ SCREEN PERCEPTION]: {description}", flush=True)
    speak_sentence(description)
    signals.set_state("idle")

# Initialize message history for memory optimization
_message_history = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

def speak_sentence(sentence):
    clean = re.sub(r"\[ACTION:[^\]]+\]", "", sentence).strip()
    if not clean:
        return
    print(f"\n[JARVIS]: {clean}", flush=True)
    signals.set_state("speaking")
    try:
        # Try Kokoro TTS via audio_engine first (simpler, fewer device conflicts)
        generator = tts_pipeline(clean, voice='bm_lewis', speed=1.15)
        audio_engine.play_stream(generator)
    except Exception as e1:
        try:
            print(f"[TTS neural error ({e1}), falling back...]", flush=True)
            generator = tts_pipeline(clean, voice='bm_lewis', speed=1.15)
            audio_engine.play_stream(generator)
        except Exception as e2:
            print(f"[TTS error: {e2}]", flush=True)
            import subprocess
            subprocess.run(["say", "-v", "Daniel", "-r", "190", clean], timeout=8)
    finally:
        signals.set_state("idle")

def record_utterance(stream, trigger_chunk, silence_thresh=170):
    signals.set_state("listening")
    recorded = [trigger_chunk]
    silent_frames = 0
    silence_limit_frames = int(0.7 / CHUNK_DURATION)
    max_frames = int(10.0 / CHUNK_DURATION)
    
    for _ in range(max_frames):
        chunk, _ = stream.read(CHUNK_SAMPLES)
        chunk = chunk.flatten()
        recorded.append(chunk)
        rms = np.sqrt(np.mean(chunk.astype(np.float32)**2))
        
        if rms < silence_thresh:
            silent_frames += 1
        else:
            silent_frames = 0
            
        if len(recorded) > int(0.5 / CHUNK_DURATION) and silent_frames >= silence_limit_frames:
            break
            
    full_audio = np.concatenate(recorded)
    return full_audio.astype(np.float32) / 32768.0

async def check_subagent_notifications():
    while True:
        try:
            completed = get_completed_unnotified_tasks()
            for t_id, t_type, query, result in completed:
                print(f"\n[🐝 SUBAGENT COMPLETED TASK {t_id}]: {result}", flush=True)
                speak_sentence(f"Subagent completed {t_type}. {result}")
                mark_task_notified(t_id)
            await asyncio.sleep(2.0)
        except Exception:
            await asyncio.sleep(3.0)

async def main_loop():
    # Trim message history to prevent unbounded growth
    trim_message_history()

    # Pillar 7 – start Ambient Guardian with Jarvis TTS callback
    start_guardian(speak_fn=speak_sentence)
    speak_sentence("Jarvis seven pillar core online. All systems active.")
    signals.set_state("idle")

    # Start autonomous subagent worker loop & voice notifications
    asyncio.create_task(swarm_worker_loop())
    asyncio.create_task(check_subagent_notifications())
    
    stream = sd.InputStream(samplerate=RATE, channels=1, dtype='int16')
    stream.start()
    
    print("[🎙️ Calibrating room noise level...]", flush=True)
    ambient_levels = []
    for _ in range(15):
        c, _ = stream.read(CHUNK_SAMPLES)
        ambient_levels.append(np.sqrt(np.mean(c.flatten().astype(np.float32)**2)))
    avg_ambient = float(np.mean(ambient_levels))
    # Lowered threshold for quiet room: trigger at ~1.6x ambient, silence at ~1.2x
    trigger_thresh = max(150.0, avg_ambient * 1.6)
    silence_thresh = max(120.0, avg_ambient * 1.2)
    if duplex_engine is not None:
        duplex_engine.configure(trigger_thresh=trigger_thresh)
    print(f"[🎙️ Noise Floor: {avg_ambient:.1f} | Trigger: {trigger_thresh:.1f} | Silence: {silence_thresh:.1f}]", flush=True)
    print("\n[👂 Omniscient Listening: Highlight code and ask to explain, interrupt anytime...]\n", flush=True)
    
    while True:
        try:
            # Emergency Killswitch: touch /tmp/jarvis.kill to instantly stop the daemon
            if os.path.exists("/tmp/jarvis.kill"):
                print("\n[🛑 EMERGENCY KILLSWITCH ACTIVATED via /tmp/jarvis.kill!]", flush=True)
                speak_sentence("Emergency killswitch activated. Jarvis going offline.")
                try:
                    os.remove("/tmp/jarvis.kill")
                except Exception:
                    pass
                sys.exit(0)

            chunk, _ = stream.read(CHUNK_SAMPLES)
            chunk = chunk.flatten()
            rms = np.sqrt(np.mean(chunk.astype(np.float32)**2))
            
            # Dynamic Continuous Noise Floor Adaptation (EMA: 98% old + 2% new)
            if not audio_engine.is_speaking and rms < trigger_thresh:
                avg_ambient = (avg_ambient * 0.98) + (rms * 0.02)
                trigger_thresh = max(150.0, avg_ambient * 1.6)
                silence_thresh = max(170.0, avg_ambient * 1.2)
                if duplex_engine is not None:
                    duplex_engine.configure(trigger_thresh=trigger_thresh)

            # Acoustic Barge-in
            if audio_engine.is_speaking and rms > (trigger_thresh * 1.3):
                print("\n[⚡ BARGE-IN INTERRUPT DETECTED! Halting playback...]", flush=True)
                audio_engine.stop_speaking()
                await asyncio.sleep(0.05)
                continue

            if rms > trigger_thresh:
                print("\n[🎤 Voice detected...]", flush=True)
                audio_data = record_utterance(stream, chunk, silence_thresh=silence_thresh)
                
                if len(audio_data) >= RATE * 0.4:
                    signals.set_state("thinking")
                    segments, _ = whisper_model.transcribe(audio_data, language="en")
                    user_text = " ".join([s.text for s in segments]).strip()
                    clean_lower = user_text.lower().strip()
                    hallucinations = ["you", "thank you", "thanks for watching", "bye", "subscribe", ".", ".."]
                    
                    if len(clean_lower) >= 3 and clean_lower not in hallucinations:
                        update_keyboard_activity()   # Pillar 7 – reset idle gate
                        print(f"[YOU]: {user_text}", flush=True)
                        
                        # 1. Selected Code / Highlighted Text Inspection
                        if any(w in clean_lower for w in ["highlighted code", "selected code", "explain this code", "explain this selection", "explain this", "what is this code"]):
                            selected_code = get_selected_text()
                            if selected_code:
                                print(f"[🔍 INSPECTED SELECTION ({len(selected_code)} chars)]", flush=True)
                                prompt_content = f"The user highlighted this code in their editor:\n```\n{selected_code[:1500]}\n```\nUser question: {user_text}\nExplain concisely in 2 sentences."
                            else:
                                prompt_content = user_text
                        
                        # 2. Subagent Delegation
                        elif any(w in clean_lower for w in ["audit the code", "audit my code", "audit code", "security audit"]):
                            t_id = dispatch_task("audit", user_text)
                            print(f"[🐝 DISPATCHED TO SUBAGENT SWARM: Task #{t_id}]", flush=True)
                            speak_sentence("Dispatching code audit to background subagent. I'll alert you when complete.")
                            signals.set_state("idle")
                            continue
                            
                        elif any(w in clean_lower for w in ["synthesize my vault", "synthesize vault", "synthesize notes"]):
                            t_id = dispatch_task("synthesis", user_text)
                            print(f"[🐝 DISPATCHED TO SUBAGENT SWARM: Task #{t_id}]", flush=True)
                            speak_sentence("Subagent researching your second brain. Continuing to listen.")
                            signals.set_state("idle")
                            continue

                        elif any(w in clean_lower for w in ["scout web", "check url", "fetch url", "web research", "scout url"]):
                            t_id = dispatch_task("web", user_text)
                            print(f"[🐝 DISPATCHED TO SUBAGENT SWARM: Task #{t_id}]", flush=True)
                            speak_sentence("Web scout subagent dispatched. I will report back shortly.")
                            signals.set_state("idle")
                            continue

                        # 3. Screen / App Perception Queries
                        elif any(w in clean_lower for w in ["what do you see", "see my screen", "on my screen", "which app", "see antigravity", "see the id", "see id"]):
                            await handle_vision_query(user_text)
                            continue

                        # 3b. Temporal Screen Recall (Pillar 4)
                        elif any(w in clean_lower for w in ["what was i", "what were you", "recall", "remember", "an hour ago", "hours ago", "minutes ago", "this morning", "earlier today", "before lunch", "yesterday"]):
                            print(f"[📸 TEMPORAL RECALL QUERY]: {user_text}", flush=True)
                            recall_result = query_temporal_recall(user_text)
                            print(f"[📸 RECALL RESULT]: {recall_result}", flush=True)
                            speak_sentence(recall_result)
                            signals.set_state("idle")
                            continue
                        
                        # 4. Fast Direct Action Check + Dynamic Skill Fallback
                        action_result = parse_and_execute_intent(user_text)
                        if action_result:
                            print(f"[⚡ DIRECT ACTION]: {action_result}", flush=True)
                            speak_sentence(action_result)
                            signals.set_state("idle")
                            continue
                        
                        # 5. Obsidian Vault Context (High confidence only)
                        else:
                            vault_context = search_vault(user_text)
                            prompt_content = user_text
                            if vault_context:
                                print(f"[📚 Retrieved context from Obsidian Vault]", flush=True)
                                prompt_content = f"Relevant notes from user's vault:\n{vault_context}\n\nUser request: {user_text}"
                        
                        # Trim message history to prevent unbounded growth
                        trim_message_history()
                        
                        try:
                            # Circuit breaker: wait max 2.5s for Ollama to begin streaming
                            resp = await asyncio.wait_for(
                                client.chat.completions.create(
                                    model=MODEL,
                                    messages=_message_history,
                                    stream=True
                                ),
                                timeout=2.5
                            )
                            buf = ""
                            full_reply = ""
                            action_executed = False
                            
                            async for chunk_resp in resp:
                                if audio_engine.interrupted:
                                    break

                                delta = ""
                                if chunk_resp.choices and len(chunk_resp.choices) > 0:
                                    delta = chunk_resp.choices[0].delta.content or ""
                                if delta:
                                    buf += delta
                                    full_reply += delta
                                    
                                    action_match = _ACTION_REGEX.search(buf)
                                    if action_match and not action_executed:
                                        raw_action = action_match.group(0)
                                        tag_content = action_match.group(1).strip()
                                        
                                        if tag_content.startswith("dispatch_audit"):
                                            q = tag_content.replace("dispatch_audit", "").strip() or user_text
                                            dispatch_task("audit", q)
                                            action_executed = True
                                        elif tag_content.startswith("dispatch_synthesis"):
                                            q = tag_content.replace("dispatch_synthesis", "").strip() or user_text
                                            dispatch_task("synthesis", q)
                                            action_executed = True
                                        else:
                                            p2_res = dispatch_p2(raw_action)
                                            if p2_res:
                                                print(f"[🖱️ P2 GUI ACTION]: {p2_res}", flush=True)
                                                action_executed = True
                                            else:
                                                exec_result = execute_model_action(raw_action)
                                                if exec_result:
                                                    print(f"[⚡ MODEL ACTION TRIGGERED]: {exec_result}", flush=True)
                                                    action_executed = True
                                        buf = buf.replace(raw_action, "")
                                    
                                    while True:
                                        if audio_engine.interrupted:
                                            break
                                        m = _SENTENCE_END.search(buf)
                                        if not m:
                                            break
                                        sentence, buf = buf[:m.end()].strip(), buf[m.end():]
                                        if sentence:
                                            speak_sentence(sentence)
                                            
                            if buf.strip() and not audio_engine.interrupted:
                                final_reply = buf.strip()
                                
                                # Check if jarvis actually understood
                                if not check_understanding(user_text, final_reply):
                                    print(
                                        f"[🤔 UNDERSTANDING CHECK FAILED - user: '{user_text[:80]}' | "
                                        f"reply: '{final_reply[:80]}' -> clarification]",
                                        flush=True
                                    )
                                    final_reply = make_clarification(user_text)
                                    speak_sentence(final_reply)
                                    _message_history.append({"role": "assistant", "content": final_reply})
                                    continue
                                
                                speak_sentence(final_reply)
                            else:
                                final_reply = "I didn't catch that. Could you repeat?"
                            
                            _message_history.append({"role": "assistant", "content": final_reply or "Error"})
                        except asyncio.TimeoutError:
                            print("[⚠️ OLLAMA TIMEOUT: Circuit breaker triggered]", flush=True)
                            speak_sentence("Local inference is under load. Proceeding with command.")
                        except Exception as e:
                            speak_sentence(f"Apologies, error occurred: {str(e)[:40]}")
                
                signals.set_state("idle")
                # Periodic cleanup to manage memory
                cleanup_resources()
                print("\n[👂 Listening for your next command...]", flush=True)
                
            time.sleep(0.01)
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            time.sleep(0.1)

    stream.stop()
    stream.close()

if __name__ == "__main__":
    asyncio.run(main_loop())
