"""Intelligent Model Router for Jarvis.

Routes queries to the best model based on:
- Query complexity
- Available context window
- System load
- Response quality goals
"""

import os
import time

# Model priorities (lower = better for quick response)
MODEL_CONFIG = {
    "llama3.2:3b": {
        "max_tokens": 512,
        "use_for": "General chat, quick responses, most queries",
        "priority": 1  # Best for most queries
    },
    "moondream:latest": {
        "max_tokens": 512,
        "use_for": "Vision-based queries, screen OCR",
        "priority": 2
    },
    "qwen3-embedding:8b": {
        "max_tokens": 128,  # Low - just for embedding generation
        "use_for": "Vector search, similarity",
        "priority": 3
    }
}

def route_query(query, query_type="default"):
    """Route query to optimal model."""
    q = query.lower().strip()
    
    # Vision queries -> use vision model
    if any(w in q for w in ["see", "show", "screen", "visual", "what do you see"]):
        return {"model": "moondream:latest", "type": "vision", "priority": 2}
    
    # Code/security queries -> use LLM with code capabilities
    if any(w in q for w in ["code", "audit", "security", "review", "debug", "fix", "analyze", "refactor"]):
        return {"model": "llama3.2:3b", "type": "code", "priority": 1}
    
    # Simple greetings -> use lightweight model
    simple_greetings = ["hello", "hi", "hey", "good morning", "good evening"]
    if any(g in q for g in simple_greetings):
        return {"model": "llama3.2:3b", "type": "greeting", "priority": 1}
    
    # Quick queries -> use lightweight model
    quick_questions = ["how are you", "what time", "what should", "what about", "tell me"]
    if any(qw in q for qw in quick_questions):
        return {"model": "llama3.2:3b", "type": "quick", "priority": 1}
    
    # Default - LLM
    return {"model": "llama3.2:3b", "type": "default", "priority": 1}

def get_query_complexity(query):
    """Classify query into complexity levels."""
    q = query.lower().strip()
    
    complex_patterns = [
        "audit", "analyze", "review", "evaluate", "assess",
        "explain", "why", "how come", "interpret", "investigate"
    ]
    
    simple_patterns = [
        "hello", "hi", "yes", "no", "ok", "okay", "what", "how", "when", "where"
    ]
    
    if any(p in q for p in complex_patterns):
        return "complex"
    elif any(p in q for p in simple_patterns):
        return "simple"
    else:
        return "medium"

def get_model_for_complexity(complexity):
    """Get model for query complexity.

    Routes simple/quick reasoning to the lightweight chat model and keeps
    the heavier vision model reserved for visual work.
    """
    if complexity == "complex":
        return "llama3.2:3b"
    if complexity == "vision":
        return "moondream:latest"
    # simple / medium
    return "llama3.2:3b"

if __name__ == "__main__":
    test_queries = [
        "How are you?",
        "Check the code for security issues",
        "What do you see on my screen?",
        "Tell me about the weather",
        "Analyze this function for bugs",
        "Why is my application slow?"
    ]
    
    for q in test_queries:
        route = route_query(q)
        complexity = get_query_complexity(q)
        print(f"  Query: {q[:40]:40s} -> Model: {route['model']:20s} (complexity: {complexity})")
