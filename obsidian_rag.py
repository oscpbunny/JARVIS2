#!/usr/bin/env python3
"""Obsidian Vault Real-Time Semantic Search & Context Injector for Jarvis.
Filters out noise, short command words, and only injects high-confidence context.
"""
import os
import re
from pathlib import Path

from jarvis_config import VAULT_DIR

STOPWORDS = {
    "open", "launch", "start", "close", "quit", "tab", "new", "window", "draw",
    "canvas", "chrome", "safari", "resolve", "davinci", "terminal", "editor",
    "please", "can", "you", "the", "and", "this", "that", "with", "what", "how",
    "who", "when", "where", "why", "are", "for", "from", "now", "just", "make",
    "tell", "show", "help", "switch", "look"
}

def clean_text(text: str) -> str:
    text = re.sub(r'^---[\s\S]*?---\n', '', text)
    text = re.sub(r'\[\[(.*?)\]\]', r'\1', text)
    return text.strip()

def search_vault(query: str, max_results: int = 2) -> str:
    """Fast search across the configured vault (jarvis_config.VAULT_DIR) - strictly requires high-confidence content tokens."""
    if not VAULT_DIR.exists():
        return ""

    tokens = [t.lower() for t in re.findall(r'[a-zA-Z]{3,}', query)]
    meaningful_tokens = [t for t in tokens if t not in STOPWORDS]
    
    # Do not trigger vault search on generic control phrases like "new tab", "open chrome"
    if not meaningful_tokens:
        return ""

    scored_notes = []

    for md_file in VAULT_DIR.rglob("*.md"):
        if any(part in md_file.parts for part in (".obsidian", "templates", "+Utility", ".config")):
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        content_lower = content.lower()
        stem_lower = md_file.stem.lower()
        
        # Give massive weight if title matches the query concept
        title_hits = sum(stem_lower.count(token) for token in meaningful_tokens)
        body_hits = sum(content_lower.count(token) for token in meaningful_tokens)
        
        score = (title_hits * 10) + body_hits

        # Minimum score threshold to prevent irrelevant injections
        if score >= 5:
            scored_notes.append((score, md_file.name, content))

    scored_notes.sort(key=lambda x: x[0], reverse=True)
    top_notes = scored_notes[:max_results]

    if not top_notes:
        return ""

    snippets = []
    for score, filename, content in top_notes:
        cleaned = clean_text(content)
        first_paragraph = cleaned[:300].replace("\n", " ")
        snippets.append(f"Note: {filename}\nSnippet: {first_paragraph}")

    return "\n\n".join(snippets)

if __name__ == "__main__":
    print("Testing 'new tab':", repr(search_vault("new tab")))
    print("Testing 'neuroplasticity':", repr(search_vault("neuroplasticity")))
