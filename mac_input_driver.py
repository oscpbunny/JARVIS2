#!/usr/bin/env python3
"""PILLAR 2 — Autonomous GUI Computer-Use & Agentic Click/Type Controller.

High-precision macOS input driver for Jarvis:
  * Bezier-curved, human-like cursor interpolation (kCGEventMouseMoved).
  * Click / double-click / drag via Quartz CGEvent (verified working under this venv).
  * AXUIElement accessibility-tree extraction with an AppleScript (System Events)
    fallback for processes the raw AX API cannot reach without TCC grants.
  * Generic menu-bar walking (`click_menu`) used for app-specific workflows
    (e.g. DaVinci Resolve page switching: Cut / Edit / Fusion / Color / Deliver).

All public functions degrade gracefully: on any AX/Quartz failure they return
`{"ok": False, "error": "..."}` instead of raising, so the voice loop never dies.
"""
from __future__ import annotations

import math
import os
import random
import subprocess
import time
from typing import Any

try:
    import Quartz
    _QUARTZ = True
except Exception:  # pragma: no cover
    Quartz = None  # type: ignore
    _QUARTZ = False

# --------------------------------------------------------------------------
# Cursor primitives
# --------------------------------------------------------------------------

def current_cursor() -> tuple[float, float]:
    """Return the current global cursor position (top-left origin, screen points)."""
    if not _QUARTZ:
        raise RuntimeError("Quartz unavailable")
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return float(loc.x), float(loc.y)


def _post_mouse(kind, x: float, y: float, button=None):
    if not _QUARTZ:
        raise RuntimeError("Quartz unavailable")
    from Quartz import CGPoint
    if button is None:
        button = Quartz.kCGMouseButtonLeft
    ev = Quartz.CGEventCreateMouseEvent(None, kind, CGPoint(x=x, y=y), button)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _bezier(p0, p1, p2, p3, t: float) -> tuple[float, float]:
    """Cubic bezier evaluation — gives cursors a natural arc."""
    u = 1 - t
    x = (u ** 3) * p0[0] + 3 * (u ** 2) * t * p1[0] + 3 * u * (t ** 2) * p2[0] + (t ** 3) * p3[0]
    y = (u ** 3) * p0[1] + 3 * (u ** 2) * t * p1[1] + 3 * u * (t ** 2) * p2[1] + (t ** 3) * p3[1]
    return x, y


def bezier_path(start: tuple[float, float], end: tuple[float, float],
                steps: int = 24, wobble: float | None = None) -> list[tuple[float, float]]:
    """Curved human-like trajectory from `start` to `end` (randomised control points)."""
    if wobble is None:
        dist = math.hypot(end[0] - start[0], end[1] - start[1])
        wobble = max(30.0, dist * 0.35)
    c1 = (start[0] + random.uniform(-wobble, wobble) * 0.4,
          start[1] + random.uniform(-wobble, wobble) * 0.4)
    c2 = (end[0] + random.uniform(-wobble, wobble) * 0.6,
          end[1] + random.uniform(-wobble, wobble) * 0.6)
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        te = t * t * (3 - 2 * t)  # ease-in-out deceleration
        out.append(_bezier(start, c1, c2, end, te))
    out[-1] = end
    return out


def move_to(x: float, y: float, curved: bool = True, duration: float = 0.22) -> dict:
    """Move the cursor to (x, y) with optional bezier arc + human speed."""
    try:
        start = current_cursor()
        if curved:
            steps = max(8, int(duration / 0.012))
            path = bezier_path(start, (x, y), steps=steps)
        else:
            path = [(x, y)]
        for px, py in path:
            _post_mouse(Quartz.kCGEventMouseMoved, px, py)
            time.sleep(duration / max(1, len(path)))
        return {"ok": True, "x": x, "y": y}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def click(x: float | None = None, y: float | None = None, clicks: int = 1,
          curved: bool = True) -> dict:
    """Click at (x, y) (moving there first). clicks=2 = double-click."""
    try:
        if x is not None and y is not None:
            r = move_to(x, y, curved=curved)
            if not r.get("ok"):
                return r
        from Quartz import CGPoint
        if x is None or y is None:
            loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
            cx, cy = float(loc.x), float(loc.y)
        else:
            cx, cy = float(x), float(y)
        for _ in range(max(1, clicks)):
            _post_mouse(Quartz.kCGEventLeftMouseDown, cx, cy)
            time.sleep(0.045)
            _post_mouse(Quartz.kCGEventLeftMouseUp, cx, cy)
            time.sleep(0.06)
        return {"ok": True, "clicked": clicks, "x": cx, "y": cy}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _post_key(keycode: int):
    down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def press_key(keycode: int, modifiers: list[str] | None = None) -> dict:
    """Post a raw keycode (36=Return, 49=Space…) with optional ['command','shift',…]."""
    try:
        flags = 0
        table = {"command": Quartz.kCGEventFlagMaskCommand,
                 "shift": Quartz.kCGEventFlagMaskShift,
                 "option": Quartz.kCGEventFlagMaskAlternate,
                 "control": Quartz.kCGEventFlagMaskControl}
        for m in modifiers or []:
            flags |= table.get(m.lower(), 0)
        down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
        Quartz.CGEventSetFlags(down, flags)
        up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
        Quartz.CGEventSetFlags(up, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Task 11 — Typing safety interlock (allowlisted targets only)
# --------------------------------------------------------------------------

# Integration lane 19:30: CotEditor.app is NOT installed on this Mac.
# Broadened to the user's real IDEs/editors + terminals.
_SAFE_TARGET_APPS = (
    "coteditor",
    "antigravity",
    "terminal",
    "iterm2",
    "iterm",
    "xcode",
    "textedit",
    "vscode",
    "visual studio code",
    "cursor",
    "sublime",
    "atom",
    "vim",
    "emacs",
)


def _frontmost_bundle() -> str:
    """Bundle id of the frontmost app ('' on failure)."""
    try:
        res = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get bundle identifier of first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5)
        return res.stdout.strip().lower() if res.returncode == 0 else ""
    except Exception:
        return ""


