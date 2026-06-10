"""Tests for the Claude Code effort/thinking docs extractor + conformance gate.

Covers ``update/extract_claude_code_effort.py`` (deterministic parse of the
in-scope docs sections, offline, against a committed sample slice) and
``update/validate_effort_conformance.py`` (the per-PR gate that the selector's
Claude Code effort/thinking vocabulary stays consistent with the docs):

- Extractor parses the per-model effort matrix + ultracode/ultrathink facts
  from the sample model-config.md slice.
- Extractor fails loudly when the docs are restructured.
- Conformance PASSES on the committed selector + committed docs snapshot
  (this is the real CI gate — a drifting selector edit makes it red).
- Conformance FAILS on an undocumented effort level (check A), an unsupported
  per-model effort claim (check B), and ultracode/ultrathink conflation
  (check C).
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
EXTRACTOR = UPDATE_DIR / "extract_claude_code_effort.py"
CONFORMANCE = UPDATE_DIR / "validate_effort_conformance.py"
SAMPLE_MD = REPO_ROOT / "tests" / "fixtures" / "model-config-sample.md"

# The real committed artifacts the per-PR gate runs against.
REAL_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"
REAL_SNAPSHOT = UPDATE_DIR / "claude-code-effort.json"


def _load_extractor():
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module("extract_claude_code_effort")
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def _load_conformance():
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module("validate_effort_conformance")
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def _run_conformance(selector: Path, snapshot: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CONFORMANCE),
            "--selector",
            str(selector),
            "--snapshot",
            str(snapshot),
        ],
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #


def test_extractor_parses_in_scope_sections() -> None:
    mod = _load_extractor()
    snapshot = mod.build_snapshot(SAMPLE_MD.read_text(), source_url="file://sample")

    assert snapshot["per_model_effort"] == {
        "Fable 5": ["low", "medium", "high", "xhigh", "max"],
        "Opus 4.8": ["low", "medium", "high", "xhigh", "max"],
        "Opus 4.7": ["low", "medium", "high", "xhigh", "max"],
        "Opus 4.6": ["low", "medium", "high", "max"],
        "Sonnet 4.6": ["low", "medium", "high", "max"],
    }
    # Sonnet 4.6 / Opus 4.6 do NOT support xhigh — the exact drift the gate guards.
    assert "xhigh" not in snapshot["per_model_effort"]["Sonnet 4.6"]
    assert snapshot["effort_levels"] == ["low", "medium", "high", "xhigh", "max"]

    assert snapshot["default_effort"]["Opus 4.7"] == "xhigh"
    assert snapshot["default_effort"]["Sonnet 4.6"] == "high"

    ultracode = snapshot["ultracode"]
    assert ultracode["is_setting"] is True
    assert ultracode["is_effort_level"] is False
    assert ultracode["sends_effort"] == "xhigh"
    assert ultracode["session_only"] is True
    assert ultracode["orchestrates_workflows"] is True

    ultrathink = snapshot["ultrathink"]
    assert ultrathink["is_per_turn_keyword"] is True
    assert ultrathink["changes_session_effort"] is False
    assert "think hard" in ultrathink["not_recognized"]

    assert snapshot["extended_thinking"]["cannot_disable_on"] == ["Fable 5"]
    assert "Option+T" in snapshot["extended_thinking"]["on_off_controls"]
    assert len(snapshot["section_sha256"]) == 64


def test_extractor_cli_writes_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "effort.json"
    result = subprocess.run(
        [
            sys.executable,
            str(EXTRACTOR),
            "--input",
            str(SAMPLE_MD),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["per_model_effort"]["Opus 4.8"] == ["low", "medium", "high", "xhigh", "max"]


def test_extractor_raises_on_restructured_docs() -> None:
    mod = _load_extractor()
    # Missing the "### Adjust effort level" start heading entirely.
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Some other page\n\nNo effort section here.\n", source_url="x")


# --------------------------------------------------------------------------- #
# Conformance gate
# --------------------------------------------------------------------------- #


def test_conformance_passes_on_committed_artifacts() -> None:
    """The real gate: committed selector must conform to the committed snapshot."""
    result = _run_conformance(REAL_SELECTOR, REAL_SNAPSHOT)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout


def test_conformance_flags_undocumented_effort_level(tmp_path: Path) -> None:
    """Check A: an undocumented value in the THINKING enum → FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "THINKING: [Off/Low/Medium/High/XHigh/N/A]",
        "THINKING: [Off/Low/Medium/High/XHigh/Ultra/N/A]",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "check A" in result.stderr
    assert "Ultra" in result.stderr


