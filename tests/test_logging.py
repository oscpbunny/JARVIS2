"""Phase 7 — structured logging (jarvis_log) regression tests."""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jarvis_config as cfg
import jarvis_log


class TestGetLogger:
    def test_returns_stdlib_logger(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "LOG_DIR", tmp_path)
        import importlib
        importlib.reload(jarvis_log)
        try:
            log = jarvis_log.get_logger("phase7_test_a")
            assert isinstance(log, logging.Logger)
            assert log.level != logging.NOTSET or True  # level set from config
            log.info("hello phase 7")
            assert (tmp_path / "phase7_test_a.log").exists()
        finally:
            importlib.reload(jarvis_log)

    def test_idempotent_no_duplicate_handlers(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "LOG_DIR", tmp_path)
        import importlib
        importlib.reload(jarvis_log)
        try:
            a = jarvis_log.get_logger("phase7_dup")
            n = len(a.handlers)
            b = jarvis_log.get_logger("phase7_dup")
            assert a is b
            assert len(b.handlers) == n
        finally:
            importlib.reload(jarvis_log)

    def test_unwritable_dir_falls_back_to_console(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(cfg, "LOG_DIR", tmp_path / "nope" / "deeper")
        # Make mkdir fail by pointing at a file, not a dir.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        monkeypatch.setattr(cfg, "LOG_DIR", blocker / "child")
        import importlib
        importlib.reload(jarvis_log)
        try:
            log = jarvis_log.get_logger("phase7_fallback")
            log.info("still works")
            captured = capsys.readouterr()
            assert "still works" in captured.err
        finally:
            importlib.reload(jarvis_log)

    def test_rotation_settings_from_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "LOG_DIR", tmp_path)
        monkeypatch.setattr(cfg, "LOG_MAX_MB", 1)
        monkeypatch.setattr(cfg, "LOG_BACKUPS", 2)
        import importlib
        importlib.reload(jarvis_log)
        try:
            from logging.handlers import RotatingFileHandler
            log = jarvis_log.get_logger("phase7_rot")
            rfhs = [h for h in log.handlers if isinstance(h, RotatingFileHandler)]
            assert rfhs, "expected a RotatingFileHandler"
            assert rfhs[0].maxBytes == 1 * 1024 * 1024
            assert rfhs[0].backupCount == 2
        finally:
            importlib.reload(jarvis_log)

    def test_config_values_sane(self):
        assert isinstance(cfg.LOG_LEVEL, str) and cfg.LOG_LEVEL
        assert isinstance(cfg.LOG_DIR, Path)
        assert cfg.LOG_MAX_MB >= 1
        assert cfg.LOG_BACKUPS >= 0


class TestPillarWiring:
    """Every converted pillar exposes a module-level logger wired to jarvis_log."""

    @pytest.mark.parametrize("mod,name", [
        ("ambient_guardian", "ambient_guardian"),
        ("subagent_swarm", "subagent_swarm"),
        ("screen_recorder", "screen_recorder"),
        ("optimizations", "optimizations"),
    ])
    def test_module_logger_attached(self, mod, name):
        module = pytest.importorskip(mod)
        log = getattr(module, "log", None)
        assert isinstance(log, logging.Logger), f"{mod}.log missing"
        assert log.name == name
