"""Smart Model Optimizer for Jarvis.

Reduces system load by:
1. Keeping only essential models running
2. Routing queries to appropriate models
3. Caching frequent responses
4. Using smaller models for simple queries
"""

import os
import asyncio
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Model Routing Configuration
MODEL_ROUTES = {
    "simple_phrases": {
        "model": "llama3.2:3b",
        "use": "General conversation, greetings, quick questions",
        "priority": 1  # Highest priority (only essential models)
    },
    "complex_tasks": {
        "model": "llama3.2:3b",
        "use": "Code analysis, security audits, complex reasoning",
        "priority": 2
    },
    "embeddings": {
        "model": "qwen3-embedding:8b",
        "use": "Vector search, vault context, semantic search",
        "priority": 3
    },
    "vision": {
        "model": "moondream:latest",
        "use": "Screen OCR, visual understanding, object detection",
        "priority": 4
    },
    "intent_analysis": {
        "model": "guoxuter/ov_intent_analysis_sft:v7_q8",
        "use": "Intent classification, quick analysis",
        "priority": 5
    }
}

class ModelManager:
    """Manages Ollama model lifecycle for optimal performance."""
    
    def __init__(self):
        self.running_models = set()
        self.model_cache = {}
        self.query_rtt = {}  # Request-response time cache
        self.system_load = 0.0
    
    def get_essential_models(self):
        """Return only essential models (keeps system fast)."""
        return {
            "llama3.2:3b": "Main response model - most queries",
            "moondream:latest": "Vision - screen OCR and visual queries"
        }
    
    def get_model_routes(self):
        """Get the model routing configuration."""
        return MODEL_ROUTES
    
    def optimize_model_load(self):
        """Optimize which models are loaded based on usage patterns."""
        # Start with essential models only
        essential = self.get_essential_models()
        
        # Load only essential models initially
        print("🧠 Optimizing model load...")
        for model, purpose in essential.items():
            if model not in self.running_models:
                self._start_model(model)
                self.running_models.add(model)
                print(f"  ✅ Loaded: {model} ({purpose})")
        
        # Keep non-essential models but only run them when needed
        # Check if we should load additional models based on query patterns
        return essential
    
    def _start_model(self, model_name):
        """Start an Ollama model server."""
        try:
            # Check if model is already running
            result = subprocess.run(
                ["curl", "-s", f"http://localhost:11434/api/tags"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False
            
            import json
            try:
                data = json.loads(result.stdout)
                model_names = [m["name"] for m in data.get("models", [])]
                if model_name in model_names:
                    return True
            except (OSError, subprocess.SubprocessError, ValueError, KeyError):
                pass
            
            # Start model
            subprocess.Popen(
                ["ollama", "run", model_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            time.sleep(2)  # Wait for model to initialize
            return True
        except Exception as e:
            print(f"  ❌ Failed to start {model_name}: {e}")
            return False
    
    def should_load_model(self, query_type, priority_threshold=3):
        """Determine if a model should be loaded for a specific query type."""
        simple_types = {"simple", "greeting", "quick"}
        complex_types = {"complex", "analysis", "synthesis"}

        if query_type in simple_types:
            # Simple queries only need the lightweight essential model
            return True
        if query_type in complex_types:
            # Complex tasks may benefit from the heavier vision model
            return priority_threshold <= 3
        return False
    
    def get_model_for_query(self, query, query_type="default"):
        """Get the best model for a given query."""
        # Route based on query content
        simple_words = ["what", "how", "is", "hello", "hi", "ok", "yes", "no"]
        complex_words = ["audit", "analyze", "review", "explain", "code", "security", "hope"]
        
        if any(w in query.lower() for w in complex_words):
            return {
                "model": "llama3.2:3b",
                "use_case": "complex_task"
            }
        
        if query_type == "vision":
            return {
                "model": "moondream:latest",
                "use_case": "vision"
            }
        
        # Default to lightweight model for simple queries
        return {
            "model": "llama3.2:3b",
            "use_case": "simple"
        }

# Global model manager
model_manager = ModelManager()

if __name__ == "__main__":
    model_manager.optimize_model_load()
