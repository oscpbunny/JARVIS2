#!/usr/bin/env python3
"""Task 13 - Mission 5 self-test suite (Tasks 11 + 12). Standalone, no hardware."""
import struct, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "legacy"))
RESULTS = []
def check(name, fn):
    try:
        detail = fn() or "ok"
        RESULTS.append((name, True, str(detail)))
    except AssertionError as e:
        RESULTS.append((name, False, "ASSERT: %s" % e))
    except Exception as e:
        RESULTS.append((name, False, "%s: %s" % (type(e).__name__, e)))
        traceback.print_exc()
def t11_imports():
    import mac_input_driver as d
    assert callable(d.get_menubar_items); assert callable(d.get_dock_apps)
    return "both importable"
def t11_menubar():
    import mac_input_driver as d
    items = d.get_menubar_items()
    assert isinstance(items, list); assert all(isinstance(x, str) for x in items)
    return "%d items" % len(items)
def t11_menubar_named():
    import mac_input_driver as d
    items = d.get_menubar_items("Finder")
    assert isinstance(items, list)
    return "%d items for Finder" % len(items)
def t11_dock():
    import mac_input_driver as d
    apps = d.get_dock_apps()
    assert isinstance(apps, list); assert all(isinstance(x, str) for x in apps)
    return "%d apps" % len(apps)
def t11_bridge():
    import pillar_bridge as b
    assert "get_menubar_items" in b.P2_ACTIONS; assert "get_dock_apps" in b.P2_ACTIONS
    return "both exported"
def t12_imports():
    from speech_duplex import fast_rms_int16, slice_energy
    assert callable(fast_rms_int16) and callable(slice_energy)
    return "both importable"
def t12_silence():
    from speech_duplex import slice_energy
    raw = struct.pack("<720h", *([0]*720))
    assert slice_energy(raw) == 0.0
    return "silence -> 0.0"
def t12_tone():
    import math
    from speech_duplex import slice_energy
    tone = [int(1000*math.sin(2*math.pi*i/48)) for i in range(720)]
    v = slice_energy(struct.pack("<720h", *tone))
    assert 600 < v < 800, v
    return "tone RMS=%.1f" % v
def t12_empty():
    from speech_duplex import fast_rms_int16, slice_energy
    assert fast_rms_int16(b"") == 0.0; assert slice_energy(b"\x00") == 0.0
    return "empty safe"
def t12_reuse():
    from speech_duplex import fast_rms_int16
    buf = {}
    raw = struct.pack("<720h", *([500]*720))
    a = fast_rms_int16(raw, buf); b = fast_rms_int16(raw, buf)
    assert len(buf) == 1 and a == b
    return "scratch reused RMS=%.1f" % a
def t12_latency():
    from speech_duplex import slice_energy
    raw = struct.pack("<720h", *([700]*720))
    slice_energy(raw)
    t0 = time.perf_counter()
    for _ in range(200): slice_energy(raw)
    us = (time.perf_counter()-t0)/200*1e6
    assert us < 2000, us
    return "%.1fus/slice" % us
def t12_gate():
    from speech_duplex import slice_energy, DuplexSpeech
    eng = DuplexSpeech(tts_pipeline=None)
    eng.configure(trigger_thresh=500.0); eng.speaking = True
    quiet = struct.pack("<720h", *([50]*720))
    loud = struct.pack("<720h", *([30000]*720))
    assert not eng.should_interrupt(slice_energy(quiet))
    assert any(eng.should_interrupt(slice_energy(loud)) for _ in range(3))
    eng.clear_interrupt()
    return "gate path ok"
if __name__ == "__main__":
    check("T11 imports", t11_imports); check("T11 menubar", t11_menubar)
    check("T11 menubar named", t11_menubar_named); check("T11 dock", t11_dock)
    check("T11 bridge", t11_bridge); check("T12 imports", t12_imports)
    check("T12 silence", t12_silence); check("T12 tone", t12_tone)
    check("T12 empty", t12_empty); check("T12 reuse", t12_reuse)
    check("T12 latency", t12_latency); check("T12 gate", t12_gate)
    n = sum(1 for _, ok, _ in RESULTS if ok)
    for name, ok, d in RESULTS: print("[PASS]" if ok else "[FAIL]", name + ":", d)
    print("%d/%d passed" % (n, len(RESULTS)))
    sys.exit(0 if n == len(RESULTS) else 1)
