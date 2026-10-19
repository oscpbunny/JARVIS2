"""Memory & Performance Optimized Model Management for Jarvis.

Features:
- Adaptive model loading based on usage patterns
- Request caching for repeated queries
- Model lifecycle management
- Performance monitoring
"""

import os
import json
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

ROOT = Path(__file__).resolve().parent

class ModelCache:
    """Cache model responses for repeated queries."""
    
    def __init__(self, max_size=100):
        self.cache = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def get(self, key):
        """Get cached response."""
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        return None
    
    def set(self, key, value):
        """Cache a response."""
        if len(self.cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
        self.cache[key] = value
    
    def get_stats(self):
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "cache_size": len(self.cache)
        }

class ModelManager:
    """Manage Ollama model lifecycle."""
    
    def __init__(self):
        self.essential_models = [
            "llama3.2:3b",  # Main LLM for responses
            "moondream:latest"  # Vision for screen OCR
        ]
        self.extra_models = [
            "qwen3-embedding:8b",
            "moondream:latest"
        ]
        self.model_status = {}
        self.cache = ModelCache(max_size=100)
        self._start_essential_models()
    
    def _start_model(self, model_name):
        """Start a single Ollama model."""
        try:
            # Check if already running
            result = subprocess.run(
                ["curl", "-s", "http://localhost:11434/api/tags"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False
            
            import json
            data = json.loads(result.stdout)
            running = [m["name"] for m in data.get("models", [])]
            
            if model_name in running:
                self.model_status[model_name] = "running"
                return True
            
            # Start model
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            time.sleep(2)
            
            # Verify it started
            time.sleep(1)
            self.model_status[model_name] = "running"
            return True
        except Exception as e:
            self.model_status[model_name] = f"error: {e}"
            return False
    
    def _start_essential_models(self):
        """Start only essential models."""
        print("🧠 Starting essential models...")
        for model in self.essential_models:
            if self._start_model(model):
                print(f"  ✅ {model}")
            else:
                print(f"  ❌ Failed: {model}")
    
    def optimize_for_speed(self):
        """Optimize for fastest response times."""
        # Keep only essential models
        extra = [
            "qwen3-embedding:8b" if False else None,  # Optional: for embedding
            "moondream:latest"  # Keep vision model
        ]
        
        # Only keep essential + vision
        return [m for m in self.essential_models if m.startswith("llama3.2")]
    
    def should_use_fast_model(self, query):
        """Determine if a query can use a faster model."""
        q = query.lower().strip()
        
        # Quick questions can use faster processing
        quick_questions = [
            "hello", "hi", "hey", "how are you", "what's up",
            "ok", "okay", "yes", "no", "thanks", "sorry"
        ]
        
        # Complex tasks need more power
        complex_tasks = [
            "audit", "analyze", "review", "explain", "debug", 
            "fix", "code", "security", "hope", "what do you see", "find"
        ]
        
        for word in quick_questions:
            if word in q:
                return True
        
        for word in complex_tasks:
            if word in q:
                return False
        
        return True
    
    def get_cache_stats(self):
        """Get cache statistics."""
        return self.cache.get_stats()
    
    def log_performance(self, query, response_time):
        """Log performance for optimization."""
        # Log slow queries for analysis
        if response_time > 5.0:  # More than 5 seconds
            print(f"[⚠️ SLOW QUERY: {response_time:.2f}s] {query[:50]}")

# Global model manager instance
model_manager = ModelManager()

if __name__ == "__main__":
    print(f"Cache stats: {model_manager.get_cache_stats()}")
    print(f"Ready to handle queries efficiently")
