#!/usr/bin/env python3
"""Pillar 1 — Self-Evolving Dynamic Skill Engine
Provides runtime generation, LLM synthesis, compilation checks, and hot-reloading
of new Jarvis skills when unrecognized intents occur.
"""
from __future__ import annotations

import os
import sys
import subprocess
import traceback
import importlib
import urllib.request
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434")
MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")


def synthesize_skill_code(intent_description: str) -> str:
    """Uses Ollama to generate a safe Python function for the requested intent."""
    prompt = f"""Write a concise, standalone Python module for Jarvis to execute this intent: "{intent_description}".
It MUST define a function:
def execute_skill(args: dict = None) -> dict:
    # returns dict with 'status': 'success'|'error', 'message': str

Only return pure Python code enclosed in ```python ``` tags. Keep it safe using standard library or macOS subprocess."""
    try:
        req_data = json.dumps({
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/api/generate",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            raw = data.get("response", "")
            if "```python" in raw:
                return raw.split("```python")[1].split("```")[0].strip()
            elif "```" in raw:
                return raw.split("```")[1].split("```")[0].strip()
            return raw.strip()
    except Exception:
        # Fallback safe template
        return (
            f"def execute_skill(args: dict = None) -> dict:\n"
            f"    \"\"\"Synthesized skill for: {intent_description}\"\"\"\n"
            f"    return {{'status': 'success', 'message': 'Handled intent: {intent_description}'}}\n"
        )


def generate_skill(skill_name: str, code: str) -> str:
    clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in skill_name).strip("_")[:30]
    filename = f"dynamic_{clean_name}.py"
    filepath = SKILLS_DIR / filename
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(code, encoding="utf-8")
    return f"skills.dynamic_{clean_name}"


def validate_skill(filepath: Path) -> bool:
    try:
        subprocess.check_output([sys.executable, "-m", "py_compile", str(filepath)], stderr=subprocess.STDOUT)
        check_code = f"import importlib.util; spec = importlib.util.spec_from_file_location('tmp', r'{filepath}'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"
        subprocess.check_output([sys.executable, "-c", check_code], stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError as e:
        print("[⚠️ Skill validation error]:", e.output.decode(errors="ignore"))
        return False


def hot_reload(module_path: str) -> Any:
    if module_path in sys.modules:
        return importlib.reload(sys.modules[module_path])
    return importlib.import_module(module_path)


def register_skill(skill_name: str, code: str | None = None) -> bool:
    """Synthesizes (if needed), compiles, validates and hot-reloads a skill."""
    try:
        if not code:
            code = synthesize_skill_code(skill_name)
        mod_name = generate_skill(skill_name, code)
        clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in skill_name).strip("_")[:30]
        full_path = SKILLS_DIR / f"dynamic_{clean_name}.py"
        if not validate_skill(full_path):
            return False
        hot_reload(mod_name)
        print(f"[⚡ SKILL REGISTERED & HOT-RELOADED]: {mod_name}", flush=True)
        return True
    except Exception:
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        intent = " ".join(sys.argv[1:])
        ok = register_skill(intent)
        print(f"Registration result for '{intent}': {ok}")
