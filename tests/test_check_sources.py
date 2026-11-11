"""The catalog run's source gate: each provider's own sources start a refresh.

Until 2026-11 only Cursor's pricing page did, so Gemini 4 Carbon, priced on
Google's own page, waited for Cursor while every run said "pricing.md
unchanged". These tests pin the signature rules in update/check_sources.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "update"))

import check_sources as cs  # noqa: E402

OLD = {"cursor": "c1", "provider:google": "g1", "tracker:gemini-thinking": "t1"}


def test_a_provider_page_alone_starts_a_refresh_without_the_curation_pass() -> None:
    new = {**OLD, "provider:google": "g2"}
    for due in (True, False):
        staged, changed, cursor_changed = cs.decide(OLD, new, cursor_due=due)
        assert changed == ["provider:google"] and not cursor_changed
        assert staged["provider:google"] == "g2"


def test_a_cursor_change_waits_for_the_daily_run() -> None:
    new = {**OLD, "cursor": "c2"}
    staged, changed, cursor_changed = cs.decide(OLD, new, cursor_due=False)
    assert changed == [] and not cursor_changed
    assert staged["cursor"] == "c1"  # kept, so the daily run still sees the change
    staged, changed, cursor_changed = cs.decide(OLD, new, cursor_due=True)
    assert changed == ["cursor"] and cursor_changed and staged["cursor"] == "c2"


def test_a_cursor_fetch_failure_runs_the_pass_and_retries() -> None:
    new = {k: v for k, v in OLD.items() if k != "cursor"}
    staged, changed, cursor_changed = cs.decide(OLD, new, cursor_due=True)
    assert cursor_changed and changed == ["cursor"] and staged["cursor"] == "c1"
    staged, changed, cursor_changed = cs.decide(OLD, new, cursor_due=False)
    assert not cursor_changed and changed == [] and staged["cursor"] == "c1"


def test_nothing_changed_runs_nothing() -> None:
    staged, changed, cursor_changed = cs.decide(OLD, dict(OLD), cursor_due=True)
    assert (staged, changed, cursor_changed) == (OLD, [], False)


def test_the_one_line_signature_before_2026_11_was_cursors_page() -> None:
    old = cs.parse_signature("abc123  https://cursor.com/docs/models/pricing.md\n")
    assert old == {"cursor": "abc123"}
    # Its first run with provider lines refreshes once, without the pass.
    staged, changed, cursor_changed = cs.decide(old, {"cursor": "abc123", "provider:x": "p"}, True)
    assert changed == ["provider:x"] and not cursor_changed
    assert cs.parse_signature(cs.render_signature(staged)) == staged


def test_the_local_signature_reads_snapshots_trackers_and_codex(tmp_path: Path) -> None:
    (tmp_path / "catalog-google.json").write_text('{"models": []}')
    (tmp_path / "gemini-thinking.json").write_text(
        json.dumps({"unexpected_models": ["Gemini 4 Carbon"], "section_sha256": "x"})
    )
    (tmp_path / "default-efforts.json").write_text(
        json.dumps({"_comment": "c", "anthropic-api": {"Fable 5.2": "high"}})
    )
    codex = tmp_path / "codex.txt"
    codex.write_text("gpt-6.1-sol\ngpt-6-luna\n")
    lines = cs.local_signature(tmp_path, codex)
    assert set(lines) == {
        "provider:google",
        "tracker:gemini-thinking",
        "tracker:default-efforts",
        "codex",
    }
    # A tracker's line moves with the models it names, not its other fields.
    (tmp_path / "gemini-thinking.json").write_text(
        json.dumps({"unexpected_models": ["Gemini 4 Carbon"], "section_sha256": "y"})
    )
    assert (
        cs.local_signature(tmp_path, codex)["tracker:gemini-thinking"]
        == (lines["tracker:gemini-thinking"])
    )
    # An empty Codex list is a failed fetch: no line, so the last one stays.
    codex.write_text("")
    assert "codex" not in cs.local_signature(tmp_path, codex)


def test_default_effort_tables_name_their_models() -> None:
    snap = {"_comment": "x", "openai-api": {"GPT-6.1 Sol": "medium"}, "codex": {"a": "low"}}
    assert cs.tracker_models(snap, "*") == ["GPT-6.1 Sol", "a"]
    assert cs.tracker_models({"unexpected_models": ["b", "a"]}, "unexpected_models") == ["a", "b"]


def test_the_summary_names_each_source() -> None:
    text = cs.summary(["cursor", "provider:google", "tracker:gemini-thinking", "codex"])
    assert "Cursor's pricing page" in text and "google's pricing page" in text
    assert "the gemini-thinking docs tracker" in text and "the Codex model list" in text


def test_the_workflow_wires_the_gate() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert '- cron: "0 0-15,17-23 * * *"' in wf and '- cron: "0 16 * * *"' in wf
    # The readers run before the gate, every run.
    readers = wf.index("- name: Refresh provider-direct catalog snapshots")
    assert readers < wf.index("- name: Check for upstream source changes")
    step = wf[readers:].split("\n      - name:", 1)[0]
    assert "if:" not in step.split("run: |", 1)[0].split("id: readers", 1)[1]
    assert "--cursor-due" in wf and "--codex-ids" in wf
    opus = wf.split("- name: Refresh roadmodel catalog (Opus)", 1)[1].split("run: |", 1)[0]
    assert "steps.gate.outputs.cursor_changed == 'true'" in opus
