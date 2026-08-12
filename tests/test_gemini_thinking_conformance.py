"""Tests for the Gemini thinking docs extractor + conformance check.

Covers ``update/extract_gemini_thinking.py`` (deterministic bs4 parse of the
unified discrete-level table, offline, against a committed HTML slice) and the
provider-aware Gemini check (check E) in
``update/validate_effort_conformance.py``.

As of 2026-06 Google unified the Gemini reasoning surface onto a single discrete
thinking-level table (``Model | Default Thinking | Levels Supported``) spanning
the 3.x and 2.5 generations; the numeric 2.5 ``thinkingBudget`` table was retired
upstream and is no longer parsed or tracked.

- Extractor parses the level table (Gemini 3 Pro is low/high; 2.5 models use the
  same discrete levels) and keys it by selector display name.
- Extractor fails loudly when the docs are restructured (anchors gone) and flags
  an unexpected model / a newly documented level rather than absorbing it.
- The level-vocabulary extractor pulls the right tokens from the real selector.
- Conformance PASSES on the committed selector + committed Gemini snapshot.
- Conformance FAILS on an undocumented level (subset), a documented level dropped
  from the bullet (completeness), and a per-model tie the docs disallow
  (Gemini 3 Pro -> medium).
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


def _run_conformance(
    selector: Path, gemini_snapshot: Path = REAL_GEMINI_SNAPSHOT
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
            str(gemini_snapshot),
        ],
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #


def test_extractor_parses_level_table() -> None:
    mod = _load("extract_gemini_thinking")
    snap = mod.build_snapshot(SAMPLE_HTML.read_text(), source_url="file://sample")

    assert snap["thinking_levels"] == ["low", "medium", "high"]
    assert snap["per_model_levels"]["Gemini 3.1 Pro"] == ["low", "medium", "high"]
    # The subset model: Gemini 3 Pro supports only low/high (no medium).
    assert snap["per_model_levels"]["Gemini 3 Pro"] == ["low", "high"]
    # 2.5 models now use the same discrete levels.
    assert snap["per_model_levels"]["Gemini 2.5 Flash"] == ["low", "medium", "high"]
    assert snap["level_defaults"]["Gemini 3.1 Pro"] == "high"
    assert snap["level_defaults"]["Gemini 3.5 Flash"] == "medium"
    assert snap["level_defaults"]["Gemini 2.5 Flash-Lite"] == "off"

    assert snap["unexpected_models"] == []
    assert snap["unexpected_levels"] == []
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
    assert data["thinking_levels"] == ["low", "medium", "high"]


def test_committed_snapshot_invariants() -> None:
    """The committed snapshot must carry the SHAPE the gate relies on.

    Deliberately asserts structure, not the level list itself. Pinning the exact
    vocabulary (``["low", "medium", "high"]``) meant that the day Google
    documented a new tier, this test went red and the DeepSeek/Gemini lanes
    stopped — the tracker had correctly detected a real upstream change and CI
    read it as breakage. Completeness of the selector's mapping for whatever
    levels ARE documented is enforced by conformance check E, which fails loudly
    and specifically; that is the right place for it.
    """
    snap = json.loads(REAL_GEMINI_SNAPSHOT.read_text())
    levels = snap["thinking_levels"]
    assert isinstance(levels, list) and levels, "thinking_levels must be non-empty"
    assert len(levels) == len(set(levels)), f"duplicate levels: {levels}"
    per_model = snap["per_model_levels"]
    assert isinstance(per_model, dict) and per_model
    for model, rows in per_model.items():
        assert rows, f"{model} has an empty level row"
        assert set(rows) <= set(levels), (
            f"{model} row {rows} contains a level absent from thinking_levels {levels}"
        )
    # The retired numeric-budget keys must NOT come back.
    assert "per_model_budget" not in snap
    assert "budget_sentinels" not in snap


def test_extractor_raises_on_restructured_docs() -> None:
    mod = _load("extract_gemini_thinking")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("<html><body>No tables here.</body></html>", source_url="x")


def test_extractor_flags_unexpected_level_model() -> None:
    mod = _load("extract_gemini_thinking")
    html = SAMPLE_HTML.read_text().replace(
        "gemini-3-flash-preview",
        "gemini-4-flash-preview",
    )
    snap = mod.build_snapshot(html, source_url="x")
    assert "Gemini 4 Flash" in snap["unexpected_models"]
    assert "Gemini 4 Flash" in snap["per_model_levels"]


def test_extractor_flags_a_new_thinking_level() -> None:
    """A docs-added thinking LEVEL (a new tier beyond the known baseline) must be
    CAPTURED — flowed into thinking_levels + per_model_levels and surfaced in
    unexpected_levels — not silently dropped. Closes the silent-miss gap."""
    mod = _load("extract_gemini_thinking")
    # The "low, high" cell is unique to the Gemini 3 Pro row.
    html = SAMPLE_HTML.read_text().replace("low, high</td>", "low, high, ultra</td>")
    snap = mod.build_snapshot(html, source_url="x")
    assert "ultra" in snap["thinking_levels"]
    assert "ultra" in snap["unexpected_levels"]
    assert "ultra" in snap["per_model_levels"]["Gemini 3 Pro"]


def test_conformance_demands_a_newly_documented_level(tmp_path: Path) -> None:
    """The teeth: if the docs add a thinking level (snapshot has it) the selector
    does NOT yet enumerate, the gate FAILS (E1 completeness) — so a new tier can
    never slip through silently."""
    snap = json.loads(REAL_GEMINI_SNAPSHOT.read_text())
    snap["thinking_levels"] = [*snap["thinking_levels"], "ultra"]
    drifted_snapshot = tmp_path / "gemini.json"
    drifted_snapshot.write_text(json.dumps(snap))

    result = _run_conformance(REAL_SELECTOR, gemini_snapshot=drifted_snapshot)
    assert result.returncode == 1
    assert "check E (gemini levels)" in result.stderr
    assert "ultra" in result.stderr


# --------------------------------------------------------------------------- #
# Token extraction (parser robustness on the real selector)
# --------------------------------------------------------------------------- #


def test_level_vocab_extraction_on_real_selector() -> None:
    mod = _load("validate_effort_conformance")
    selector = REAL_SELECTOR.read_text()
    thinking_flat = mod._collapse(mod.extract_block(selector, mod.THINKING_BLOCK))
    vocab = mod.gemini_level_tokens(thinking_flat)
    documented = {
        lv.lower() for lv in json.loads(REAL_GEMINI_SNAPSHOT.read_text())["thinking_levels"]
    }
    # The CONTRACT is selector == docs, not selector == a list frozen in a test.
    assert vocab == documented


# --------------------------------------------------------------------------- #
# Conformance gate (check E)
# --------------------------------------------------------------------------- #


def test_conformance_passes_on_committed_artifacts() -> None:
    result = _run_conformance(REAL_SELECTOR)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout


def _documented_levels() -> list[str]:
    """The committed snapshot's level list, in documented order."""
    return [
        str(lv).lower() for lv in json.loads(REAL_GEMINI_SNAPSHOT.read_text())["thinking_levels"]
    ]


