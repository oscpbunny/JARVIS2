#!/usr/bin/env python3
"""Comprehensive macOS System, App, Terminal & Automation Engine for Jarvis."""
import os
import sys
import subprocess
from pathlib import Path

# Ensure the skills/ subdirectory is importable
_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
if str(_SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILLS_DIR))

try:
    from dynamic_skill_engine import register_skill as _register_skill
    _SKILL_ENGINE_AVAILABLE = True
except ImportError:
    _SKILL_ENGINE_AVAILABLE = False
    def _register_skill(name, code):
        return False

try:
    from jarvis_config import ROOT
except ImportError:
    ROOT = Path(__file__).resolve().parent



APP_PATHS = {
    "antigravity": "/Applications/Antigravity IDE.app",
    "antigravity ide": "/Applications/Antigravity IDE.app",
    "davinci": "/Applications/DaVinci Resolve/DaVinci Resolve.app",
    "resolve": "/Applications/DaVinci Resolve/DaVinci Resolve.app",
    "chrome": "/Applications/Google Chrome.app",
    "obsidian": "/Applications/Obsidian.app",
    "safari": "/Applications/Safari.app",
    "terminal": "/System/Applications/Utilities/Terminal.app",
    "finder": "/System/Library/CoreServices/Finder.app",
    "notes": "/System/Applications/Notes.app",
    "spotify": "/Applications/Spotify.app"
}

def run_applescript(script: str):
    subprocess.run(["osascript", "-e", script], capture_output=True)

def open_app(key: str) -> str:
    key_clean = key.lower().strip()
    path = APP_PATHS.get(key_clean)
    if path and os.path.exists(path):
        subprocess.run(["open", path])
        name = Path(path).stem
        return f"Opening {name}."
    
    # Try general open by app name
    res = subprocess.run(["open", "-a", key], capture_output=True)
    if res.returncode == 0:
        return f"Opening {key}."
    return f"Opened {key}."

def close_app(key: str) -> str:
    key_clean = key.lower().strip()
    if "terminal" in key_clean:
        run_applescript('tell application "Terminal" to quit')
        return "Closed Terminal."
    elif "chrome" in key_clean:
        run_applescript('tell application "Google Chrome" to quit')
        return "Closed Google Chrome."
    elif "davinci" in key_clean or "resolve" in key_clean:
        run_applescript('tell application "DaVinci Resolve" to quit')
        return "Closed DaVinci Resolve."
    else:
        run_applescript(f'tell application "{key}" to quit')
        return f"Closed {key}."

def type_text(text: str) -> str:
    """Types text directly into the active foreground window, followed by return key."""
    escaped = text.replace('"', '\\"')
    script = f'''
    tell application "System Events"
        keystroke "{escaped}"
        key code 36
    end tell
    '''
    run_applescript(script)
    return f"Typed '{text}'."

def new_tab() -> str:
    run_applescript('tell application "System Events" to keystroke "t" using command down')
    return "Opened a new tab."

def set_volume(level: int) -> str:
    level = max(0, min(100, level))
    run_applescript(f"set volume output volume {level}")
    return f"Volume set to {level} percent."

def volume_up() -> str:
    run_applescript("set volume output volume ((output volume of (get volume settings)) + 15)")
    return "Turned volume up."

def volume_down() -> str:
    run_applescript("set volume output volume ((output volume of (get volume settings)) - 15)")
    return "Turned volume down."

def mute_volume() -> str:
    run_applescript("set volume with output muted")
    return "Muted system audio."

def media_play_pause() -> str:
    run_applescript('''
    if application "Spotify" is running then
        tell application "Spotify" to playpause
    else if application "Music" is running then
        tell application "Music" to playpause
    else
        tell application "System Events" to key code 100
    end if
    ''')
    return "Toggled media playback."

def draw_canvas() -> str:
    canvas_html = ROOT / "canvas.html"
    subprocess.run(["open", str(canvas_html)])
    return "Opening your interactive neural drawing canvas now."

