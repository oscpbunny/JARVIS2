#!/usr/bin/env python3
"""PILLAR 6 — Native macOS Accessibility & Selected Code Inspector.

Reads whatever text/code the user has highlighted in ANY app (Xcode, Antigravity
IDE, Safari, Terminal, Electron webviews) without manual copy-pasting.

Resolution order (mirrors the FRONTIER_PROGRESS spec):
  1. `AXUIElement` focused-element query for `kAXSelectedTextAttribute`.
  2. System Events (AppleScript) AXSelectedText walk — works even when the raw
     AX API is TCC-blocked for this process.
  3. Clipboard fallback tap: snapshot pasteboard, simulate Cmd+C via CGEvent,
     poll for a pasteboard change, then seamlessly restore the prior contents.

All functions return {"ok": bool, "text": str, "backend": str, ...} and never raise.
"""
from __future__ import annotations

import subprocess
import time

try:
    from AppKit import NSPasteboard
    from ApplicationServices import (
        AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue)
    import Quartz
    _NATIVE = True
except Exception:  # pragma: no cover
    _NATIVE = False

_MAX_KEEP = 20_000  # cap injected code context at 20k chars


# --------------------------------------------------------------------------
# Backend 1 — raw AX focused element
# --------------------------------------------------------------------------

def _ax_selected_text_raw() -> str | None:
    try:
        sys_wide = AXUIElementCreateSystemWide()
        res = AXUIElementCopyAttributeValue(sys_wide, "AXFocusedApplication", None)
        err, app_el = (res if isinstance(res, tuple) else (0, res))
        if err != 0 or app_el is None:
            return None
        res2 = AXUIElementCopyAttributeValue(app_el, "AXFocusedUIElement", None)
        err2, focus_el = (res2 if isinstance(res2, tuple) else (0, res2))
        if err2 != 0 or focus_el is None:
            return None
        res3 = AXUIElementCopyAttributeValue(focus_el, "AXSelectedText", None)
        err3, text = (res3 if isinstance(res3, tuple) else (0, res3))
        if err3 == 0 and isinstance(text, str):
            return text
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Backend 2 — System Events AXSelectedText
# --------------------------------------------------------------------------

def _ax_selected_text_applescript() -> str | None:
    script = '''
    tell application "System Events"
        tell (first process whose frontmost is true)
            try
                set fe to value of attribute "AXFocusedUIElement"
                return value of attribute "AXSelectedText" of fe
            on error
                return ""
            end try
        end tell
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=6)
        if res.returncode == 0:
            text = res.stdout.rstrip("\n").strip()
            # AppleScript null renders as the literal string "missing value"
            if not text or text == "missing value":
                return None
            return text
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Backend 3 — clipboard fallback tap (Cmd+C + pasteboard restore)
# --------------------------------------------------------------------------

def _snapshot_pasteboard() -> tuple[int, str | None]:
    """Return (changeCount, currentString)."""
    pb = NSPasteboard.generalPasteboard()
    s = pb.stringForType_("public.utf8-plain-text")
    return int(pb.changeCount()), (s if s else None)


def _restore_pasteboard(prev_text: str | None):
    """Restore the prior string contents (best effort).

    A None snapshot means the clipboard held no string — clear it so the
    Cmd+C capture never leaks into the user's pasteboard.
    """
    try:
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        if prev_text is not None:
            pb.setString_forType_(prev_text, "public.utf8-plain-text")
    except Exception:
        pass


def _cmd_c() -> bool:
    """Simulate Cmd+C via CGEvent (keycode 8 = 'C' with Command flag)."""
    try:
        flags = Quartz.kCGEventFlagMaskCommand
        down = Quartz.CGEventCreateKeyboardEvent(None, 8, True)
        Quartz.CGEventSetFlags(down, flags)
        up = Quartz.CGEventCreateKeyboardEvent(None, 8, False)
        Quartz.CGEventSetFlags(up, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        return True
    except Exception:
        return False


def _selected_text_clipboard(timeout: float = 0.45) -> str | None:
    """Copy the selection with Cmd+C, read it, then restore the old pasteboard.

    Restore runs in `finally` so the user's clipboard is never corrupted,
    even if the Cmd+C tap, the poll loop, or an early return throws.
    """
    if not _NATIVE:
        return None
    prev_count, prev_text = _snapshot_pasteboard()
    try:
        if not _cmd_c():
            return None
        deadline = time.time() + timeout
        captured: str | None = None
        while time.time() < deadline:
            time.sleep(0.05)
            count, text = _snapshot_pasteboard()
            if count != prev_count and text:
                captured = text
                break
        return captured
    finally:
        # Seamless restore of the user's clipboard — always runs.
        _restore_pasteboard(prev_text)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def get_selected_text(prefer_clipboard: bool = False) -> dict:
    """Return the user's current text selection from any app.

    Order: clipboard tap (if requested) → raw AX → System Events AX → clipboard.
    """
    if not _NATIVE:
        text = _ax_selected_text_applescript()
        if text:
            return {"ok": True, "text": text[:_MAX_KEEP], "backend": "applescript"}
        return {"ok": False, "error": "native frameworks unavailable"}

    if prefer_clipboard:
        text = _selected_text_clipboard()
        if text:
            return {"ok": True, "text": text[:_MAX_KEEP], "backend": "clipboard"}

    text = _ax_selected_text_raw()
    if text:
        return {"ok": True, "text": text[:_MAX_KEEP], "backend": "ax"}

    text = _ax_selected_text_applescript()
    if text:
        return {"ok": True, "text": text[:_MAX_KEEP], "backend": "applescript"}

    text = _selected_text_clipboard()
    if text:
        return {"ok": True, "text": text[:_MAX_KEEP], "backend": "clipboard"}

    return {"ok": False, "error": "no selection exposed by the frontmost app"}


def selection_context(label: str = "highlighted code") -> str:
    """Human/LLM-ready context string describing the current selection."""
    res = get_selected_text()
    if not res.get("ok") or not res.get("text", "").strip():
        return ""
    text = res["text"].strip()
    lines = text.count("\n") + 1
    return (f"The user's currently highlighted {label} ({lines} lines, "
            f"captured via {res['backend']}):\n```\n{text}\n```")


if __name__ == "__main__":
    r = get_selected_text()
    print("backend:", r.get("backend"), "| ok:", r.get("ok"))
    print("text preview:", repr(r.get("text", ""))[:300])
