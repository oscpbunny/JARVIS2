#!/usr/bin/env python3
"""PILLAR 5 — Full-Duplex Audio & Instant Acoustic Barge-In.

Lets the user interrupt Jarvis mid-sentence ("Wait, skip that — just open Chrome")
and have him stop talking instantly (<~100ms) and re-listen.

Mechanism (per FRONTIER_PROGRESS spec):
  * TTS playback and mic input run concurrently — playback on a dedicated
    OutputStream, mic monitored on a private InputStream opened only while speaking.
  * Adaptive echo suppression: the speaker leakage baseline measured during
    playback raises the barge-in gate dynamically (echo_floor * 1.8); only
    *novel* louder user voice trips it. Two consecutive hot slices (~90ms)
    are required, so a single cough doesn't cut Jarvis off.
  * On barge-in the playback stream is stopped immediately, the LLM stream is
    aborted by the caller (via `interrupt` event), and the conversation buffer
    is truncated to the interruption point.

The engine never raises into the voice loop; failures degrade to plain sync TTS.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

_SENTENCE_STRIP = None  # set lazily to avoid circular imports


def fast_rms_int16(raw: bytes, _buf: dict | None = None) -> float:
    """Task 12 — zero-allocation RMS for one ~45ms int16 mic slice.

    Reuses a per-thread float32 scratch buffer (keyed by byte length) so
    the hot mic loop performs no fresh allocations: np.frombuffer views
    the PortAudio bytes, np.square/np.mean accumulate out-of-place into
    no new buffers beyond the reused scratch. Pure function of `raw`;
    returns 0.0 on empty/malformed input instead of raising.
    """
    try:
        if not raw:
            return 0.0
        view = np.frombuffer(raw, dtype=np.int16)
        if view.size == 0:
            return 0.0
        if _buf is None:
            _buf = {}
        key = view.size
        scratch = _buf.get(key)
        if scratch is None or scratch.shape != view.shape:
            scratch = np.empty(view.shape, dtype=np.float32)
            _buf[key] = scratch
        # Square in float32 via scratch: copy-then-square to avoid overflow.
        np.copyto(scratch, view, casting="unsafe")
        scratch *= scratch
        return float(np.sqrt(float(np.mean(scratch))))
    except Exception:
        return 0.0


_MIC_SCRATCH: dict = {}


def slice_energy(raw: bytes) -> float:
    """Task 12 convenience wrapper using the module-level scratch buffer."""
    return fast_rms_int16(raw, _MIC_SCRATCH)


class DuplexSpeech:
    """Interruptible Kokoro TTS engine with acoustic barge-in detection."""

    def __init__(self, tts_pipeline, voice: str = "bm_lewis", speed: float = 1.15,
                 tts_rate: int = 24000, mic_rate: int = 16000,
                 on_state: Callable[[str], None] | None = None,
                 on_interrupt: Callable[[], None] | None = None):
        self.pipeline = tts_pipeline
        self.voice = voice
        self.speed = speed
        self.tts_rate = tts_rate
        self.mic_rate = mic_rate
        self.on_state = on_state or (lambda s: None)
        self.on_interrupt = on_interrupt or (lambda: None)

        self.speaking = False
        self.abort_event = threading.Event()    # set by barge-in or external abort
        self.last_status = "done"               # "done" | "interrupted" | "error"
        self.barge_count = 0

        self.trigger_thresh = 1100.0            # configured from daemon calibration
        self.echo_floor = 0.0                   # adaptive speaker-leakage baseline
        self._hot_slices = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, trigger_thresh: float | None = None):
        """Pass the daemon's calibrated mic trigger threshold."""
        if trigger_thresh is not None:
            self.trigger_thresh = float(trigger_thresh)

    # ------------------------------------------------------------------
    # Barge-in gate (pure logic — unit-testable without audio hardware)
    # ------------------------------------------------------------------

    def barge_gate(self, mic_rms: float) -> float:
        """Dynamic RMS threshold that must be exceeded to count as interruption."""
        return max(self.trigger_thresh, self.echo_floor * 1.8)

    def should_interrupt(self, mic_rms: float, hot_needed: int = 2) -> bool:
        """Feed one mic slice (≈45ms). True ⇒ barge-in fired (event is set)."""
        if not self.speaking or self.abort_event.is_set():
            return False
        # Update adaptive echo floor from the leakage baseline (robust mean)
        self.echo_floor = (self.echo_floor * 0.9) + (mic_rms * 0.1) \
            if self.echo_floor > 0 else mic_rms
        if mic_rms > self.barge_gate(mic_rms):
            self._hot_slices += 1
        else:
            self._hot_slices = 0
        if self._hot_slices >= hot_needed:
            self.interrupt()
            return True
        return False

    def interrupt(self):
        """Acoustic or programmatic interruption — stops playback immediately."""
        self.abort_event.set()
        # Abort ONLY our own output stream (sd.stop() would kill the
        # daemon's listening InputStream too).
        out = getattr(self, "_out", None)
        try:
            if out is not None:
                out.abort()
        except Exception:
            pass

    def clear_interrupt(self):
        """Reset barge-in state before the next utterance/speak cycle."""
        self.abort_event.clear()
        self._hot_slices = 0
        self.echo_floor = 0.0

    # ------------------------------------------------------------------
    # Mic monitor — runs on a private thread only while speaking
    # ------------------------------------------------------------------

    def _mic_monitor(self):
        """Read the mic while TTS plays; trip barge-in on novel user voice."""
        try:
            mic = sd.InputStream(samplerate=self.mic_rate, channels=1, dtype="int16")
            mic.start()
        except Exception as e:
            print(f"[BARGE-IN] mic unavailable: {e}", flush=True)
            return
        slice_samples = int(self.mic_rate * 0.045)  # ~45ms slices
        try:
            while self.speaking and not self.abort_event.is_set():
                data, _ = mic.read(slice_samples)
                rms = slice_energy(bytes(data))  # Task 12: zero-alloc RMS
                if self.should_interrupt(rms):
                    print("\n[🔇 BARGE-IN DETECTED — stopping playback]", flush=True)
                    self.on_interrupt()
                    break
        except Exception:
            pass
        finally:
            try:
                mic.stop()
                mic.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def speak(self, text: str) -> str:
        """Speak `text` with live barge-in. Returns 'done' | 'interrupted' | 'error'.

        Non-reentrant: the caller (voice loop) awaits this synchronously; the
        mic monitor runs concurrently so the user can cut in at any time.
        """
        import re
        clean = re.sub(r"\[ACTION:[^\]]+\]", "", text).strip()
        if not clean:
            return "done"
        with self._lock:
            if self.speaking:
                return "error"
            self.speaking = True
        self.abort_event.clear()
        self._hot_slices = 0
        self.echo_floor = 0.0
        self.on_state("speaking")
        print(f"\n[JARVIS]: {clean}", flush=True)

        monitor = threading.Thread(target=self._mic_monitor, daemon=True)
        monitor.start()

        status = "done"
        slice_samples = int(self.tts_rate * 0.045)
        self._out = None
        try:
            self._out = sd.OutputStream(samplerate=self.tts_rate, channels=1,
                                        dtype="float32")
            self._out.start()
            generator = self.pipeline(clean, voice=self.voice, speed=self.speed)
            for _, _, audio in generator:
                if self.abort_event.is_set():
                    status = "interrupted"
                    break
                audio = np.asarray(audio, dtype=np.float32)
                # slice each TTS chunk so interruption latency stays ~45ms
                for i in range(0, len(audio), slice_samples):
                    if self.abort_event.is_set():
                        status = "interrupted"
                        break
                    self._out.write(audio[i:i + slice_samples])
                if status == "interrupted":
                    break
        except Exception as e:
            print(f"TTS error: {e}", flush=True)
            status = "error"
        finally:
            try:
                self._out.stop()
                self._out.close()
            except Exception:
                pass
            self.speaking = False
            monitor.join(timeout=0.6)
            self.last_status = status
        return status


if __name__ == "__main__":
    # Pure-logic sanity check (no audio devices touched)
    ds = DuplexSpeech(tts_pipeline=None)
    ds.configure(trigger_thresh=1000.0)
    ds.speaking = True
    ds.echo_floor = 500.0
    assert not ds.should_interrupt(600.0), "quiet leakage must not trip"
    # drive two hot slices to fire
    ds._hot_slices = 0
    ds.should_interrupt(6000.0)
    fired = ds.should_interrupt(6000.0)
    print("barge fired:", fired, "| gate:", ds.barge_gate(0))
    assert fired and ds.abort_event.is_set()
    ds.clear_interrupt()
    assert not ds.abort_event.is_set()
    print("PILLAR 5 barge-in state machine OK")


    def clear_interrupt(self):
        self.abort_event.clear()
        self._hot_slices = 0
        self.echo_floor = 0.0