def _committed_enumeration() -> str:
    """The selector's level enumeration, rebuilt from the snapshot.

    These drift tests used to splice a LITERAL slice of the selector
    (``"`low`, `medium`, `high` — across"``). That silently becomes a no-op the
    moment the vocabulary changes — the "drifted" selector would be byte-identical
    to the real one, the gate would pass, and the test would fail for a reason
    that has nothing to do with what it is checking. Deriving the string keeps
    the drift real whatever the documented vocabulary is.
    """
    return ", ".join(f"`{lv}`" for lv in _documented_levels())


def test_conformance_flags_undocumented_gemini_level(tmp_path: Path) -> None:
    """E1 subset: an undocumented level in the Gemini bullet enumeration -> FAIL."""
    enumeration = _committed_enumeration()
    drifted = REAL_SELECTOR.read_text().replace(enumeration, enumeration + ", `ultra`")
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E" in result.stderr
    assert "ultra" in result.stderr


def test_conformance_flags_documented_level_missing(tmp_path: Path) -> None:
    """E1 completeness: dropping a documented level from the bullet -> FAIL."""
    enumeration = _committed_enumeration()
    # Drop the LAST documented level from the bullet, and name that same level in
    # the assertion — hardcoding it would silently stop testing what it claims
    # the moment the vocabulary changes.
    levels = _documented_levels()
    dropped = levels[-1]
    drifted = REAL_SELECTOR.read_text().replace(
        enumeration, ", ".join(f"`{lv}`" for lv in levels[:-1])
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E" in result.stderr
    assert dropped in result.stderr


def test_conformance_flags_unsupported_per_model_level(tmp_path: Path) -> None:
    """E2: affirmatively tying Gemini 3 Pro to `medium` (which it lacks) -> FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "</thinking-context>",
        "    Gemini 3 Pro runs at `medium` thinking by default.\n  </thinking-context>",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)
    result = _run_conformance(selector)
    assert result.returncode == 1
    assert "check E (gemini per-model)" in result.stderr
    assert "Gemini 3 Pro" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
