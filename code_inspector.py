#!/usr/bin/env python3
"""Native macOS Accessibility & Selected Code Inspector for Antigravity IDE & macOS.
Extracts highlighted code from active windows without manual copy-pasting.
"""
import subprocess

try:
    from jarvis_log import get_logger
    log = get_logger("code_inspector")
except Exception:  # standalone use without the log module
    import logging as _logging
    log = _logging.getLogger("code_inspector")

def get_selected_text() -> str | None:
    # 1. First attempt: AppleScript keystroke copy with fast clipboard tap
    script = '''
    set oldClip to the clipboard
    tell application "System Events"
        keystroke "c" using command down
    end tell
    delay 0.08
    set newClip to the clipboard
    return newClip
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
        txt = res.stdout.strip()
        if txt and len(txt) > 2:
            return txt
    except Exception:
        pass
    return None

if __name__ == "__main__":
    log.info("Testing code inspection on active selection...")
    selection = get_selected_text()
    if selection:
        msg = f"Selected ({len(selection)} chars):\n{selection[:200]}"
        log.info("%s", msg)
    else:
        log.info("No active text selection detected.")
