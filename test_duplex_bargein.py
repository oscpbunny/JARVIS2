#!/usr/bin/env python3
"""Standalone verification harness for Pillar 5 DuplexSpeech engine.
Tests mock acoustic energy gate and instant speech abort without requiring live audio hardware.
"""
import sys
import numpy as np
from pathlib import Path
from pillar_bridge import make_duplex_speech, _load_duplex_class

class MockTTSPipeline:
    def __call__(self, text, voice="af_heart", speed=1.0):
        mock_audio = np.zeros(24000, dtype=np.float32)
        yield "mock", "mock_ph", mock_audio

def test_duplex_logic():
    cls = _load_duplex_class()
    if cls is None:
        print("❌ Could not load DuplexSpeech class")
        sys.exit(1)

    mock_tts = MockTTSPipeline()
    engine = make_duplex_speech(mock_tts, trigger_thresh=1000.0)
    if engine is None:
        print("❌ Failed to instantiate DuplexSpeech via bridge")
        sys.exit(1)

    # Put engine in speaking state to test acoustic barge-in gating
    engine.speaking = True

    # 1. Verify quiet slice does not interrupt
    quiet_tripped = engine.should_interrupt(mic_rms=300.0)
    assert not quiet_tripped, "Quiet audio falsely tripped barge-in gate!"

    # 2. Verify 2 consecutive hot slices (> 1000 threshold) trigger barge-in
    engine.should_interrupt(mic_rms=6000.0)
    loud_tripped = engine.should_interrupt(mic_rms=6000.0)
    assert loud_tripped, "Loud audio failed to trigger barge-in gate!"
    assert engine.abort_event.is_set(), "Engine abort_event not set on interruption!"

    # 3. Verify reset
    engine.clear_interrupt()
    assert not engine.abort_event.is_set(), "Abort event failed to clear!"

    print("✅ DuplexSpeech logic, acoustic gating, and interruption tests PASSED cleanly.")

if __name__ == "__main__":
    test_duplex_logic()
