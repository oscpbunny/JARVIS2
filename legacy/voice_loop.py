#!/usr/bin/env python3
"""Interactive Live Voice Session with Ollama & Kokoro TTS."""
import os
import sys
import asyncio
import tempfile
from pathlib import Path
from openai import AsyncOpenAI
import sounddevice as sd
from kokoro import KPipeline

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backtalk"))

from backtalk import signals
from backtalk.config import CFG

MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")

print(f"\n=======================================================")
print(f"  🎙️  JARVIS VOICE AGENT ONLINE")
print(f"  Mind:   {MODEL} (via {API_BASE})")
print(f"  Voice:  Kokoro TTS (bm_lewis) -> MacBook Pro Speakers")
print(f"  HUD:    http://127.0.0.1:8790")
print(f"=======================================================\n")

pipeline = KPipeline(lang_code='b')

async def speak(text):
    print(f"\n[JARVIS]: {text}\n", flush=True)
    signals.set_state("speaking")
    generator = pipeline(text, voice='bm_lewis', speed=1.05)
    for _, _, audio in generator:
        sd.play(audio, 24000)
        sd.wait()
    signals.set_state("idle")

async def chat():
    client = AsyncOpenAI(base_url=API_BASE, api_key="ollama")
    messages = [
        {"role": "system", "content": "You are Jarvis, a calm, intelligent cyber and software engineering AI companion. Keep answers punchy, natural, conversational, and direct (1-3 sentences max)."}
    ]
    
    # Startup greeting
    await speak("Jarvis online. All systems nominal. What are we working on?")
    
    while True:
        try:
            signals.set_state("idle")
            user_input = input("\nYou (press Ctrl+C to exit): ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "goodbye"):
                await speak("Powering down voice interface. Have a productive day.")
                break
                
            messages.append({"role": "user", "content": user_input})
            signals.set_state("thinking")
            print("[Jarvis is thinking...]", flush=True)
            
            resp = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                stream=False
            )
            reply = resp.choices[0].message.content or "Acknowledged."
            messages.append({"role": "assistant", "content": reply})
            
            await speak(reply)
            
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session...")
            signals.set_state("idle")
            break

if __name__ == "__main__":
    asyncio.run(chat())
