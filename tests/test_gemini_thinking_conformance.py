"""Tests for the Gemini thinking docs extractor + conformance check.

Covers ``update/extract_gemini_thinking.py`` (deterministic bs4 parse of the two
in-scope tables, offline, against a committed HTML slice) and the provider-aware
Gemini check (check E) added to ``update/validate_effort_conformance.py``:

- Extractor parses the Gemini 3.x thinking-level support matrix (3.1 Pro lacks
  minimal) and the Gemini 2.5 numeric budget table (2.5 Pro cannot disable) from
  the HTML slice, and derives the -1/0 sentinels.
- Extractor fails loudly when the docs are restructured (anchors gone) and flags
  an unexpected level-matrix model rather than absorbing it.
- The level-vocabulary extractor pulls the right tokens from the real selector.
- Conformance PASSES on the committed selector + committed Gemini snapshot.
- Conformance FAILS on an undocumented level (subset), a documented level
  dropped from the bullet (completeness), a per-model tie the docs disallow
  (3.1 Pro -> minimal), and a dropped -1/dynamic sentinel.
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
EXTRACTOR = UPDATE_DIR / "extract_gemini_thinking.py"
CONFORMANCE = UPDATE_DIR / "validate_effort_conformance.py"
SAMPLE_HTML = REPO_ROOT / "tests" / "fixtures" / "gemini-thinking-sample.html"

REAL_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"
REAL_CC_SNAPSHOT = UPDATE_DIR / "claude-code-effort.json"
REAL_CODEX_SNAPSHOT = UPDATE_DIR / "codex-reasoning.json"
REAL_GEMINI_SNAPSHOT = UPDATE_DIR / "gemini-thinking.json"


def _load(name: str) -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def _run_conformance(selector: Path) -> subprocess.CompletedProcess[str]:
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
        ],
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #


def test_extractor_parses_both_tables() -> None:
    mod = _load("extract_gemini_thinking")
    snap = mod.build_snapshot(SAMPLE_HTML.read_text(), source_url="file://sample")

    assert snap["thinking_levels"] == ["minimal", "low", "medium", "high"]
    assert snap["per_model_levels"]["Gemini 3.1 Pro"] == ["low", "medium", "high"]
    assert "minimal" not in snap["per_model_levels"]["Gemini 3.1 Pro"]
    assert snap["per_model_levels"]["Gemini 3 Flash"] == ["minimal", "low", "medium", "high"]
    assert snap["level_defaults"]["Gemini 3.1 Pro"] == "high"
    assert snap["level_defaults"]["Gemini 3.5 Flash"] == "medium"

    budget = snap["per_model_budget"]
    assert budget["2.5 Pro"]["range"] == [128, 32768]
    assert budget["2.5 Pro"]["can_disable"] is False
    assert budget["2.5 Flash"]["range"] == [0, 24576]
    assert budget["2.5 Flash"]["can_disable"] is True

    assert snap["budget_sentinels"] == {"dynamic": -1, "disable": 0}
    assert snap["unexpected_models"] == []
    assert len(snap["section_sha256"]) == 64


def test_extractor_cli_writes_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "gemini.json"
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), "--input", str(SAMPLE_HTML), "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["thinking_levels"] == ["minimal", "low", "medium", "high"]


def test_committed_snapshot_invariants() -> None:
    """The committed snapshot must carry the headline facts the gate relies on."""
    snap = json.loads(REAL_GEMINI_SNAPSHOT.read_text())
    assert snap["thinking_levels"] == ["minimal", "low", "medium", "high"]
    assert "minimal" not in snap["per_model_levels"]["Gemini 3.1 Pro"]
    assert snap["budget_sentinels"]["dynamic"] == -1
    assert snap["budget_sentinels"]["disable"] == 0


def test_extractor_raises_on_restructured_docs() -> None:
    mod = _load("extract_gemini_thinking")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("<html><body>No tables here.</body></html>", source_url="x")


def test_extractor_flags_unexpected_level_model() -> None:
    mod = _load("extract_gemini_thinking")
    html = SAMPLE_HTML.read_text().replace(
        "<th>Gemini 3 Flash</th>",
        "<th>Gemini 4 Flash</th>",
    )
    snap = mod.build_snapshot(html, source_url="x")
    assert "Gemini 4 Flash" in snap["unexpected_models"]
    assert "Gemini 4 Flash" in snap["per_model_levels"]


# --------------------------------------------------------------------------- #
# Token extraction (parser robustness on the real selector)
# --------------------------------------------------------------------------- #


def test_level_vocab_extraction_on_real_selector() -> None:
    mod = _load("validate_effort_conformance")
    selector = REAL_SELECTOR.read_text()
    thinking_flat = mod._collapse(mod.extract_block(selector, mod.THINKING_BLOCK))
    vocab = mod.gemini_level_tokens(thinking_flat)
    assert vocab == {"minimal", "low", "medium", "high"}


# --------------------------------------------------------------------------- #
# Conformance gate (check E)
# --------------------------------------------------------------------------- #


def test_conformance_passes_on_committed_artifacts() -> None:
    result = _run_conformance(REAL_SELECTOR)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout


def test_conformance_flags_undocumented_gemini_level(tmp_path: Path) -> None:
    """E1 subset: an undocumented level in the Gemini bullet enumeration -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`minimal`, `low`, `medium`, `high` (not every",
        "`minimal`, `low`, `medium`, `high`, `ultra` (not every",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E" in result.stderr
    assert "ultra" in result.stderr


def test_conformance_flags_documented_level_missing(tmp_path: Path) -> None:
    """E1 completeness: dropping `high` from the bullet enumeration -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`minimal`, `low`, `medium`, `high` (not every",
        "`minimal`, `low`, `medium` (not every",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E" in result.stderr
    assert "high" in result.stderr


def test_conformance_flags_unsupported_per_model_level(tmp_path: Path) -> None:
    """E2: affirmatively tying Gemini 3.1 Pro to `minimal` (which it lacks) -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "</thinking-context>",
        "    Gemini 3.1 Pro runs at `minimal` thinking by default.\n  </thinking-context>",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E (gemini per-model)" in result.stderr
    assert "Gemini 3.1 Pro" in result.stderr


def test_conformance_flags_dropped_dynamic_sentinel(tmp_path: Path) -> None:
    """E3: removing the -1/dynamic sentinel acknowledgement -> FAIL."""
    drifted = (
        REAL_SELECTOR.read_text()
        .replace("`-1`", "`none`")
        .replace("dynamic", "static")
        .replace("Dynamic", "Static")
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E (gemini sentinels)" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
