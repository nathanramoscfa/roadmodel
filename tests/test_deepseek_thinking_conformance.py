"""Tests for the DeepSeek thinking docs extractor + conformance check.

Covers ``update/extract_deepseek_thinking.py`` (deterministic bs4 parse of the
single Control-Parameter table, offline, against a committed HTML slice) and the
provider-aware DeepSeek check (check F) added to
``update/validate_effort_conformance.py``:

- Extractor parses the thinking toggle (``enabled``/``disabled``) and the
  reasoning-effort enum (``high``/``max``) from the table cells, and the
  defaults + compatibility aliases from the footnotes.
- Extractor fails loudly when the docs are restructured (anchors gone) and flags
  an unexpected native effort/toggle value rather than absorbing it.
- The effort/toggle vocabulary extractors pull the right tokens from the real
  selector.
- Conformance PASSES on the committed selector + committed DeepSeek snapshot.
- Conformance FAILS on an undocumented effort token (subset), a documented effort
  token dropped from the bullet (completeness), a broken output mapping, and a
  toggle-vocabulary drift.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
EXTRACTOR = UPDATE_DIR / "extract_deepseek_thinking.py"
CONFORMANCE = UPDATE_DIR / "validate_effort_conformance.py"
SAMPLE_HTML = REPO_ROOT / "tests" / "fixtures" / "deepseek-thinking-sample.html"

REAL_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"
REAL_CC_SNAPSHOT = UPDATE_DIR / "claude-code-effort.json"
REAL_CODEX_SNAPSHOT = UPDATE_DIR / "codex-reasoning.json"
REAL_GEMINI_SNAPSHOT = UPDATE_DIR / "gemini-thinking.json"
REAL_DEEPSEEK_SNAPSHOT = UPDATE_DIR / "deepseek-thinking.json"


def _load(name: str) -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def _run_conformance(
    selector: Path, deepseek_snapshot: Path = REAL_DEEPSEEK_SNAPSHOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CONFORMANCE),
            "--selector",
            str(selector),
            "--snapshot",
            str(REAL_CC_SNAPSHOT),
            "--codex-snapshot",
            str(REAL_CODEX_SNAPSHOT),
            "--gemini-snapshot",
            str(REAL_GEMINI_SNAPSHOT),
            "--deepseek-snapshot",
            str(deepseek_snapshot),
        ],
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #


def test_extractor_parses_control_table() -> None:
    mod = _load("extract_deepseek_thinking")
    snap = mod.build_snapshot(SAMPLE_HTML.read_text(), source_url="file://sample")

    assert snap["reasoning_effort"] == ["high", "max"]
    assert snap["thinking_toggle"] == ["enabled", "disabled"]
    assert snap["toggle_default"] == "enabled"
    assert snap["effort_default"] == "high"
    assert snap["effort_aliases"] == {"low": "high", "medium": "high", "xhigh": "max"}
    assert snap["unexpected_effort"] == []
    assert snap["unexpected_toggle"] == []
    assert len(snap["section_sha256"]) == 64


def test_extractor_cli_writes_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "deepseek.json"
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), "--input", str(SAMPLE_HTML), "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["reasoning_effort"] == ["high", "max"]
    assert data["thinking_toggle"] == ["enabled", "disabled"]


def test_committed_snapshot_invariants() -> None:
    """The committed snapshot must carry the headline facts the gate relies on."""
    snap = json.loads(REAL_DEEPSEEK_SNAPSHOT.read_text())
    effort = snap["reasoning_effort"]
    assert isinstance(effort, list) and effort, "reasoning_effort must be non-empty"
    assert len(effort) == len(set(effort)), f"duplicate effort tiers: {effort}"
    # The toggle is a two-position control by definition — that IS an invariant,
    # unlike the effort vocabulary, which upstream may extend at any time.
    assert set(snap["thinking_toggle"]) == {"enabled", "disabled"}
    # Defaults are informational (the gate does not depend on them), so require
    # only that they are drawn from the documented vocabulary when present. They
    # silently became None once already when DeepSeek reworded the footnote the
    # extractor anchored on.
    if snap.get("effort_default") is not None:
        assert snap["effort_default"] in effort
    if snap.get("toggle_default") is not None:
        assert snap["toggle_default"] in snap["thinking_toggle"]


def test_extractor_raises_on_restructured_docs() -> None:
    mod = _load("extract_deepseek_thinking")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("<html><body>No tables here.</body></html>", source_url="x")


def test_extractor_flags_unexpected_effort_value() -> None:
    """A docs-added NATIVE effort tier (in the table cell) must be CAPTURED —
    flowed into reasoning_effort and surfaced in unexpected_effort — not silently
    dropped. Mirrors the Gemini unexpected_levels guard (PR #229)."""
    mod = _load("extract_deepseek_thinking")
    html = SAMPLE_HTML.read_text().replace('"high/max"', '"high/max/ultra"')
    snap = mod.build_snapshot(html, source_url="x")
    assert "ultra" in snap["reasoning_effort"]
    assert "ultra" in snap["unexpected_effort"]


def test_extractor_flags_unexpected_toggle_value() -> None:
    mod = _load("extract_deepseek_thinking")
    html = SAMPLE_HTML.read_text().replace('"enabled/disabled"', '"enabled/disabled/paused"')
    snap = mod.build_snapshot(html, source_url="x")
    assert "paused" in snap["thinking_toggle"]
    assert "paused" in snap["unexpected_toggle"]


def test_conformance_demands_a_newly_documented_effort(tmp_path: Path) -> None:
    """The teeth: if the docs add an effort tier (snapshot has it) the selector
    does NOT yet enumerate, the gate FAILS (F1 completeness) — so a new tier can
    never slip through silently."""
    snap = json.loads(REAL_DEEPSEEK_SNAPSHOT.read_text())
    snap["reasoning_effort"] = [*snap["reasoning_effort"], "ultra"]
    drifted_snapshot = tmp_path / "deepseek.json"
    drifted_snapshot.write_text(json.dumps(snap))

    result = _run_conformance(REAL_SELECTOR, deepseek_snapshot=drifted_snapshot)
    assert result.returncode == 1
    assert "check F (deepseek effort)" in result.stderr
    assert "ultra" in result.stderr


# --------------------------------------------------------------------------- #
# Token extraction (parser robustness on the real selector)
# --------------------------------------------------------------------------- #


def test_effort_and_toggle_vocab_extraction_on_real_selector() -> None:
    mod = _load("validate_effort_conformance")
    selector = REAL_SELECTOR.read_text()
    thinking_flat = mod._collapse(mod.extract_block(selector, mod.THINKING_BLOCK))
    # The CONTRACT is selector == docs, not selector == a list frozen in a test.
    # (The two fixture-based tests above DO pin exact values, correctly: they
    # parse a checked-in HTML sample, so their expected output cannot move
    # underneath them. This one reads the live snapshot, so it must derive.)
    documented = {
        lv.lower() for lv in json.loads(REAL_DEEPSEEK_SNAPSHOT.read_text())["reasoning_effort"]
    }
    assert mod.deepseek_effort_tokens(thinking_flat) == documented
    assert mod.deepseek_toggle_tokens(thinking_flat) == {"disabled", "enabled"}


# --------------------------------------------------------------------------- #
# Conformance gate (check F)
# --------------------------------------------------------------------------- #


def test_conformance_passes_on_committed_artifacts() -> None:
    result = _run_conformance(REAL_SELECTOR)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout


def test_conformance_flags_undocumented_deepseek_effort(tmp_path: Path) -> None:
    """F1 subset: an undocumented effort token in the DeepSeek enumeration -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`high`, `max` (default",
        "`high`, `max`, `ultra` (default",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check F (deepseek effort)" in result.stderr
    assert "ultra" in result.stderr


def test_conformance_flags_dropped_deepseek_effort(tmp_path: Path) -> None:
    """F1 completeness: dropping `max` from the enumeration -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`high`, `max` (default",
        "`high` (default",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check F (deepseek effort)" in result.stderr
    assert "max" in result.stderr


def test_conformance_flags_broken_deepseek_mapping(tmp_path: Path) -> None:
    """F-mapping: breaking the `max` -> `XHigh` mapping -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "effort `max` → `XHigh`",
        "effort `max` → `High`",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check F (deepseek mapping)" in result.stderr
    assert "XHigh" in result.stderr


def test_conformance_flags_deepseek_toggle_drift(tmp_path: Path) -> None:
    """F1 toggle subset: an undocumented toggle value -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`disabled`, default `enabled`)",
        "`disabled` / `paused`, default `enabled`)",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check F (deepseek toggle)" in result.stderr
    assert "paused" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
