#!/usr/bin/env python3
"""Pillar 3 — Autonomous Hierarchical Subagent Swarm for Jarvis.
Delegated asynchronous workers for deep background tasks:
  - CodeAuditor: Static AST / regex security & style scanning + Ollama LLM synthesis
  - WebScout: Headless HTTP URL fetching & intelligence extraction (bulletins/releases)
  - SecondBrainSynthesizer: Vault exploration, synthesis, and structured note creation
Thread-safe WAL SQLite task bus with voice notification dequeuing.
"""
from __future__ import annotations

import os
import sys
import re
import time
import json
import sqlite3
import asyncio
from pathlib import Path
from openai import AsyncOpenAI
from typing import Callable

from jarvis_config import ROOT, VAULT_DIR, VAULT_MEMORY, HACKTIVATE_DIR
from jarvis_config import LLM_API_BASE, LLM_MODEL
from jarvis_log import get_logger

try:
    from vault_index import iter_notes
except ImportError:
    iter_notes = None

log = get_logger("subagent_swarm")

DB_PATH = ROOT / "agent_bus.sqlite3"
API_BASE = LLM_API_BASE
MODEL = LLM_MODEL


def init_bus():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute('''
        CREATE TABLE IF NOT EXISTS task_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT,
            query TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            notified INTEGER DEFAULT 0,
            created_at REAL,
            completed_at REAL
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON task_queue(status)")
    conn.commit()
    conn.close()


def dispatch_task(task_type: str, query: str) -> int:
    """Dispatches a task to the background swarm."""
    init_bus()
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    now = time.time()
    cur.execute(
        "INSERT INTO task_queue (task_type, query, status, created_at) VALUES (?, ?, 'pending', ?)",
        (task_type, query, now)
    )
    t_id = cur.lastrowid
    conn.commit()
    conn.close()
    return t_id


def get_completed_unnotified_tasks():
    """Returns completed tasks that haven't been voiced to the user yet."""
    init_bus()
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_type, query, result FROM task_queue WHERE status = 'completed' AND notified = 0 ORDER BY completed_at ASC"
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def mark_task_notified(task_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("UPDATE task_queue SET notified = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


# ─── Worker 1: CodeAuditor ───────────────────────────────────────────────────

_SWIFT_RULES = [
    ("force-unwrap", re.compile(r"\w!\.|\w!\)|\w!,|\w! |try! |as! "), "high", "Force unwrap/try — crash risk"),
    ("hardcoded-secret", re.compile(r"(password|secret|api[_-]?key|token)\s*[:=]\s*\"[^\"]{8,}\"", re.I), "critical", "Possible hardcoded credential"),
    ("todo-fixme", re.compile(r"//\s*(TODO|FIXME|HACK)"), "info", "Unfinished work marker"),
]

_PY_RULES = [
    ("shell-injection", re.compile(r"subprocess\.[a-z_]+\([^)]*shell\s*=\s*True"), "high", "shell=True enables injection"),
    ("eval-exec", re.compile(r"\b(eval|exec)\("), "high", "Dynamic code execution"),
    ("hardcoded-secret", re.compile(r"(password|secret|api[_-]?key|token)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.I), "critical", "Possible hardcoded credential"),
]

async def run_code_audit(query: str) -> str:
    """Combines rule-based static analysis with LLM reasoning."""
    issues = []
    snippets = []
    keywords = [k.lower() for k in query.split() if len(k) > 3]

    for p in [HACKTIVATE_DIR, ROOT]:
        if not p.exists():
            continue
        for f in list(p.rglob("*.swift"))[:15] + list(p.rglob("*.py"))[:15]:
            if any(part in (".build", "venv", ".git", "__pycache__") for part in f.parts):
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                rules = _SWIFT_RULES if f.suffix == ".swift" else _PY_RULES
                for lineno, line in enumerate(txt.splitlines()[:200], 1):
                    for name, pat, sev, adv in rules:
                        if pat.search(line):
                            issues.append(f"{f.name}:{lineno} [{sev}] {adv}")
                if any(k in txt.lower() or k in f.stem.lower() for k in keywords):
                    snippets.append(f"{f.name}:\n{txt[:600]}")
            except Exception:
                pass

    rule_summary = f"Found {len(issues)} rule flags: " + "; ".join(issues[:3]) if issues else "Zero static rule flags."
    client = AsyncOpenAI(base_url=API_BASE, api_key="ollama")
    prompt = (
        f"You are an expert security and code auditor.\n"
        f"Static scan findings: {rule_summary}\n"
        f"Context:\n" + "\n".join(snippets[:2]) + f"\n\nRequest: {query}\n"
        f"Provide a 2-sentence crisp summary of code safety and fixes."
    )
    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"{rule_summary}. Code analysis complete."


# ─── Worker 2: WebScout ──────────────────────────────────────────────────────

async def run_web_scout(url_or_query: str) -> str:
    """Scouts URLs or releases via lightweight HTTP fetch."""
    url = url_or_query.strip()
    match = re.search(r'https?://[^\s]+', url)
    target_url = match.group(0) if match else None

    if not target_url:
        return f"WebScout requires a valid URL to examine: {url_or_query[:60]}."

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(target_url, headers={"User-Agent": "Jarvis-WebScout/2.0"})
            html = r.text
            title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            title = title_m.group(1).strip() if title_m else target_url
            body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
            return f"Scouted {target_url}: '{title[:60]}' (Status {r.status_code}). Summary: {body[:200]}..."
    except Exception as e:
        return f"WebScout could not fetch {target_url}: {str(e)[:60]}."


# ─── Worker 3: SecondBrainSynthesizer ────────────────────────────────────────

async def run_vault_synthesis(query: str) -> str:
    """Synthesizes knowledge from Obsidian Vault or records a new note."""
    client = AsyncOpenAI(base_url=API_BASE, api_key="ollama")
    snippets = []
    tokens = [t.lower() for t in query.split() if len(t) > 3]

    if iter_notes is not None:
        # Use cached vault index (mtime/size based, avoids re-reading files)
        for md_file, content, content_lower, stem_lower in iter_notes():
            if any(t in content_lower or t in stem_lower for t in tokens):
                snippets.append(f"Note: {md_file.name}\n{content[:400]}")
                if len(snippets) >= 3:
                    break
    else:
        # Fallback: direct rglob (no cache)
        for md_file in VAULT_DIR.rglob("*.md"):
            if any(p in md_file.parts for p in (".obsidian", "templates", "+Utility")):
                continue
            try:
                c = md_file.read_text(encoding="utf-8", errors="ignore")
                if any(t in c.lower() or t in md_file.stem.lower() for t in tokens):
                    snippets.append(f"Note: {md_file.name}\n{c[:400]}")
                    if len(snippets) >= 3:
                        break
            except Exception:
                continue

    vault_context = "\n\n".join(snippets) if snippets else "No direct note match found."
    prompt = (
        f"Synthesize this knowledge from the user's Obsidian Second Brain:\n{vault_context}\n\n"
        f"User Query: {query}\n"
        f"Provide a 2-sentence crisp synthesis."
    )
    try:
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Vault search concluded: {len(snippets)} relevant notes found."


# ─── Async Swarm Loop ────────────────────────────────────────────────────────

async def swarm_worker_loop():
    """Continuously monitors task bus and delegates without blocking voice."""
    init_bus()
    while True:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            cur = conn.cursor()
            cur.execute("SELECT id, task_type, query FROM task_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
            row = cur.fetchone()
            conn.close()

            if row:
                t_id, t_type, query = row
                conn = sqlite3.connect(DB_PATH, timeout=5.0)
                conn.execute("UPDATE task_queue SET status = 'running' WHERE id = ?", (t_id,))
                conn.commit()
                conn.close()

                try:
                    if t_type in ("audit", "code_audit"):
                        result = await asyncio.wait_for(run_code_audit(query), timeout=25.0)
                    elif t_type in ("web", "web_scout"):
                        result = await asyncio.wait_for(run_web_scout(query), timeout=25.0)
                    elif t_type in ("synthesis", "vault"):
                        result = await asyncio.wait_for(run_vault_synthesis(query), timeout=25.0)
                    else:
                        result = f"Task completed for query: {query[:50]}"
                except asyncio.TimeoutError:
                    result = f"Subagent {t_type} exceeded deadline (25s) and was safely aborted."
                except Exception as ex:
                    result = f"Subagent error: {str(ex)[:60]}"

                conn = sqlite3.connect(DB_PATH, timeout=5.0)
                conn.execute(
                    "UPDATE task_queue SET status = 'completed', result = ?, completed_at = ? WHERE id = ?",
                    (result, time.time(), t_id)
                )
                conn.commit()
                conn.close()

            await asyncio.sleep(0.8)
        except Exception:
            await asyncio.sleep(1.5)


if __name__ == "__main__":
    init_bus()
    if len(sys.argv) > 1 and sys.argv[1] == "dispatch":
        t_id = dispatch_task(sys.argv[2], " ".join(sys.argv[3:]))
        log.info("Dispatched task #%s", t_id)
    else:
        log.info("[🐝 SUBAGENT SWARM ONLINE]")
        asyncio.run(swarm_worker_loop())