def _typing_allowed(app_hint: str | None = None) -> tuple[bool, str]:
    """Task 11 interlock: only allowlisted apps may receive keys.

    Frontmost app must match _SAFE_TARGET_APPS by name or bundle id,
    or match an explicit app_hint (daemon-only: forwarded solely from
    validated focus_app_window contexts, never from voice/model text).
    """
    try:
        cur = _frontmost_name().lower()
        bundle = _frontmost_bundle()
        if any(s in cur or s in bundle for s in _SAFE_TARGET_APPS):
            return True, cur or bundle
        if app_hint and (app_hint.lower() in cur or app_hint.lower() in bundle):
            return True, cur or bundle
        return False, cur or bundle or "unknown"
    except Exception as e:
        return False, f"check-failed: {e}"


def type_keys(text: str, app_hint: str | None = None) -> dict:
    """Type literal text into the focused control via CGEvent unicode keystrokes.

    Task 7: batch-chunked injection — the string is posted in ≤64-char
    CGEvent chunks sharing one key-down/up pair, instead of one event pair
    per character. Newlines/tabs/space go through raw keycodes only when the
    whole string is a single control char; mixed text stays in unicode chunks.
    Old per-character path removed (it was 12ms/char = ~80 chars/sec max).

    Task 11: SAFETY INTERLOCK — refuses unless an allowlisted app
    (Antigravity/Terminal/iTerm/Xcode/TextEdit/…) is frontmost
    (or app_hint matches the frontmost app — daemon-only hint).
    Prevents keystrokes landing in chat/voice UI. Returns
    {"ok": False, "blocked": ..., "error": ...} on refusal; never raises.
    """
    try:
        ok, target = _typing_allowed(app_hint)
        if not ok:
            return {"ok": False, "blocked": target,
                    "error": f"typing blocked: frontmost app is '{target}' — "
                             "bring an allowlisted app forward or pass app_hint"}
        if not text:
            return {"ok": True, "typed": 0}
        if text == " ":
            _post_key(49)
            return {"ok": True, "typed": 1}
        if text == "\n":
            _post_key(36)
            return {"ok": True, "typed": 1}
        if text == "\t":
            _post_key(48)
            return {"ok": True, "typed": 1}
        CHUNK = 64
        n = 0
        for i in range(0, len(text), CHUNK):
            piece = text[i:i + CHUNK].replace("\n", " ").replace("\t", " ")
            down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            Quartz.CGEventKeyboardSetUnicodeString(down, len(piece), piece)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
            up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventKeyboardSetUnicodeString(up, len(piece), piece)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
            n += len(piece)
        return {"ok": True, "typed": n}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --------------------------------------------------------------------------
# Accessibility tree
# --------------------------------------------------------------------------

_ROLE_KEYS = ("AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXRoleDescription")
_VALUE_KEYS = ("AXValue", "AXSelectedText", "AXFilename", "AXURL")


_AX_PERF: dict[str, Any] = {"calls": 0, "focused_hits": 0, "full_hits": 0, "last_ms": 0.0}


# ----------------------------------------------------------------------
# Task 14 — AX perf tracer (per-stage timing breakdown)
# ----------------------------------------------------------------------

_AX_TRACE: dict[str, Any] = {
    "calls": 0, "focused_wins": 0, "full_wins": 0, "applescript_fallbacks": 0,
    "last_stages_ms": {}, "last_total_ms": 0.0, "last_path": "unknown",
    "slow_queries": [],  # rolling tail of >500ms queries (max 20)
}


def _trace_stage(store: dict, name: str, t0: float) -> None:
    try:
        store[name] = round((time.perf_counter() - t0) * 1000, 2)
    except Exception:
        pass


