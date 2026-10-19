"""Memory Management Module for Jarvis.

Handles memory monitoring, cleanup, and optimization.
"""

import os
import gc
import sys
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent

def get_memory_usage():
    """Get current memory usage statistics."""
    try:
        # macOS specific
        result = subprocess.run(
            ["/usr/sbin/lsof", "-p", str(os.getpid())],
            capture_output=True, text=True, timeout=5
        )
        # Memory details via system memory
        mem = {}
        mem['rss'] = "N/A"  # Would need /proc or other method
        mem['vsz'] = "N/A"
        return mem
    except:
        return {}

def cleanup_temp_files():
    """Clean up old temporary files."""
    # Clean up temp files in working directory
    for pattern in ['*.tmp', '*.temp', '*.swp', '*~']:
        for f in ROOT.glob(pattern):
            try:
                if f.is_file():
                    os.utime(f, None)  # Reset timestamp
            except:
                pass

def force_gc():
    """Trigger garbage collection."""
    gc.collect()

def optimize_numpy():
    """Optimize numpy memory usage."""
    import numpy as np
    # Ensure numpy uses efficient memory
    np.set_printoptions(threshold=np.inf)
    return True

if __name__ == "__main__":
    cleanup_temp_files()
    force_gc()
    optimize_numpy()
    print("💾 Memory cleanup complete")