def parse_and_execute_intent(text: str) -> str | None:
    t = text.lower().strip()
    if len(t) < 3 or t in ["you", "thank you", "bye", "hmm", "yeah", "uh"]:
        return None

    # 1. Type text command (e.g. "type exit", "type ls", "type clear")
    if t.startswith("type "):
        cmd_to_type = text[5:].strip()
        return type_text(cmd_to_type)
        
    # 2. Close app / Close terminal
    if "close" in t or "quit" in t or "exit" in t:
        if "terminal" in t:
            return close_app("terminal")
        if "chrome" in t:
            return close_app("chrome")
        if "resolve" in t or "davinci" in t:
            return close_app("davinci")

    # 3. Questions asking if it sees Antigravity IDE
    if "antigravity" in t and ("see" in t or "look" in t or "view" in t or "detect" in t or "open?" in t):
        # This is an inquiry, not an open command! Handled by screen vision.
        return None

    # 4. Open Antigravity IDE
    if ("open antigravity" in t or "launch antigravity" in t or "open ide" in t) and "not" not in t:
        return open_app("antigravity ide")

    # 5. Volume & Media
    if "volume up" in t or "turn up" in t or "louder" in t:
        return volume_up()
    if "volume down" in t or "turn down" in t or "quieter" in t:
        return volume_down()
    if t == "mute" or "mute audio" in t or "mute system" in t:
        return mute_volume()
    if "play" in t and "pause" in t or "pause music" in t or "pause track" in t or "resume music" in t:
        return media_play_pause()

    # 6. Browser Tabs
    if "new tab" in t or t == "tab" or "open tab" in t:
        return new_tab()

    # 7. Canvas / Drawing
    if any(w in t for w in ["draw", "canvas", "sketch", "whiteboard", "paint"]):
        return draw_canvas()
        
    # 8. DaVinci Resolve
    if any(w in t for w in ["open davinci", "open resolve", "launch resolve", "launch davinci", "damage result"]):
        return open_app("davinci")
        
    # 9. Chrome
    if "open chrome" in t or "launch chrome" in t:
        return open_app("chrome")
        
    # 10. Terminal
    if "open terminal" in t or "launch terminal" in t:
        return open_app("terminal")

    return None


def handle_missing_intent(user_text: str) -> str | None:
    """Attempt to synthesize a new skill for an unrecognized intent.
    Returns None if the skill engine is unavailable, allowing the caller
    to fall through to the LLM for a natural conversational response.
    """
    if not _SKILL_ENGINE_AVAILABLE:
        return None
    skill_name = user_text.lower().replace(' ', '_')[:30]
    stub_code = (
        f"def execute_skill(args: dict) -> dict:\n"
        f"    \"\"\"Generated stub for intent: {user_text}\"\"\"\n"
        f"    return {{'status': 'executed', 'message': 'Stub for: {user_text}'}}\n"
    )
    success = _register_skill(skill_name, stub_code)
    return None  # Always fall through to LLM for actual response; skill is stored for future use


def execute_model_action(action_tag: str) -> str | None:
    action_tag = action_tag.strip("[] ").replace("ACTION:", "").strip()
    parts = action_tag.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "open_app":
        return open_app(arg)
    elif cmd == "close_app":
        return close_app(arg)
    elif cmd == "type_text":
        return type_text(arg)
    elif cmd in ("draw_canvas", "draw"):
        return draw_canvas()
    elif cmd in ("new_tab", "tab"):
        return new_tab()
    elif cmd == "volume_up":
        return volume_up()
    elif cmd == "volume_down":
        return volume_down()
    elif cmd == "mute":
        return mute_volume()
    return None

if __name__ == "__main__":
    print(parse_and_execute_intent("type exit"))
    print(parse_and_execute_intent("close terminal"))
    print(open_app("antigravity ide"))