def test_conformance_flags_unsupported_per_model_effort(tmp_path: Path) -> None:
    """Check B: tying Sonnet 4.6 to xhigh (which it does not support) → FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "</thinking-context>",
        "    Sonnet 4.6 always runs at xhigh effort.\n  </thinking-context>",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "check B" in result.stderr
    assert "Sonnet 4.6" in result.stderr


def test_conformance_flags_ultracode_ultrathink_conflation(tmp_path: Path) -> None:
    """Check C: dropping the ultrathink distinction entirely → FAIL."""
    drifted = REAL_SELECTOR.read_text().replace("ultrathink", "ultracode")
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "check C" in result.stderr
    assert "ultrathink" in result.stderr


def test_extract_block_anchors_to_real_tag() -> None:
    """The inline `<orchestration-context>` reference inside <thinking-context>
    must not be mistaken for the element's opening tag."""
    mod = _load_conformance()
    selector = REAL_SELECTOR.read_text()
    orch = mod.extract_block(selector, "orchestration-context")
    think = mod.extract_block(selector, "thinking-context")
    assert orch.strip().startswith("Orchestration (Claude Code's Dynamic Workflows")
    assert "</thinking-context>" not in orch
    assert "ultrathink" in think


def test_conformance_flags_wrapped_per_model_effort(tmp_path: Path) -> None:
    """Check B must catch a per-model claim whose model name and effort token
    fall on different (hard-wrapped) lines."""
    drifted = REAL_SELECTOR.read_text().replace(
        "</thinking-context>",
        "    On Sonnet 4.6 the recommender may emit\n"
        "    THINKING `XHigh` here.\n  </thinking-context>",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "check B" in result.stderr
    assert "Sonnet 4.6" in result.stderr


def test_conformance_allows_docs_faithful_fallback_prose(tmp_path: Path) -> None:
    """A correct fallback statement naming a model + an unsupported level
    (mirroring the docs) must NOT be flagged."""
    drifted = REAL_SELECTOR.read_text().replace(
        "</thinking-context>",
        "    On Opus 4.6, an xhigh request falls back to high "
        "(it has no xhigh tier).\n  </thinking-context>",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_conformance_flags_semantic_conflation(tmp_path: Path) -> None:
    """Check C must catch ultrathink described with ultracode's session /
    orchestration semantics even when per-turn decoy markers remain."""
    drifted = REAL_SELECTOR.read_text().replace(
        "on that turn only;",
        "on that turn only; it is ALSO a session setting that sends `xhigh` "
        "for the whole session and orchestrates Dynamic Workflows, exactly "
        "like ultracode;",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "conflation" in result.stderr


def test_extractor_raises_when_ultracode_xhigh_link_lost() -> None:
    """The extractor must fail loud (not emit sends_effort=None) if the docs
    reword the ultracode→xhigh phrasing — that would silently disable the gate."""
    mod = _load_extractor()
    md = SAMPLE_MD.read_text().replace(
        "it sends `xhigh` to the model", "it sends extra-high effort"
    )
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot(md, source_url="x")


def test_extractor_flags_unexpected_model() -> None:
    """A new model row is FLAGGED (catalog cron's lane), parsed but recorded
    in unexpected_models rather than silently absorbed."""
    mod = _load_extractor()
    md = SAMPLE_MD.read_text().replace(
        "| Fable 5                 | `low`, `medium`, `high`, `xhigh`, `max` |",
        "| Fable 5                 | `low`, `medium`, `high`, `xhigh`, `max` |\n"
        "| Haiku 5                 | `low`, `medium`                         |",
    )
    snap = mod.build_snapshot(md, source_url="x")
    assert "Haiku 5" in snap["unexpected_models"]
    assert "Haiku 5" in snap["per_model_effort"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
