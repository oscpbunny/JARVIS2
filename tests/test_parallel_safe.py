"""Parallel-safe additions: vault_index cache + jarvis_health probe + CI pytest."""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestVaultIndex:
    def test_iter_never_raises_and_caches(self):
        import vault_index as vi
        vi.clear()
        first = list(vi.iter_notes())
        s1 = vi.stats()
        assert s1["misses"] >= 0
        second = list(vi.iter_notes())
        s2 = vi.stats()
        assert len(first) == len(second)
        # 4-tuple: (path, content, content_lower, stem_lower)
        if first:
            assert len(first[0]) == 4, first[0]
            p, content, content_lower, stem = first[0]
            assert content.lower() == content_lower
            assert p.stem.lower() == stem
            # second pass over unchanged vault must be all hits (no disk reads)
            assert s2["hits"] == len(first), s2
        assert {type(p).__name__ for p, _, _, _ in first} <= {"PosixPath", "WindowsPath"} or not first

    def test_stats_shape(self):
        import vault_index as vi
        s = vi.stats()
        assert set(s) == {"entries", "hits", "misses"}

    def test_missing_vault_yields_nothing(self, tmp_path, monkeypatch):
        import vault_index as vi
        monkeypatch.setattr(vi, "VAULT_DIR", tmp_path / "does-not-exist")
        vi.clear()
        assert list(vi.iter_notes()) == []

    def test_nested_paths_and_case_preserved(self, tmp_path, monkeypatch):
        """Nested notes must resolve; snippets must keep original case."""
        import vault_index as vi
        import obsidian_rag as rag
        sub = tmp_path / "Memory" / "Sub"
        sub.mkdir(parents=True)
        (sub / "Nested.md").write_text(
            "# MixedCase TOKENXYZ\nTOKENXYZ TOKENXYZ TOKENXYZ TOKENXYZ body text here\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(vi, "VAULT_DIR", tmp_path)
        monkeypatch.setattr(rag, "VAULT_DIR", tmp_path)
        vi.clear()
        rows = list(vi.iter_notes())
        assert rows and len(rows[0]) == 4
        assert any("Sub" in str(p) for p, _, _, _ in rows)
        out = rag.search_vault("tokenxyz")
        assert "MixedCase" in out, out  # original case, not lowercased
        assert "mixedcase tokenxyz body" not in out


class TestHealthProbe:
    def test_check_shape_and_never_raises(self):
        import jarvis_health as h
        rep = h.check()
        assert set(rep) >= {"ok", "warnings", "info"}
        assert isinstance(rep["warnings"], list)
        assert "pillars_ready" in rep["info"]

    def test_pillars_all_wired(self):
        import jarvis_health as h
        rep = h.check()
        ready = rep["info"].get("pillars_ready", [])
        assert "ambient_guardian" in ready
        assert "subagent_swarm" in ready


class TestCI:
    def test_ci_runs_pytest(self):
        yml = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        assert "pytest" in yml, "CI must run the pytest suite (was compileall+smoke only)"
        assert "test_logging.py" in yml or "tests/" in yml


class TestActionHardening:
    """Voice/model text must never break out of an AppleScript string."""

    def test_close_app_rejects_arbitrary_names(self):
        from jarvis_actions import close_app
        hostile = 'Evil" to activate\ntell application "X'
        out = close_app(hostile)
        assert "not in the allowed app list" in out

    def test_keystroke_literal_flattens_injection(self):
        from jarvis_actions import _keystroke_literal
        assert "\n" not in _keystroke_literal('a"\nb')
        assert _keystroke_literal('a"b') == 'a\\"b'
        assert len(_keystroke_literal("x" * 9999)) <= 500

    def test_osascript_quote_matches_driver(self):
        import platform
        from jarvis_actions import _osascript_quote
        hostile = 'Finder" to activate'
        q = _osascript_quote(hostile)
        assert q.startswith('quoted form of "')
        if platform.system() == "Darwin":
            import mac_input_driver as d
            assert q == d._osascript_quote(hostile)

    def test_set_volume_rejects_junk(self):
        from jarvis_actions import set_volume
        assert "must be a number" in set_volume("loud; rm -rf /")
        assert "100 percent" in set_volume(999)


class TestSyncLogBounded:
    def test_log_keeps_last_n_lines(self, tmp_path, monkeypatch):
        import obsidian_sync as sync
        monkeypatch.setattr(sync, "SYNC_LOG", tmp_path / "sync.log")
        for i in range(250):
            sync.log(f"line {i}")
        lines = (tmp_path / "sync.log").read_text().splitlines()
        assert len(lines) == sync._SYNC_LOG_KEEP
        assert lines[-1].endswith("line 249")


class TestSupervisorNonblocking:
    def test_no_sleep_inside_restart_branch(self):
        src = (ROOT / "supervisor.py").read_text()
        assert "NEXT_RETRY" in src
        # the restart branch must schedule + continue, not time.sleep(delay)
        restart_idx = src.index("Retrying in")
        window = src[max(0, restart_idx - 400):restart_idx + 400]
        assert "del SERVICES[name]" in window
        assert "time.sleep(delay)" not in src


class TestPhase7Leftovers:
    """screen_vision / code_inspector / obsidian_rag expose jarvis_log loggers;
    jarvis_actions __main__ must not launch the IDE as a side-effect."""

    def test_module_loggers_attached(self):
        import code_inspector
        import obsidian_rag
        import screen_vision
        for mod, name in ((screen_vision, "screen_vision"),
                          (code_inspector, "code_inspector"),
                          (obsidian_rag, "obsidian_rag")):
            log = getattr(mod, "log", None)
            assert isinstance(log, logging.Logger), f"{name}.log missing"
            assert log.name == name

    def test_no_ide_launch_in_actions_main(self):
        src = (ROOT / "jarvis_actions.py").read_text()
        main = src.split('if __name__ == "__main__":', 1)[1]
        assert 'open_app(' not in main, "module self-test must not launch apps"
        assert "skipped open_app probe" in main


class TestVisionGate:
    """Pin the hallucinated-coords safety gate (live bug 2026-10-19).

    moondream returned confident coords for a nonexistent target and
    visual_click CLICKED them. The gate must fail closed on anything but
    an explicit yes.
    """

    @staticmethod
    def _gate_with(monkeypatch, response=None, error=False):
        import json as _json
        import urllib.request as _ur
        import mac_input_driver as d

        class _Resp:
            def read(self):
                return _json.dumps({"response": response or ""}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            if error:
                raise OSError("connection refused")
            return _Resp()

        monkeypatch.setattr(_ur, "urlopen", fake_urlopen)
        return d._vision_confirms_exists("whatever", "fakeimg")

    def test_explicit_yes_passes(self, monkeypatch):
        assert self._gate_with(monkeypatch, response="yes") is True

    def test_no_refused(self, monkeypatch):
        assert self._gate_with(monkeypatch, response="no") is False

    def test_garbage_refused(self, monkeypatch):
        assert self._gate_with(monkeypatch, response="hmm, maybe? coordinates 0.5,0.5") is False

    def test_query_failure_fails_closed(self, monkeypatch):
        assert self._gate_with(monkeypatch, error=True) is False

    def test_empty_response_fails_closed(self, monkeypatch):
        assert self._gate_with(monkeypatch, response="") is False


class TestLegacyBrainInterlock:
    """always_online_jarvis.py is RETIRED; launching it auto-spawns Ollama
    models (2 llama-server ~= 39pct RAM) and overheated the Mac on 2026-10-19.
    The __main__ block must refuse to run without an explicit override."""

    def test_main_block_has_interlock(self):
        src = (ROOT / "always_online_jarvis.py").read_text()
        assert 'JARVIS_ALLOW_LEGACY' in src, "missing retired-brain interlock"
        assert "is RETIRED" in src

    def test_refuses_to_run_without_override(self):
        import subprocess as _sp
        r = _sp.run(
            # sys.executable (not a hardcoded venv path) so this runs on CI,
            # where pytest uses the setup-python interpreter with no ./venv.
            [sys.executable, str(ROOT / "always_online_jarvis.py")],
            capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/bin:/bin"},  # no JARVIS_ALLOW_LEGACY
        )
        assert r.returncode == 1, r.stderr[-400:]
        assert "RETIRED" in (r.stderr + r.stdout)
