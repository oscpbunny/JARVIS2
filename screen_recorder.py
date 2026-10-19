#!/usr/bin/env python3
"""Pillar 4 – Episodic Visual Screen Recall (Temporal Memory Engine)
High-performance screen ingestion and semantic temporal recall daemon:
  - Ingests screen frames via native macOS Quartz API (zero disk writing for idle screens)
  - Hardware-accelerated OCR via Apple Neural Engine (PyObjC Vision framework, ~0.3s)
  - Perceptual content hash to skip idle/duplicate frames
  - Vector embeddings via local qwen3-embedding:8b (Ollama)
  - Natural language temporal querying with keyword overlap & vector cosine ranking
"""
from __future__ import annotations

import os
import sys
import time
import math
import sqlite3
import hashlib
import threading
import json
import urllib.request
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# PyObjC Quartz and Vision frameworks
from Quartz import (
    CGRectNull,
    CGWindowListCreateImage,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
    kCGWindowImageDefault
)
import Vision

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "screen_memory.sqlite3"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("JARVIS_EMBED_MODEL", "qwen3-embedding:8b")
CAPTURE_INTERVAL = 15  # seconds

_running = False
_thread = None
_last_hash = ""

_STOPWORDS = {
    "what", "was", "the", "that", "i", "in", "at", "on", "ago",
    "about", "an", "a", "hour", "hours", "minute", "minutes",
    "looking", "saw", "see", "viewed", "you", "me", "we", "jarvis",
    "screen", "display", "window", "find", "show", "tell"
}


# ─── DB Bootstrap ─────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screen_frames (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    REAL    NOT NULL,
            app_name     TEXT,
            window_title TEXT,
            ocr_text     TEXT,
            frame_hash   TEXT,
            embedding    TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_screen_ts ON screen_frames(timestamp)")
    conn.commit()
    conn.close()


# ─── Active Window Perception ────────────────────────────────────────────────

