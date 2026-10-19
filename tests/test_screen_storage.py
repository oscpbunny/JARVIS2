"""Phase 6 — screen recall storage & retention."""
import importlib
import json
import sqlite3
import struct
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import screen_recorder as sr


@pytest.fixture()
def isolated_db(monkeypatch, tmp_path):
    """Point the recorder at a throwaway DB so tests never touch the real one."""
    db = tmp_path / "test_screen.sqlite3"
    monkeypatch.setattr(sr, "DB_PATH", db)
    sr.init_db()
    return db


class TestEmbeddingCodec:
    def test_pack_decode_roundtrip(self):
        vec = [0.5, -1.25, 3.0, 0.0] * 1024  # 4096-dim like qwen3-embedding:8b
        blob = sr._pack_embedding(vec)
        assert len(blob) == 4096 * 4  # float32 → 16 KB
        back = sr._decode_embedding(blob)
        assert back == pytest.approx(vec, abs=1e-6)

    def test_packed_is_smaller_than_json(self):
        vec = [0.123456789] * 4096
        assert len(sr._pack_embedding(vec)) < len(json.dumps(vec))

    def test_decode_legacy_json_rows(self):
        legacy = json.dumps([1.0, 2.0, 3.0])
        assert sr._decode_embedding(legacy) == [1.0, 2.0, 3.0]

    def test_decode_garbage_returns_none(self):
        assert sr._decode_embedding(None) is None
        assert sr._decode_embedding(b"\x00\x01\x02") is None  # 3 bytes, not a whole float32
        assert sr._decode_embedding("not json{{{") is None
        assert sr._decode_embedding(12345) is None


class TestPruneDb:
    def _insert(self, db, ts, emb=None):
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO screen_frames (timestamp, app_name, ocr_text, embedding)"
                " VALUES (?, ?, ?, ?)",
                (ts, "TestApp", "hello", emb),
            )

    def test_prunes_frames_older_than_retention(self, isolated_db, monkeypatch):
        monkeypatch.setattr(sr, "RETENTION_SECONDS", 3600)  # 1h for the test
        now = time.time()
        self._insert(isolated_db, now - 7200)  # 2h old → pruned
        self._insert(isolated_db, now - 60)    # fresh → kept
        stats = sr.prune_db()
        assert stats["ok"] is True
        assert stats["deleted_by_age"] == 1
        with sqlite3.connect(isolated_db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM screen_frames").fetchone()[0] == 1

    def test_row_count_cap_keeps_newest(self, isolated_db, monkeypatch):
        monkeypatch.setattr(sr, "MAX_FRAMES", 3)
        monkeypatch.setattr(sr, "RETENTION_SECONDS", 10**9)  # disable age prune
        now = time.time()
        for i in range(5):
            self._insert(isolated_db, now + i)
        stats = sr.prune_db()
        assert stats["deleted_by_count"] == 2
        with sqlite3.connect(isolated_db) as conn:
            rows = conn.execute("SELECT timestamp FROM screen_frames ORDER BY timestamp").fetchall()
        assert len(rows) == 3
        assert rows[0][0] == pytest.approx(now + 2)

    def test_prune_on_shared_connection(self, isolated_db, monkeypatch):
        """ingest_frame passes its open connection — prune must not close it."""
        monkeypatch.setattr(sr, "RETENTION_SECONDS", 3600)
        now = time.time()
        conn = sqlite3.connect(isolated_db)
        try:
            conn.execute(
                "INSERT INTO screen_frames (timestamp, app_name) VALUES (?, ?)",
                (now - 7200, "Old"),
            )
            stats = sr.prune_db(conn)
            assert stats["deleted_by_age"] == 1
            conn.commit()  # must still work — prune did not close it
            assert conn.execute("SELECT COUNT(*) FROM screen_frames").fetchone()[0] == 0
        finally:
            conn.close()

    def test_init_db_enables_wal(self, isolated_db):
        with sqlite3.connect(isolated_db) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_config_values_are_sane(self):
        import jarvis_config as cfg
        assert cfg.SCREEN_CAPTURE_INTERVAL > 0
        assert cfg.SCREEN_RETENTION_DAYS > 0
        assert cfg.SCREEN_MAX_FRAMES > 0
        assert cfg.SCREEN_MAX_DB_MB > 0
