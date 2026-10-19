#!/usr/bin/env python3
"""Single source of truth for JARVIS2 paths, models and limits.

Every root-level pillar module reads its configuration from HERE, so the
whole system agrees on ONE vault, ONE watched project and ONE set of
model names. Import this instead of hardcoding a path:

    from jarvis_config import VAULT_DIR, LLM_MODEL, ROOT

Everything can be overridden with an environment variable, so the same
code runs on any machine without edits:

    JARVIS_VAULT        path to the Obsidian vault   (default ~/Vault)
    JARVIS_HACKTIVATE   project the guardian watches (default <parent>/hacktivate)
    OLLAMA_URL          local Ollama server          (default http://localhost:11434)
    LLM_API_BASE        OpenAI-compatible endpoint   (default $OLLAMA_URL/v1)
    LLM_MODEL           chat model                   (default llama3.2:3b)
    JARVIS_VISION_MODEL vision model                 (default moondream:latest)
    JARVIS_EMBED_MODEL  embedding model              (default qwen3-embedding:8b)
    JARVIS_MAX_HISTORY  conversation turns kept      (default 40)
    JARVIS_MAX_WORKERS  subagent worker concurrency  (default 3)
"""
from __future__ import annotations

import os
from pathlib import Path

# The repo root — the folder holding this file.
ROOT = Path(__file__).resolve().parent

# ── Watched / user data locations ────────────────────────────────────────────
# The Obsidian second brain. Path.home() keeps the historical ~/Vault default
# working while being portable across machines and usernames.
VAULT_DIR = Path(os.environ.get("JARVIS_VAULT") or Path.home() / "Vault")
VAULT_MEMORY = VAULT_DIR / "Memory"

# The project the ambient guardian watches for builds, compiler errors and
# git activity. Default preserves the original sibling-folder layout.
HACKTIVATE_DIR = Path(
    os.environ.get("JARVIS_HACKTIVATE") or ROOT.parent / "hacktivate"
)

# ── Local LLM ────────────────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
LLM_API_BASE = os.environ.get("LLM_API_BASE", OLLAMA_URL + "/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
VISION_MODEL = os.environ.get("JARVIS_VISION_MODEL", "moondream:latest")
EMBED_MODEL = os.environ.get("JARVIS_EMBED_MODEL", "qwen3-embedding:8b")

# ── Runtime limits (one tuning place for the whole system) ───────────────────
MAX_MESSAGE_HISTORY = int(os.environ.get("JARVIS_MAX_HISTORY", "40"))
MAX_WORKERS = int(os.environ.get("JARVIS_MAX_WORKERS", "3"))
CLEANUP_INTERVAL = int(os.environ.get("JARVIS_CLEANUP_INTERVAL", "300"))

# ── Screen recall (pillar 4) tunables ─────────────────────────────────────────
SCREEN_CAPTURE_INTERVAL = int(os.environ.get("JARVIS_SCREEN_INTERVAL", "15"))
# Rolling retention: frames older than this are pruned on every ingest.
SCREEN_RETENTION_DAYS = int(os.environ.get("JARVIS_SCREEN_RETENTION_DAYS", "7"))
# Hard caps that trigger pruning even for fresh frames: row count and DB bytes.
SCREEN_MAX_FRAMES = int(os.environ.get("JARVIS_SCREEN_MAX_FRAMES", "20000"))
SCREEN_MAX_DB_MB = int(os.environ.get("JARVIS_SCREEN_MAX_DB_MB", "512"))