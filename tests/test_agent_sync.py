"""Tests for agent_sync.py — the one-command coordination helper.

Two real bugs found by usage are pinned here:
  1. claims() regex must accept ANY dated bullet ("Added timeout=5.0 ..." was
     invisible when we matched only CLAIM|DONE|Ack, re-flagging claimed files).
  2. --json must stay pure JSON (pillar import preamble captured, not printed).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent_sync


class TestLaneMap:
    def test_known_lanes(self):
        assert agent_sync.lane_of("vault_index.py") == "perf"
        assert agent_sync.lane_of("subagent_swarm.py") == "integration"
        assert "shared" in agent_sync.lane_of("jarvis_config.py")
        assert "coordination" in agent_sync.lane_of("AGENTS_COORDINATION.md")

    def test_unassigned_fallback(self):
        assert agent_sync.lane_of("mystery_file.py") == "unassigned"

    def test_shared_files_map(self):
        assert "shared" in agent_sync.lane_of("jarvis_actions.py")
        assert "shared" in agent_sync.lane_of("obsidian_rag.py")


class TestClaimsParsing:
    def _coord(self, tmp_path, body):
        c = tmp_path / "AGENTS_COORDINATION.md"
        c.write_text(body, encoding="utf-8")
        return c

    def test_any_dated_bullet_counts(self, tmp_path, monkeypatch):
        # regression: "Added ..." lines (no CLAIM/DONE/Ack keyword) must count
        monkeypatch.setattr(agent_sync, "COORD", self._coord(
            tmp_path,
            "- 2026-10-19 code agent (Kilo): Added timeout=5.0 to subagent_swarm.py\n"
            "- 2026-10-19 Cline (perf lane): DONE thing\n"
            "## heading\n"
            "prose that is not a bullet\n",
        ))
        lines = agent_sync.claims()
        assert len(lines) == 2
        assert any("Added timeout" in ln for ln in lines)

    def test_empty_or_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_sync, "COORD", tmp_path / "missing.md")
        assert agent_sync.claims() == []

    def test_n_limit(self, tmp_path, monkeypatch):
        body = "".join(f"- 2026-10-19 agent: entry {i}\n" for i in range(20))
        monkeypatch.setattr(agent_sync, "COORD", self._coord(tmp_path, body))
        assert len(agent_sync.claims(5)) == 5


class TestUnclaimedEdits:
    def test_claimed_and_coord_skipped(self, monkeypatch):
        monkeypatch.setattr(agent_sync, "_git", lambda *a: " M subagent_swarm.py\n M AGENTS_COORDINATION.md")
        monkeypatch.setattr(agent_sync, "claims", lambda n=40: ["- 2026-10-19 Kilo: Added x to subagent_swarm.py"])
        assert agent_sync.unclaimed_edits() == []

    def test_unmentioned_file_flagged(self, monkeypatch):
        monkeypatch.setattr(agent_sync, "_git", lambda *a: " M sneaky_edit.py")
        monkeypatch.setattr(agent_sync, "claims", lambda n=40: ["- 2026-10-19 Kilo: done other_file.py"])
        out = agent_sync.unclaimed_edits()
        assert len(out) == 1 and "sneaky_edit.py" in out[0] and "unassigned" in out[0]

    def test_clean_tree(self, monkeypatch):
        monkeypatch.setattr(agent_sync, "_git", lambda *a: "")
        assert agent_sync.unclaimed_edits() == []


class TestClaimLogger:
    def test_appends_done_line(self, tmp_path, monkeypatch, capsys):
        c = tmp_path / "AGENTS_COORDINATION.md"
        monkeypatch.setattr(agent_sync, "COORD", c)
        rc = agent_sync.cmd_claim("verified thing", "DONE")
        assert rc == 0
        text = c.read_text(encoding="utf-8")
        assert text.startswith("- 2026-") and "Cline (perf lane): DONE verified thing" in text
        assert "logged:" in capsys.readouterr().out

    def test_kind_prefix_not_duplicated(self, tmp_path, monkeypatch):
        c = tmp_path / "coord.md"
        monkeypatch.setattr(agent_sync, "COORD", c)
        agent_sync.cmd_claim("DONE already prefixed", "DONE")
        assert c.read_text(encoding="utf-8").count("DONE") == 1


class TestMain:
    def test_json_is_pure_json(self, monkeypatch, capsys):
        fake = {"ok": True, "files": [], "unclaimed_edits": [], "recent_claims": [],
                "health_warnings": [], "health_info": {}, "vault_cache": {},
                "import_preamble": "[pillars] active: ..."}
        monkeypatch.setattr(agent_sync, "snapshot", lambda: fake)
        monkeypatch.setattr(sys, "argv", ["agent_sync.py", "--json"])
        assert agent_sync.main() == 0
        data = json.loads(capsys.readouterr().out)  # must parse — regression #2
        assert data["ok"] is True and "import_preamble" in data

    def test_human_mode_mentions_status(self, monkeypatch, capsys):
        fake = {"ok": True, "files": [], "unclaimed_edits": [], "recent_claims": [],
                "health_warnings": [], "health_info": {}, "vault_cache": {},
                "import_preamble": ""}
        monkeypatch.setattr(agent_sync, "snapshot", lambda: fake)
        monkeypatch.setattr(sys, "argv", ["agent_sync.py"])
        assert agent_sync.main() == 0
        out = capsys.readouterr().out
        assert "CLEAN" in out and "clean" in out

    def test_claim_flag_writes_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(agent_sync, "COORD", tmp_path / "c.md")
        monkeypatch.setattr(sys, "argv", ["agent_sync.py", "--claim", "vault_index.py", "test"])
        assert agent_sync.main() == 0
        assert "CLAIM vault_index.py test" in (tmp_path / "c.md").read_text(encoding="utf-8")


class TestCmdMsg5W:
    """Structured 5W handoffs carry who/what/when/how/why + an explicit ASK so
    the other agent can judge risk and act without guessing."""

    def test_msg_emits_all_five_w(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(agent_sync, "COORD", tmp_path / "c.md")
        rc = agent_sync.cmd_msg(
            who="Kilo", what="fixed leak", when="now", how="finally-block",
            why="avoid slot exhaustion", ask="review it?", kind="MSG")
        assert rc == 0
        text = (tmp_path / "c.md").read_text(encoding="utf-8")
        assert "MSG by Kilo: fixed leak" in text
        for tag in ("WHEN: now", "HOW: finally-block", "WHY: avoid slot exhaustion",
                    "ASK: review it?"):
            assert tag in text, text

    def test_msg_omits_missing_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_sync, "COORD", tmp_path / "c.md")
        agent_sync.cmd_msg(who="Cline", what="just this", kind="MSG")
        text = (tmp_path / "c.md").read_text(encoding="utf-8")
        assert "WHEN:" not in text and "ASK:" not in text

    def test_flagval_skips_bare_trigger(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["agent_sync.py", "--ask", "--who", "Kilo"])
        # bare --ask must not swallow --who as its value
        assert agent_sync._flagval("--ask") == ""
        assert agent_sync._flagval("--who") == "Kilo"

    def test_flagval_returns_quoted_value(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["x", "--what", "two word value"])
        assert agent_sync._flagval("--what") == "two word value"

    def test_ask_trigger_defaults_to_ask_kind(self, monkeypatch, capsys, tmp_path):
        # COORD MUST be patched to tmp_path: main() -> cmd_msg() appends to
        # agent_sync.COORD, and without this the test writes real lines into
        # AGENTS_COORDINATION.md (pollution bug found 2026-10-19).
        monkeypatch.setattr(agent_sync, "COORD", tmp_path / "c.md")
        fake = {"ok": True, "files": [], "unclaimed_edits": [], "recent_claims": [],
                "health_warnings": [], "health_info": {}, "vault_cache": {},
                "import_preamble": ""}
        monkeypatch.setattr(agent_sync, "snapshot", lambda: fake)
        monkeypatch.setattr(sys, "argv", ["agent_sync.py", "--ask", "--what", "q1",
                                          "--q", "the question"])
        assert agent_sync.main() == 0
        out = capsys.readouterr().out
        assert out.startswith("logged:") and "ASK by" in out and "the question" in out
        # the line landed in the tmp coord file, not the real one
        assert "the question" in (tmp_path / "c.md").read_text(encoding="utf-8")
