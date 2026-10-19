"""Performance & Memory Optimization Module for JARVIS.

Implements:
- Memory-efficient message history management
- Non-blocking TTS (async)
- Optimized Ollama API calls with timeouts
- Background worker queue cleanup
- Periodic temp file cleanup
"""

import gc
import time
import threading
import concurrent.futures
from typing import Optional

# One config for the whole system: ROOT was the missing name that made
# cleanup_resources raise NameError; the limits are shared, not re-declared.
from jarvis_config import ROOT, CLEANUP_INTERVAL, MAX_MESSAGE_HISTORY, MAX_WORKERS

# ─── In-Memory State for Optimization ────────────────────────────────────────

_message_history: list = []
_last_cleanup_time = 0.0
_cleanup_done = False

# ─── Thread Pool Singleton ───────────────────────────────────────────────────

_thread_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
_thread_pool_lock = threading.Lock()

def get_thread_pool():
    """Return the bounded thread pool (singleton; safe to call from anywhere)."""
    global _thread_pool
    if _thread_pool is None:
        with _thread_pool_lock:
            if _thread_pool is None:
                _thread_pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=MAX_WORKERS,  # Shared limit from jarvis_config
                    thread_name_prefix="jarvis-thread",
                )
    return _thread_pool

def release_thread_pool():
    """Shut the pool down (call at exit)."""
    global _thread_pool
    if _thread_pool is not None:
        _thread_pool.shutdown(wait=False)
        _thread_pool = None


# ─── Message History Trimming ────────────────────────────────────────────────

def trim_message_history(messages: list, max_keep: int = MAX_MESSAGE_HISTORY) -> list:
    """Trim conversation history to keep it bounded.

    Keeps the system message plus the most recent turns. Prevents
    unbounded memory growth during long-running sessions. Returns a
    new list; does not mutate the input.
    """
    if not messages:
        return []
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    keep = rest[-max_keep:] if len(rest) > max_keep else rest
    return system + keep

def cleanup_resources():
    """Periodic resource cleanup to manage memory."""
    global _last_cleanup_time, _cleanup_done

    now = time.time()
    if now - _last_cleanup_time < CLEANUP_INTERVAL:
        return

    elapsed = int(now - _last_cleanup_time) if _last_cleanup_time else 0
    _last_cleanup_time = now

    gc.collect()

    removed = 0
    for pattern in ['*.tmp', '*.temp', '*.swp']:
        for f in ROOT.glob(pattern):
            try:
                if f.is_file():
                    f.unlink()
                    removed += 1
            except OSError:
                pass

    print(f"[🧹 RESOURCE CLEANUP: {removed} temp files, ran after {elapsed}s]", flush=True)
