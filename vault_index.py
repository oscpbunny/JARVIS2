#!/usr/bin/env python3
"""Vault mtime cache — avoids re-reading every *.md on every voice turn.

Problem: obsidian_rag.search_vault() + subagent_swarm run VAULT_DIR.rglob("*.md")
and read_text() on EVERY turn. Blocks the voice loop.

This module is ADDITIVE only (no edits to callers required yet):
  from vault_index import iter_notes, stats

- iter_notes() yields (Path, content, content_lower, stem_lower) using an
  in-memory {(mtime, size) -> content} cache. Unchanged files cost one
  stat(), not read. content is ORIGINAL case (for snippets); content_lower
  + stem_lower are for scoring. Storing the Path (not just filename) keeps
  nested notes (Memory/foo.md) resolvable without re-reads.
- Never raises: vault missing / unreadable file -> yields nothing.
- clear() resets cache (tests, vault moved).

Usage (owner lane):
  from vault_index import iter_notes
  for md_path, content, content_lower, stem_lower in iter_notes(): ...
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, Tuple

try:
    from jarvis_config import VAULT_DIR
except ImportError:  # standalone use without config module
    from pathlib import Path as _P
    VAULT_DIR = _P.home() / "Vault"

_SKIP_PARTS = frozenset({".obsidian", "templates", "+Utility", ".config", ".trash"})

# path-str -> (mtime, size, content, content_lower, stem_lower)
_CACHE: dict[str, tuple[float, int, str, str, str]] = {}
_HITS = 0
_MISSES = 0


def clear() -> None:
    """Reset cache + counters (tests / vault moved)."""
    _CACHE.clear()
    global _HITS, _MISSES
    _HITS = 0
    _MISSES = 0


def stats() -> dict:
    """Cache introspection for health probe / tests. Never raises."""
    return {"entries": len(_CACHE), "hits": _HITS, "misses": _MISSES}


def iter_notes() -> Iterator[Tuple[Path, str, str, str]]:
    """Yield (path, content, content_lower, stem_lower) for vault notes.

    Unchanged files served from cache (stat only). Missing vault -> empty.
    Corrupt/unreadable file -> skipped, cached as empty so we don't retry
    disk I/O every turn (invalidated when mtime/size changes).

    4-tuple rationale (2026-10-19, with Kilo): the index previously yielded
    only content_lower, forcing obsidian_rag to re-read the file for an
    original-case snippet via (VAULT_DIR / filename) — wrong for nested notes
    (Memory/foo.md) and an extra disk I/O per hit. Yielding content + full
    Path removes both problems.
    """
    global _HITS, _MISSES
    try:
        if not VAULT_DIR.exists():
            return
        files = list(VAULT_DIR.rglob("*.md"))
    except Exception:
        return
    for md_file in files:
        try:
            if any(part in md_file.parts for part in _SKIP_PARTS):
                continue
            try:
                st = md_file.stat()
            except OSError:
                continue
            key = str(md_file)
            cached = _CACHE.get(key)
            if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                _HITS += 1
                yield md_file, cached[2], cached[3], cached[4]
                continue
            _MISSES += 1
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""
            stem_lower = md_file.stem.lower()
            content_lower = content.lower()
            # cap cached string to avoid unbounded RAM if vault has huge files
            if len(content) > 200_000:
                content = content[:200_000]
                content_lower = content_lower[:200_000]
            _CACHE[key] = (st.st_mtime, st.st_size, content, content_lower, stem_lower)
            yield md_file, content, content_lower, stem_lower
        except Exception:
            continue


if __name__ == "__main__":
    n = sum(1 for _ in iter_notes())
    try:
        from jarvis_log import get_logger
        log = get_logger("vault_index")
    except Exception:
        import logging as _logging
        log = _logging.getLogger("vault_index")
    log.info("vault=%s notes=%s %s", VAULT_DIR, n, stats())