def ax_trace() -> dict:
    """Return the Task-14 AX tracer state (integration lane can log this).

    Counters + last per-stage timings + rolling tail of slow (>500ms) queries.
    Never raises.
    """
    try:
        return {"ok": True, **{k: (list(v) if isinstance(v, list) else v)
                               for k, v in _AX_TRACE.items()}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _record_ax_trace(path: str, stages: dict, total_ms: float,
                     app: str | None = None, n_elements: int = 0) -> None:
    try:
        _AX_TRACE["calls"] += 1
        if path == "focused":
            _AX_TRACE["focused_wins"] += 1
        elif path == "full":
            _AX_TRACE["full_wins"] += 1
        else:
            _AX_TRACE["applescript_fallbacks"] += 1
        _AX_TRACE["last_stages_ms"] = dict(stages)
        _AX_TRACE["last_total_ms"] = round(total_ms, 2)
        _AX_TRACE["last_path"] = path
        if total_ms > 500:
            _AX_TRACE["slow_queries"].append({
                "app": app, "path": path, "ms": round(total_ms, 1),
                "elements": n_elements, "stages": dict(stages),
            })
            del _AX_TRACE["slow_queries"][:-20]
    except Exception:
        pass


def _record_ax_perf(path: str, n_elements: int) -> None:
    try:
        _AX_PERF["calls"] += 1
        if path == "focused":
            _AX_PERF["focused_hits"] += 1
        else:
            _AX_PERF["full_hits"] += 1
    except Exception:
        pass


def ax_perf() -> dict:
    """Return Task-6 AX fast-path counters (integration lane can log this)."""
    return {"ok": True, **_AX_PERF}


def _ax_attr(element, name: str):
    try:
        from ApplicationServices import AXUIElementCopyAttributeValue
        res = AXUIElementCopyAttributeValue(element, name, None)
        if isinstance(res, tuple) and len(res) == 2:
            return res[1] if res[0] == 0 else None
        return res
    except Exception:
        return None


def _ax_children(element) -> list:
    kids = _ax_attr(element, "AXChildren")
    return list(kids) if kids else []


def _describe_ax(element, depth: int, max_depth: int, out: list, prefix: str):
    if depth > max_depth:
        return
    info: dict[str, Any] = {"path": prefix}
    for k in _ROLE_KEYS + _VALUE_KEYS:
        v = _ax_attr(element, k)
        if v is None:
            continue
        try:
            info[k] = str(v)[:160]
        except Exception:
            pass
    pos = _ax_attr(element, "AXPosition")
    size = _ax_attr(element, "AXSize")
    try:
        if pos is not None and size is not None:
            info["x"] = float(pos.x)
            info["y"] = float(pos.y)
            info["w"] = float(size.width)
            info["h"] = float(size.height)
    except Exception:
        pass
    if "x" in info and (info["w"] <= 0 or info["h"] <= 0):
        return  # invisible / offscreen leaf
    if len(info) > 1:
        out.append(info)
    for i, child in enumerate(_ax_children(element)):
        _describe_ax(child, depth + 1, max_depth, out, f"{prefix}/{i}")

def _ax_tree_applescript(app_name: str | None) -> dict:
    """AppleScript fallback: list buttons/checkboxes/text fields of the front window."""
    proc = "first process whose frontmost is true"
    if app_name:
        proc = f'application process "{app_name}"'
    script = f'''
    tell application "System Events"
        tell {proc}
            set outList to {{}}
            try
                set w to front window
                set wTitle to name of w
                repeat with b in (every button of w)
                    try
                        set end of outList to "BUTTON|" & (name of b as string) & "|" & (description of b as string)
                    end try
                end repeat
                repeat with cb in (every checkbox of w)
                    try
                        set end of outList to "CHECKBOX|" & (name of cb as string) & "|"
                    end try
                end repeat
                repeat with tf in (every text field of w)
                    try
                        set end of outList to "TEXTFIELD|" & (name of tf as string) & "|" & (value of tf as string)
                    end try
                end repeat
                set delims to AppleScript's text item delimiters
                set AppleScript's text item delimiters to "%%%"
                set body to wTitle & "%%%" & (outList as string)
                set AppleScript's text item delimiters to delims
                return body
            on error
                return "%%%"
            end try
        end tell
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=8)
        body = res.stdout.strip()
        title, _, items = body.partition("%%%")
        elements = []
        for i, row in enumerate(items.split("%%%")):
            parts = row.split("|")
            if len(parts) >= 2 and parts[1].strip():
                el = {"path": f"as/{i}", "AXRoleDescription": parts[0], "AXTitle": parts[1]}
                if len(parts) > 2 and parts[2].strip():
                    el["AXDescription"] = parts[2]
                elements.append(el)
        return {"ok": True, "app": app_name or _frontmost_name(),
                "title": title, "elements": elements, "backend": "applescript"}
    except Exception as e:
        return {"ok": False, "error": f"applescript tree failed: {e}"}


def find_element(tree: dict, label: str) -> dict | None:
    """First element whose title/description/role contains `label` (case-insensitive).

    Prefers raw-AX elements (they carry pixel frames) over AppleScript rows.
    """
    needle = label.lower().strip()
    elements = tree.get("elements", []) if isinstance(tree, dict) else []
    best = None
    for el in elements:
        hay = " ".join(str(el.get(k, "")) for k in
                       ("AXTitle", "AXDescription", "AXRoleDescription", "AXRole")).lower()
        if needle and needle in hay:
            if "x" in el:
                return el
            best = best or el
    return best


def click_element(label: str, app_name: str | None = None) -> dict:
    """Locate a UI element by accessible name and click it (coordinate click or AX press)."""
    tree = get_ax_tree(app_name)
    if not tree.get("ok"):
        return tree
    el = find_element(tree, label)
    if el is None:
        preview = [e.get("AXTitle", "?") for e in tree.get("elements", [])][:8]
        return {"ok": False, "error": f"no element matching '{label}'", "visible": preview}
    if "x" in el:
        return click(el["x"] + el["w"] / 2, el["y"] + el["h"] / 2)
    return _ax_press_applescript(app_name, el)


def _ax_press_applescript(app_name: str | None, el: dict) -> dict:
    """Fallback AXPress for AppleScript-discovered elements."""
    title = el.get("AXTitle", "")
    role = el.get("AXRoleDescription", "button").lower()
    proc = f'application process "{app_name}"' if app_name else "first process whose frontmost is true"
    plural = "checkboxes" if "check" in role else "buttons"
    script = f'''
    tell application "System Events"
        tell {proc}
            repeat with e in (every {plural} of front window)
                if (name of e as string) is "{title}" then
                    perform action "AXPress" of e
                    return "pressed"
                end if
            end repeat
        end tell
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
        if res.returncode == 0 and "pressed" in res.stdout:
            return {"ok": True, "pressed": title, "backend": "applescript"}
        return {"ok": False, "error": f"could not press '{title}'"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

        out.append(info)
    for i, child in enumerate(_ax_children(element)):
        _describe_ax(child, depth + 1, max_depth, out, f"{prefix}/{i}")


def get_ax_tree(app_name: str | None = None, max_depth: int = 5) -> dict:
    """Accessibility tree of the frontmost (or named) app.

    Returns {"ok", "app", "elements": [{AXRole, AXTitle, x, y, w, h, ...}]}.
    Task 14: per-stage timing tracer — each query records resolve_pid_ms /
    describe_ms / applescript_ms into ax_trace(), plus a rolling tail of
    queries slower than 500ms.
    """
    t_all = time.perf_counter()
    stages: dict[str, float] = {}
    try:
        from ApplicationServices import AXUIElementCreateApplication, AXUIElementCopyAttributeValue
        t0 = time.perf_counter()
        pid = _pid_for(app_name) if app_name else _frontmost_pid()
        _trace_stage(stages, "resolve_pid_ms", t0)
        if pid is None:
            t0 = time.perf_counter()
            fb = _ax_tree_applescript(app_name)
            _trace_stage(stages, "applescript_ms", t0)
            total = (time.perf_counter() - t_all) * 1000
            _record_ax_trace("applescript", stages, total,
                             app_name, len(fb.get("elements", [])))
            return fb
        app_el = AXUIElementCreateApplication(pid)
        # Task 6 fast path: AXFocusedWindow first (sub-50ms for AppKit apps),
        # before the full AXWindows 5-level traversal.
        try:
            res0 = AXUIElementCopyAttributeValue(app_el, "AXFocusedWindow", None)
            err0, fwin = (res0 if isinstance(res0, tuple) else (0, res0))
            if err0 == 0 and fwin is not None:
                fast: list = []
                t0 = time.perf_counter()
                _describe_ax(fwin, 0, max_depth, fast, "w")
                _trace_stage(stages, "describe_ms", t0)
                if fast:
                    _record_ax_perf("focused", len(fast))
                    total = (time.perf_counter() - t_all) * 1000
                    _record_ax_trace("focused", stages, total,
                                     app_name or _app_name(pid), len(fast))
                    return {"ok": True, "pid": pid, "app": app_name or _app_name(pid),
                            "elements": fast, "backend": "ax", "fast_path": "focused"}
        except Exception:
            pass
        res = AXUIElementCopyAttributeValue(app_el, "AXWindows", None)
        err, wins = (res if isinstance(res, tuple) else (0, res))
        out: list = []
        if err == 0 and wins:
            t0 = time.perf_counter()
            for w in wins:
                _describe_ax(w, 0, max_depth, out, "w")
            _trace_stage(stages, "describe_ms", t0)
        else:
            res2 = AXUIElementCopyAttributeValue(app_el, "AXFocusedWindow", None)
            err2, win = (res2 if isinstance(res2, tuple) else (0, res2))
            if err2 == 0 and win is not None:
                t0 = time.perf_counter()
                _describe_ax(win, 0, max_depth, out, "w")
                _trace_stage(stages, "describe_ms", t0)
        if not out:
            t0 = time.perf_counter()
            fb = _ax_tree_applescript(app_name)
            _trace_stage(stages, "applescript_ms", t0)
            total = (time.perf_counter() - t_all) * 1000
            _record_ax_trace("applescript", stages, total,
                             app_name or _app_name(pid), len(fb.get("elements", [])))
            return fb
        _record_ax_perf("full", len(out))
        total = (time.perf_counter() - t_all) * 1000
        _record_ax_trace("full", stages, total,
                         app_name or _app_name(pid), len(out))
        return {"ok": True, "pid": pid, "app": app_name or _app_name(pid),
                "elements": out, "backend": "ax"}
    except Exception as e:
        t0 = time.perf_counter()
        fallback = _ax_tree_applescript(app_name)
        _trace_stage(stages, "applescript_ms", t0)
        total = (time.perf_counter() - t_all) * 1000
        _record_ax_trace("applescript", stages, total,
                         app_name, len(fallback.get("elements", []))
                         if isinstance(fallback, dict) else 0)
        if isinstance(fallback, dict):
            fallback["ax_error"] = str(e)
        return fallback



def drag(x1: float, y1: float, x2: float, y2: float, duration: float = 0.45) -> dict:
    """Press at (x1,y1), drag along a bezier arc, release at (x2,y2)."""
    try:
        move_to(x1, y1)
        _post_mouse(Quartz.kCGEventLeftMouseDown, x1, y1)
        time.sleep(0.08)
        for px, py in bezier_path((x1, y1), (x2, y2)):
            _post_mouse(Quartz.kCGEventLeftMouseDragged, px, py)
            time.sleep(duration / 24)
        _post_mouse(Quartz.kCGEventLeftMouseUp, x2, y2)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def click_menu(app_name: str, menu_path: list[str]) -> dict:
    """Click a menu bar item then a submenu item, e.g.
    click_menu('DaVinci Resolve', ['Workspace', 'Deliver'])."""
    if not menu_path:
        return {"ok": False, "error": "empty menu path"}
    press_top = f'''
            tell (menu bar 1)
                perform action "AXPress" of menu item "{menu_path[0]}" of menu 1 of menu bar item "{menu_path[0]}"
            end tell'''
    press_sub = ""
    if len(menu_path) > 1:
        press_sub = f'''
            perform action "AXPress" of menu item "{menu_path[1]}" of menu 1 of menu bar item "{menu_path[0]}" of menu bar 1'''
    script = f'''
    tell application "System Events"
        tell application process "{app_name}"
            set frontmost to true
            delay 0.2{press_top}
            delay 0.25{press_sub}
        end tell
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return {"ok": True, "menu": " > ".join(menu_path)}
        err = (res.stderr or "").strip().splitlines()
        return {"ok": False, "error": err[-1] if err else "menu press failed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --------------------------------------------------------------------------
# Application-specific workflows (Pillar 2 spec)
# --------------------------------------------------------------------------

_DAVINCI_PAGES = ("Cut", "Edit", "Fusion", "Color", "Deliver")


def davinci_page(page: str) -> dict:
    """Switch DaVinci Resolve workspace page (Cut/Edit/Fusion/Color/Deliver)."""
    page = page.strip().capitalize()
    if page not in _DAVINCI_PAGES:
        return {"ok": False, "error": f"unknown Resolve page '{page}'", "valid": list(_DAVINCI_PAGES)}
    r = ensure_front("DaVinci Resolve", "/Applications/DaVinci Resolve/DaVinci Resolve.app")
    if not r.get("ok"):
        return r
    time.sleep(1.2)
    return click_menu("DaVinci Resolve", ["Workspace", page])


def davinci_render_youtube_4k() -> dict:
    """Best-effort Deliver flow: open Deliver page, then press 'Render All'."""
    steps = []
    r = davinci_page("Deliver")
    steps.append(("open Deliver", r.get("ok", False)))
    time.sleep(0.8)
    r2 = click_element("Add to Render Queue", app_name="DaVinci Resolve")
    steps.append(("Add to Render Queue", r2.get("ok", False)))
    r3 = click_element("Render All", app_name="DaVinci Resolve")
    steps.append(("Render All", r3.get("ok", False)))
    return {"ok": steps[0][1], "steps": steps,
            "note": "Render flow is best-effort; confirm by voice once the queue starts."}


def ensure_front(app_name: str, path: str) -> dict:
    """Activate an app (launching it if needed) and bring it to the front."""
    res = subprocess.run(["osascript", "-e", f'tell application "{app_name}" to activate'],
                         capture_output=True, text=True, timeout=10)
    if res.returncode != 0:
        r = subprocess.run(["open", "-a", path], capture_output=True, text=True)
        if r.returncode != 0:
            return {"ok": False, "error": f"could not launch {app_name}"}
    return {"ok": True}

# --------------------------------------------------------------------------
# Process helpers
# --------------------------------------------------------------------------

def _frontmost_pid() -> int | None:
    try:
        res = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get unix id of first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5)
        return int(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None
    except Exception:
        return None


def _frontmost_name() -> str:
    try:
        res = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5)
        return res.stdout.strip() if res.returncode == 0 else "Unknown"
    except Exception:
        return "Unknown"


def _app_name(pid: int) -> str:
    try:
        res = subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to get name of first application process whose unix id is {pid}'],
            capture_output=True, text=True, timeout=5)
        return res.stdout.strip() or "Unknown"
    except Exception:
        return "Unknown"


def _pid_for(app_name: str) -> int | None:
    try:
        res = subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to get unix id of first application process whose name contains "{app_name}"'],
            capture_output=True, text=True, timeout=5)
        return int(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None
    except Exception:
        return None


# ----------------------------------------------------------------------
# Task 11 (Mission 5) — Native Dock & Menu Bar AX introspection
# ----------------------------------------------------------------------

def _ax_menu_titles(menu_bar_el) -> list[str]:
    """Walk one AXMenuBar element → top-level menu titles."""
    titles: list[str] = []
    try:
        for child in _ax_children(menu_bar_el):
            role = _ax_attr(child, "AXRole") or ""
            if "MenuBarItem" in str(role) or "Menu" in str(role):
                t = _ax_attr(child, "AXTitle") or _ax_attr(child, "AXDescription")
                if t:
                    titles.append(str(t))
                else:
                    for sub in _ax_children(child):
                        st = _ax_attr(sub, "AXTitle") or _ax_attr(sub, "AXDescription")
                        if st:
                            titles.append(str(st))
                            break
    except Exception:
        pass
    return titles


def get_menubar_items(app_name: str | None = None) -> list[str]:
    """Top-level menu-bar titles for an app (frontmost when None).

    Uses direct AXUIElementCopyAttributeValue on kAXMenuBarAttribute with
    an AppleScript fallback. Never raises — returns [] on failure.
    """
    try:
        from ApplicationServices import AXUIElementCreateApplication
        pid = _pid_for(app_name) if app_name else _frontmost_pid()
        if pid:
            app_el = AXUIElementCreateApplication(pid)
            mbar = _ax_attr(app_el, "AXMenuBar") or _ax_attr(app_el, "kAXMenuBarAttribute")
            if mbar is not None:
                titles = _ax_menu_titles(mbar)
                if titles:
                    return titles
    except Exception:
        pass
    # AppleScript fallback via System Events.
    try:
        proc = f'application process "{app_name}"' if app_name else \
            "first application process whose frontmost is true"
        script = (f'tell application "System Events" to tell {proc} '
                  'to get name of every menu bar item of menu bar 1')
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=8)
        if res.returncode == 0 and res.stdout.strip():
            return [s.strip() for s in res.stdout.strip().split(", ") if s.strip()]
    except Exception:
        pass
    return []


def get_dock_apps() -> list[str]:
    """Names of apps currently in the Dock.

    Reads the Dock process AX list with a defaults-read fallback.
    Never raises — returns [] on failure.
    """
    try:
        from ApplicationServices import AXUIElementCreateApplication
        pid = _pid_for("Dock")
        if pid:
            dock_el = AXUIElementCreateApplication(pid)
            kids = _ax_attr(dock_el, "AXChildren") or []
            names: list[str] = []
            for list_el in list(kids):
                for item in _ax_children(list_el):
                    t = (_ax_attr(item, "AXTitle") or _ax_attr(item, "AXDescription")
                         or _ax_attr(item, "AXValue"))
                    if t and str(t) not in names:
                        names.append(str(t))
            if names:
                return names
    except Exception:
        pass
    try:
        res = subprocess.run(
            ["defaults", "read", "com.apple.dock", "persistent-apps"],
            capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            import re as _re
            found = _re.findall(r'"CFBundleDisplayName" = "([^"]+)"', res.stdout)
            if found:
                return found
            found = _re.findall(r'/([^/]+)\.app";', res.stdout)
            if found:
                return found
    except Exception:
        pass
    return []


# ----------------------------------------------------------------------
# Task 9 — Zero-overhead perceptual screen diffing
# ----------------------------------------------------------------------

_LAST_FRAME_SIG: list[float] | None = None


def _frame_luma_signature(cg_image, grid: int = 16) -> list[float]:
    """Downsampled luminance signature of a CGImage (grid x grid means)."""
    try:
        from PIL import Image
        w = Quartz.CGImageGetWidth(cg_image)
        h = Quartz.CGImageGetHeight(cg_image)
        row = Quartz.CGImageGetBytesPerRow(cg_image)
        provider = Quartz.CGImageGetDataProvider(cg_image)
        raw = bytes(Quartz.CGDataProviderCopyData(provider))
        img = Image.frombytes("RGBA", (w, h), raw, "raw", ("BGRA", row, 1))
        small = img.convert("L").resize((grid, grid))
        px = list(small.getdata())
        return [v / 255.0 for v in px]
    except Exception:
        return []


def screen_has_changed(threshold: float = 0.02) -> bool:
    """True if the screen changed since the last call (perceptual diff).

    Compares downsampled 16x16 luminance signatures from the in-memory
    CGImage buffer — no disk, no model inference. First call primes the
    baseline and returns True. Never raises (errors → True = safe default
    meaning 'assume changed, run inference').
    """
    global _LAST_FRAME_SIG
    try:
        from Quartz import (
            CGRectNull, CGWindowListCreateImage,
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
            kCGWindowImageDefault,
        )
        cg = CGWindowListCreateImage(
            CGRectNull, kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID, kCGWindowImageDefault)
        if not cg:
            return True
        sig = _frame_luma_signature(cg)
        if not sig:
            return True
        prev = _LAST_FRAME_SIG
        _LAST_FRAME_SIG = sig
        if prev is None or len(prev) != len(sig):
            return True
        diff = sum(abs(a - b) for a, b in zip(prev, sig)) / len(sig)
        return diff >= threshold
    except Exception:
        return True


# ----------------------------------------------------------------------
# Task 10 — Multi-window / multi-app focus switcher
# ----------------------------------------------------------------------

def focus_app_window(app_name: str, window_title_regex: str | None = None) -> dict:
    """Raise an app's window before clicks or grounding.

    Activates the app, then uses AXUIElementPerformAction(kAXRaiseAction)
    on the matching window (regex on AXTitle, or frontmost/first window).
    Falls back to plain `activate` when AX raise is unavailable.
    Never raises — returns {"ok": bool, ...}.
    """
    try:
        import re
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
            AXUIElementPerformAction,
        )
        pid = _pid_for(app_name)
        if pid is None:
            # Try launching by name, then re-resolve.
            subprocess.run(["open", "-a", app_name],
                           capture_output=True, timeout=10)
            time.sleep(0.6)
            pid = _pid_for(app_name)
            if pid is None:
                return {"ok": False, "error": f"app not found: {app_name}"}
        app_el = AXUIElementCreateApplication(pid)
        res = AXUIElementCopyAttributeValue(app_el, "AXWindows", None)
        err, wins = (res if isinstance(res, tuple) else (0, res))
        target = None
        if err == 0 and wins:
            wins = list(wins)
            if window_title_regex:
                rx = re.compile(window_title_regex, re.I)
                for w in wins:
                    t = _ax_attr(w, "AXTitle") or ""
                    if rx.search(t):
                        target = w
                        break
                if target is None:
                    titles = [(_ax_attr(w, "AXTitle") or "?") for w in wins][:8]
                    return {"ok": False, "error": "no window matched",
                            "windows": titles}
            else:
                # Prefer the focused window, else the first.
                res2 = AXUIElementCopyAttributeValue(app_el, "AXFocusedWindow", None)
                err2, fwin = (res2 if isinstance(res2, tuple) else (0, res2))
                target = fwin if err2 == 0 and fwin is not None else (wins[0] if wins else None)
        if target is not None:
            try:
                AXUIElementPerformAction(target, "AXRaise")
            except Exception:
                pass
        subprocess.run(["osascript", "-e",
                        f'tell application "System Events" to set frontmost of first application process whose unix id is {pid} to true'],
                       capture_output=True, timeout=5)
        title = _ax_attr(target, "AXTitle") if target is not None else None
        return {"ok": True, "app": app_name, "window": title or "frontmost"}
    except Exception as e:
        # Last-resort fallback: plain activate.
        try:
            subprocess.run(["osascript", "-e",
                            f'tell application "{app_name}" to activate'],
                           capture_output=True, timeout=10)
            return {"ok": True, "app": app_name, "window": "activate-fallback"}
        except Exception:
            return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    print("cursor:", current_cursor())
    tree = get_ax_tree()
    print("tree:", {k: v for k, v in tree.items() if k != "elements"},
          "| elements:", len(tree.get("elements", [])))
    print("find 'cancel':", find_element(tree, "cancel"))



# ----------------------------------------------------------------------
# Visual UI Grounding via Moondream (Vision-to-Click fallback)
# ----------------------------------------------------------------------

def _in_memory_jpeg(cg_image, quality: float = 0.85) -> bytes:
    """Encode a CGImage to JPEG bytes without touching disk.

    Uses CGImageDestinationCreateWithData → ImageIO in-memory buffer.
    Falls back to PIL if the ImageIO path is unavailable.
    """
    try:
        from CoreFoundation import CFDataCreateMutable, CFDataGetBytePtr, CFDataGetLength  # type: ignore
        buf = CFDataCreateMutable(None, 0)
        dest = Quartz.CGImageDestinationCreateWithData(buf, "public.jpeg", 1, None)
        if dest:
            props = {"{JPG}": {"CompressionQuality": float(quality)}}
            try:
                import objc as _objc
                opts = _objc.python_dict_to_ns(props)
            except Exception:
                opts = None
            Quartz.CGImageDestinationAddImage(dest, cg_image, opts)
            if Quartz.CGImageDestinationFinalize(dest):
                n = CFDataGetLength(buf)
                ptr = CFDataGetBytePtr(buf)
                return bytes(bytearray(ptr[i] for i in range(n)))
    except Exception:
        pass
    # PIL fallback (still in-memory)
    try:
        from PIL import Image
        import io
        w = Quartz.CGImageGetWidth(cg_image)
        h = Quartz.CGImageGetHeight(cg_image)
        row = Quartz.CGImageGetBytesPerRow(cg_image)
        provider = Quartz.CGImageGetDataProvider(cg_image)
        raw = bytes(Quartz.CGDataProviderCopyData(provider))
        img = Image.frombytes("RGBA", (w, h), raw, "raw", ("BGRA", row, 1))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=int(quality * 100))
        return out.getvalue()
    except Exception:
        raise RuntimeError("in-memory JPEG encode failed")


def capture_screen_base64() -> tuple[str, int, int]:
    """Captures the display using Quartz and returns (base64_jpeg, width, height).

    Task 5: zero-disk fast path — CGImage → CGImageDestination in-memory JPEG
    (~40ms). Falls back to `screencapture` tmp-file path only if the in-memory
    encode fails.
    """
    import base64
    from Quartz import (
        CGRectNull,
        CGWindowListCreateImage,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        kCGWindowImageDefault,
        CGImageGetWidth,
        CGImageGetHeight
    )

    cg_image = CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        kCGWindowImageDefault
    )
    if not cg_image:
        raise RuntimeError("Failed to capture screen image via Quartz")

    w = CGImageGetWidth(cg_image)
    h = CGImageGetHeight(cg_image)

    try:
        jpeg = _in_memory_jpeg(cg_image)
        return base64.b64encode(jpeg).decode("utf-8"), w, h
    except Exception:
        pass  # fall through to legacy disk path

    # Legacy fallback: screencapture temporary buffer
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(["screencapture", "-x", "-t", "jpg", "-m", tmp_path], check=True, timeout=3)
        with open(tmp_path, "rb") as f:
            b64_str = base64.b64encode(f.read()).decode("utf-8")
        return b64_str, w, h
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def capture_perf() -> dict:
    """Benchmark the Task-5 capture path (integration lane can log this)."""
    try:
        t0 = time.time()
        b64, w, h = capture_screen_base64()
        ms = round((time.time() - t0) * 1000, 1)
        return {"ok": True, "ms": ms, "bytes": len(b64), "w": w, "h": h}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def screen_bounds() -> tuple[float, float]:
    """Return the primary monitor's logical size in screen points (w, h).

    Single source of truth for Task 4: Moondream returns normalized
    coordinates, and Retina pixel dimensions must be halved to convert them
    into the point space Quartz mouse events use. Reads live via
    Quartz.CGDisplayBounds(CGMainDisplayID()) so external/Retina display
    swaps are picked up without hardcoded magic numbers.
    Falls back to the screencapture heuristic when Quartz is unavailable.
    """
    try:
        if _QUARTZ:
            r = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            w, h = float(r.size.width), float(r.size.height)
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    try:
        _, w, h = capture_screen_base64()
        return float(w), float(h)
    except Exception:
        return 0.0, 0.0


def _parse_vision_coords(response_text: str,
                         screen_w: float, screen_h: float) -> tuple[float, float] | None:
    """Parse a moondream response into absolute screen points.

    Never raises: empty / non-JSON / garbage input returns None.
    Normalized values are clamped to [0, 1] so a hallucinating model can
    never fling the cursor off-screen. Handles three formats:
      1. {"x": 0.5, "y": 0.5} JSON object (primary)
      2. {"x": 500, "y": 350} pixel JSON (forward-compat per spec)
      3. [ymin, xmin, ymax, xmax] box (spec-bullet alternate)
      4. bare "83 397" pixel pair (spec-bullet alternate)

    Scaling uses screen_bounds(): when the captured pixel dimensions exceed
    1.5x the live logical bounds (Retina 2x), normalized coords are scaled
    against the logical size — no hardcoded thresholds.
    """
    import re

    if not response_text or not response_text.strip():
        return None

    live_w, live_h = screen_bounds()
    # Retina factor: captured pixels vs live logical points.
    fx = (screen_w / live_w) if live_w > 0 and screen_w > live_w * 1.5 else 1.0
    fy = (screen_h / live_h) if live_h > 0 and screen_h > live_h * 1.5 else 1.0
    scale_x = screen_w / fx if fx > 1.0 else screen_w
    scale_y = screen_h / fy if fy > 1.0 else screen_h

    def _to_points(nx: float, ny: float) -> tuple[float, float] | None:
        try:
            nx_f, ny_f = float(nx), float(ny)
        except (TypeError, ValueError):
            return None
        if not (nx_f == nx_f and ny_f == ny_f):  # NaN guard
            return None
        # Pixel-format detection: values > 1.5 on a large screen are pixels.
        if (nx_f > 1.5 or ny_f > 1.5) and screen_w > 100 and screen_h > 100:
            if 0 <= nx_f <= screen_w and 0 <= ny_f <= screen_h:
                return float(nx_f), float(ny_f)
            return None
        nx_c = min(1.0, max(0.0, nx_f))
        ny_c = min(1.0, max(0.0, ny_f))
        return nx_c * scale_x, ny_c * scale_y

    text = response_text.strip()

    # 1/2. JSON object with x/y (normalized or pixel)
    match = re.search(r'\{.*"x"\s*:\s*([0-9.\-]+)\s*,\s*"y"\s*:\s*([0-9.\-]+).*\}',
                      text, re.DOTALL)
    if match:
        pts = _to_points(match.group(1), match.group(2))
        if pts:
            return pts

    # 3. Alternative format [ymin, xmin, ymax, xmax]
    box_match = re.search(r'\[\s*([0-9.\-]+)\s*,\s*([0-9.\-]+)\s*,'
                          r'\s*([0-9.\-]+)\s*,\s*([0-9.\-]+)\s*\]', text)
    if box_match:
        try:
            ymin, xmin, ymax, xmax = map(float, box_match.groups())
        except (TypeError, ValueError):
            return None
        return _to_points((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)

    # 4. Bare pixel pair "83 397" (spec forward-compat, absolute pixels)
    bare = re.search(r'^\s*([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s*$', text)
    if bare:
        try:
            px, py = float(bare.group(1)), float(bare.group(2))
        except (TypeError, ValueError):
            return None
        if 0 <= px <= screen_w and 0 <= py <= screen_h:
            return px, py
        return None

    return None


def find_element_by_vision(description: str, ollama_url: str = "http://localhost:11434") -> tuple[float, float] | None:
    """Ground a visual target description into screen coordinates (x, y).

    Primary: moondream:latest via Ollama. Task 9 gate: callers that poll
    should check screen_has_changed() first to skip redundant inferences.

    Task 15: when moondream's response is unparseable (or Ollama is down),
    falls back to ANE/OCR text grounding (find_text_ocr) before giving up.
    """
    import json
    import urllib.request
    import re

    try:
        b64_img, screen_w, screen_h = capture_screen_base64()
    except Exception as e:
        print(f"[Vision Grounding Error]: Screen capture failed: {e}")
        return None

    prompt = (
        f"Detect the coordinates of this visual UI element: '{description}'. "
        f"Output the normalized center point as JSON in this format: {{\"x\": 0.5, \"y\": 0.5}} "
        f"where coordinates range from 0.0 to 1.0."
    )

    req_data = json.dumps({
        "model": "moondream:latest",
        "prompt": prompt,
        "images": [b64_img],
        "stream": False
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{ollama_url}/api/generate",
        data=req_data,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            response_text = data.get("response", "")

            # Delegate to the hardened parser: handles JSON, box, bare-pair,
            # garbage, and out-of-range values without ever raising.
            coords = _parse_vision_coords(response_text or "", screen_w, screen_h)
            if coords:
                return coords
            print(f"[Vision Grounding]: unparseable moondream response: "
                  f"{(response_text or '')[:120]!r}")
            return None

    except Exception as e:
        print(f"[Vision Grounding Error]: Ollama moondream query failed: {e}")

    return None


def visual_click(description: str, clicks: int = 1) -> dict:
    """Attempts to visually locate an element via Moondream and clicks it with Bezier smoothing."""
    try:
        coords = find_element_by_vision(description)
        if not coords:
            return {"ok": False, "error": f"Could not visually ground '{description}' with Moondream"}
        x, y = coords
        r_move = move_to(x, y, curved=True, duration=0.25)
        if not r_move.get("ok"):
            return {"ok": False, "error": f"move failed: {r_move.get('error')}"}
        r_click = click(x, y, clicks=clicks)
        if not r_click.get("ok"):
            return {"ok": False, "error": f"click failed: {r_click.get('error')}"}
        return {"ok": True, "target": description, "clicked_at": (x, y)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