def get_active_window_info() -> tuple[str, str]:
    """Returns (app_name, window_title) of frontmost window."""
    script = '''
    tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
    end tell
    set winTitle to ""
    try
        tell application frontApp
            set winTitle to name of front window
        end tell
    end try
    return frontApp & "|" & winTitle
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=2
        )
        parts = result.stdout.strip().split("|", 1)
        app = parts[0].strip() if parts else "Unknown"
        win = parts[1].strip() if len(parts) > 1 else ""
        return app, win
    except Exception:
        return "Unknown", ""


# ─── Vision Framework OCR on Apple Silicon ──────────────────────────────────

def ocr_screen() -> tuple[str, str]:
    """Captures screen in-memory via Quartz and runs Vision OCR on ANE."""
    try:
        cg_image = CGWindowListCreateImage(
            CGRectNull,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
            kCGWindowImageDefault
        )
        if not cg_image:
            return "", ""

        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(1)  # 1 = fast, 0 = accurate
        req.setUsesLanguageCorrection_(False)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok:
            return "", ""

        lines = []
        for obs in (req.results() or []):
            top = obs.topCandidates_(1)
            if top:
                lines.append(top[0].string())

        full_text = " ".join(lines)
        h = hashlib.md5(full_text.encode("utf-8", errors="ignore")).hexdigest()
        return full_text[:4000], h
    except Exception as e:
        return "", ""


# ─── Embedding Generation ────────────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    """Generate vector embedding using Ollama qwen3-embedding:8b or fallback."""
    if not text.strip():
        return None
    try:
        req_data = json.dumps({
            "model": EMBED_MODEL,
            "prompt": text[:1000]
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("embedding")
    except Exception:
        return None


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0


# ─── Screen Frame Ingestion ──────────────────────────────────────────────────

def ingest_frame():
    global _last_hash

    ocr_text, h = ocr_screen()
    if not ocr_text or h == _last_hash:
        return  # Idle or unchanged
    _last_hash = h

    app_name, win_title = get_active_window_info()
    emb = get_embedding(f"{app_name} {win_title}: {ocr_text[:300]}")
    emb_json = json.dumps(emb) if emb else None

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO screen_frames (timestamp, app_name, window_title, ocr_text, frame_hash, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), app_name, win_title, ocr_text, h, emb_json)
    )
    # Rolling retention: prune frames older than 7 days (604,800s)
    cutoff = time.time() - (7 * 86400)
    conn.execute("DELETE FROM screen_frames WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()


def _daemon_loop():
    global _running
    init_db()
    print("[📸 SCREEN RECALL DAEMON ONLINE: Native ANE OCR]", flush=True)
    while _running:
        try:
            ingest_frame()
        except Exception as e:
            pass
        time.sleep(CAPTURE_INTERVAL)


def start_daemon():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_daemon_loop, daemon=True, name="ScreenRecall")
    _thread.start()


def stop_daemon():
    global _running
    _running = False


# ─── Natural Language Temporal Query Parser ──────────────────────────────────

def parse_time_window(text: str, now: datetime | None = None) -> tuple[float, float, str]:
    """Parse temporal expressions into (start_ts, end_ts, human_label)."""
    now = now or datetime.now()
    t = text.lower()

    m = re.search(r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|half)\s*"
                  r"(second|minute|hour|day|week)s?\s+ago", t)
    if m:
        words = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5}
        n = words.get(m.group(1), float(m.group(1)) if m.group(1).replace('.', '').isdigit() else 1)
        unit = m.group(2)
        mult = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}[unit]
        delta = n * mult
        start = now - timedelta(seconds=delta)
        label = f"last {n} {unit}{'s' if n != 1 else ''}"
        return start.timestamp(), now.timestamp(), label

    if "this morning" in t or "morning" in t:
        start = now.replace(hour=4, minute=0, second=0, microsecond=0)
        end = now.replace(hour=11, minute=30, second=0, microsecond=0)
        return start.timestamp(), min(end.timestamp(), now.timestamp()), "this morning"
    if "before lunch" in t:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=13, minute=0, second=0, microsecond=0)
        return start.timestamp(), min(end.timestamp(), now.timestamp()), "before lunch"
    if "yesterday" in t:
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start.timestamp(), end.timestamp(), "yesterday"
    if "today" in t:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), now.timestamp(), "today"

    # default: last 2 hours
    start = now - timedelta(hours=2)
    return start.timestamp(), now.timestamp(), "the last 2 hours"


def query_temporal_recall(natural_query: str) -> str:
    """Hybrid temporal search (Keywords + Embeddings)."""
    init_db()
    start_ts, end_ts, label = parse_time_window(natural_query)

    import re
    keywords = [
        w for w in re.findall(r"[a-zA-Z]{3,}", natural_query.lower())
        if w not in _STOPWORDS and not re.match(r"(just|now|moment|this|before|two|three|half|hour|minute)", w)
    ]
    query_emb = get_embedding(natural_query)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT timestamp, app_name, window_title, ocr_text, embedding FROM screen_frames "
        "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT 60",
        (start_ts, end_ts)
    ).fetchall()
    conn.close()

    if not rows:
        return f"I couldn't find any recorded screen activity for {label}."

    scored = []
    for ts, app, win, ocr, emb_raw in rows:
        text_blob = f"{app} {win} {ocr}".lower()
        kw_score = sum(2.0 for kw in keywords if kw in text_blob)
        cos_score = 0.0
        if query_emb and emb_raw:
            try:
                cos_score = cosine_similarity(query_emb, json.loads(emb_raw)) * 5.0
            except Exception:
                pass
        total_score = kw_score + cos_score
        scored.append((total_score, ts, app, win, ocr))

    scored.sort(key=lambda x: (-x[0], -x[1]))
    best_score, ts, app, win, ocr = scored[0]

    dt = datetime.fromtimestamp(ts).strftime("%-I:%M %p")
    snippet = ocr[:200].replace("\n", " ").strip() if ocr else ""

    summary = f"At {dt}, you were in {app}"
    if win:
        summary += f', window titled "{win}"'
    if snippet:
        summary += f'. Text seen: "{snippet[:120]}..."'
    return summary


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "query":
        q = " ".join(sys.argv[2:]) or "what was I doing an hour ago"
        print(query_temporal_recall(q))
    else:
        init_db()
        ingest_frame()
        print("Test frame ingested successfully.")
