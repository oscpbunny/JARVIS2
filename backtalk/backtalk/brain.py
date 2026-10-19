# backtalk: talk to your local AI agent out loud.
# Copyright (C) 2026 oscpbunny
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The warm brain - a persistent local Ollama session, streaming.

One Ollama connection lives for the whole voice session: no per-turn
process spawn, no per-turn context reload. Partial-message streaming
means sentences are yielded the moment they are complete, so the mouth
starts speaking while the rest of the thought is still forming.
"""
import asyncio
import json
import re
from pathlib import Path

import httpx

from backtalk import signals
from backtalk.config import CFG, DISCIPLINE
from backtalk.vlog import log

# The 7-pillar bridge: lets this single brain see code, dispatch subagents,
# look at the screen, recall the screen, run app/GUI actions, and pull
# vault context — all before/while the LLM streams.
from backtalk import pillars

# The self-learning layer: learned preferences, turn-outcome reinforcement
# (completed/interrupted/corrected), and the brevity hint that follows.
from backtalk import learning

_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
# A model-emitted action tag, e.g. [ACTION: open chrome]. Executed inline,
# stripped from the spoken sentence.
_ACTION_TAG = re.compile(r"\[ACTION:\s*([^\]]+)\]")

# Shared conversation memory — a single JSONL both this brain and any other
# entry point read/write, so there is ONE memory for the whole system.
MEMORY_PATH = Path(__file__).resolve().parent.parent.parent / "jarvis_memory.jsonl"

# Ollama endpoint - same local server always_online_jarvis uses.
OLLAMA_URL = "http://localhost:11434/api/chat"

_SYSTEM = DISCIPLINE


class WarmBrain:
    def __init__(self, model=None):
        self.model = model or CFG["model"]
        self._messages = []
        self.session = {"turns": 0, "out_tokens": 0,
                        "in_tokens": 0, "cost": 0.0}
        self._client = None
        self._dirty = False
        self._stream_task = None
        # The self-learning layer: id of the turn now streaming, so the
        # interrupt/correct signals from the voice loop can score it.
        self._turn_id = None

    async def start(self):
        """Verify Ollama is reachable and the model is available."""
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        try:
            r = await self._client.get("http://localhost:11434/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if self.model not in models:
                base = self.model.split(":")[0]
                if not any(m == self.model or m.startswith(base + ":")
                           for m in models):
                    log("[brain] warning: model " + repr(self.model)
                        + " not in Ollama. Available: " + str(models))
        except Exception as e:
            log("[brain] Ollama unreachable: " + repr(e))
            raise RuntimeError(
                "Ollama is not running at localhost:11434. "
                "Start it with ollama serve.") from e

    async def stop(self):
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
        if self._client:
            await self._client.aclose()
            self._client = None

    async def reset_turn(self):
        """Cancel any in-flight stream so the pipe is clean."""
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except (asyncio.CancelledError, Exception):
                pass
        self._stream_task = None
        self._dirty = False

    async def interrupt(self):
        await self.reset_turn()

    def score_interrupt(self):
        """The voice loop cut this reply off — a negative signal to learn from."""
        learning.interrupt_turn(self._turn_id)
        self._turn_id = None

    def score_correction(self):
        """The user corrected this reply — a negative signal to learn from."""
        learning.mark_corrected(self._turn_id)
        self._turn_id = None

    async def command(self, cmd):
        """Handle slash-commands locally (no remote CLI)."""
        cmd = cmd.strip()
        if cmd.startswith("/clear"):
            self._messages.clear()
            log("[brain] conversation cleared")
            return "Conversation cleared."
        if cmd.startswith("/compact"):
            self._messages.clear()
            log("[brain] conversation compacted (cleared)")
            return "Compacted."
        if cmd.startswith("/model"):
            parts = cmd.split(None, 1)
            if len(parts) == 2:
                self.model = parts[1].strip()
                log("[brain] model switched to " + self.model)
                return "Model switched to " + self.model + "."
            return "No model name given."
        if cmd.startswith("/effort"):
            return "Effort is not available with local models."
        return ""

    async def context_usage(self):
        return None

    def _remember_session(self, eval_count, prompt_eval_count):
        self.session["turns"] += 1
        self.session["out_tokens"] += eval_count
        self.session["in_tokens"] += prompt_eval_count

    async def ask_stream(self, utterance):
        """Yield complete sentences as they stream out of the model.

        The single unified turn path. Before the LLM runs, the 7-pillar
        router gets first refusal: a direct answer (vision, recall, app
        action, subagent confirmation) is spoken and the model is skipped;
        otherwise any pillar context (highlighted code, vault notes) is
        injected and the model streams. [ACTION:...] tags the model emits
        are executed inline and stripped from what is spoken.
        """
        if self._client is None:
            await self.start()

        # ── Pillar routing: can a pillar answer without the LLM? ──────────
        direct, context = await asyncio.to_thread(pillars.route, utterance)
        if direct:
            # A pillar answered fully. Speak it, remember it, skip the LLM.
            tid = learning.begin_turn(utterance, "direct")
            self._messages.append({"role": "user", "content": utterance})
            self._messages.append({"role": "assistant", "content": direct})
            if len(self._messages) > 40:
                self._messages = self._messages[-40:]
            self._log_interaction(utterance, direct)
            learning.complete_turn(tid, direct, 0)
            yield direct
            return

        # The prompt the model sees: pillar context if present, else raw.
        prompt = context if context else utterance

        # A plain turn now streams; the learning layer scores it on the way
        # out (completed / interrupted / corrected).
        self._turn_id = learning.begin_turn(
            utterance, "llm+ctx" if context else "llm")

        # Learned preferences + brevity hint ride on the system prompt, so
        # the brain personalises and self-condenses over time.
        messages = [{"role": "system",
                     "content": (_SYSTEM + learning.preferences_block()
                                 + learning.brevity_hint())}]
        messages.extend(self._messages)
        messages.append({"role": "user", "content": prompt})

        self._dirty = True
        buf = ""
        spoken = []
        full_reply = []
        eval_count = 0
        prompt_eval_count = 0
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.7},
        }

        try:
            async with self._client.stream(
                    "POST", OLLAMA_URL, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise RuntimeError(data["error"])
                    chunk = (data.get("message") or {}).get("content", "")
                    if chunk:
                        full_reply.append(chunk)
                        buf += chunk
                        # Execute any [ACTION:...] tags now present in the
                        # buffer; they never reach the mouth.
                        buf, acted = self._run_action_tags(buf)
                        for a in acted:
                            log("[brain] action: " + a)
                        while True:
                            m = _SENTENCE_END.search(buf)
                            if not m:
                                break
                            sentence, buf = (buf[:m.end()].strip(),
                                             buf[m.end():])
                            if sentence:
                                spoken.append(sentence)
                                yield sentence
                    if data.get("done"):
                        eval_count = data.get("eval_count", 0)
                        prompt_eval_count = data.get(
                            "prompt_eval_count", 0)
        finally:
            self._stream_task = None

        tail = buf.strip()
        if tail:
            spoken.append(tail)
            yield tail

        reply_text = "".join(full_reply)
        self._messages.append({"role": "user", "content": utterance})
        self._messages.append({"role": "assistant", "content": reply_text})
        if len(self._messages) > 40:
            self._messages = self._messages[-40:]

        self._log_interaction(utterance, " ".join(spoken) or reply_text)
        learning.complete_turn(self._turn_id, reply_text, 0)
        self._turn_id = None
        self._remember_session(eval_count, prompt_eval_count)
        self._dirty = False

    def _run_action_tags(self, buf):
        """Execute every [ACTION: ...] in buf. Returns (cleaned, [results]).

        P2 GUI driver and the app-control engine run the tag; the tag text
        is removed so it is never spoken.
        """
        results = []

        def _fire(m):
            tag = m.group(1).strip()
            res = None
            try:
                res = pillars.execute_action_tag("[ACTION: " + tag + "]")
            except Exception as e:
                log("[brain] action tag failed: " + repr(e))
            if res:
                results.append(res)
            return ""

        cleaned = _ACTION_TAG.sub(_fire, buf)
        return cleaned, results

    def _log_interaction(self, user_text, reply_text):
        """Append one exchange to the shared JSONL memory. Never raises."""
        try:
            import time as _t
            rec = {"ts": _t.time(), "turn": self.session["turns"] + 1,
                   "user": user_text, "reply": reply_text,
                   "model": self.model}
            with open(MEMORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            log("[brain] memory write failed: " + repr(e))
