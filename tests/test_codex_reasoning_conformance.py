"""Tests for the Codex reasoning-effort docs extractor + conformance check.

Covers ``update/extract_codex_reasoning.py`` (deterministic parse of the
in-scope Codex config keys, offline, against a committed sample slice) and the
provider-aware Codex check (check D) added to
``update/validate_effort_conformance.py`` — the per-PR gate that the selector's
OpenAI/Codex reasoning vocabulary stays consistent with Codex's config docs:

- Extractor parses the four in-scope config-key enumerations from the sample
  config-reference.md slice, and isolates the same span the docs-freshness cron
  will hash.
- Extractor fails loudly when the docs are restructured (missing / reordered
  keys) and flags an unexpected reasoning value rather than absorbing it.
- The bullet / mapping token extractors pull the right reasoning tokens from the
  real selector despite hard-wrapping and the parenthetical model-id example.
- Conformance PASSES on the committed selector + committed Codex snapshot (this
  is the real CI gate — a drifting selector edit makes it red).
- Conformance FAILS on an undocumented reasoning token (subset) and on a
  documented level dropped from the bullet or the mapping (completeness).
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
EXTRACTOR = UPDATE_DIR / "extract_codex_reasoning.py"
CONFORMANCE = UPDATE_DIR / "validate_effort_conformance.py"
SAMPLE_MD = REPO_ROOT / "tests" / "fixtures" / "codex-config-reference-sample.md"

# The real committed artifacts the per-PR gate runs against.
REAL_SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"
REAL_CC_SNAPSHOT = UPDATE_DIR / "claude-code-effort.json"
REAL_CODEX_SNAPSHOT = UPDATE_DIR / "codex-reasoning.json"


def _load(name: str):  # type: ignore[no-untyped-def]
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def _run_conformance(
    selector: Path, snapshot: Path, codex_snapshot: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CONFORMANCE),
            "--selector",
            str(selector),
            "--snapshot",
            str(snapshot),
            "--codex-snapshot",
            str(codex_snapshot),
        ],
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #


def test_extractor_parses_in_scope_keys() -> None:
    mod = _load("extract_codex_reasoning")
    snapshot = mod.build_snapshot(SAMPLE_MD.read_text(), source_url="file://sample")

    assert snapshot["reasoning_effort"] == ["minimal", "low", "medium", "high", "xhigh"]
    assert snapshot["plan_mode_reasoning_effort"] == [
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert snapshot["model_reasoning_summary"] == ["auto", "concise", "detailed", "none"]
    assert snapshot["model_verbosity"] == ["low", "medium", "high"]
    assert snapshot["xhigh_model_dependent"] is True
    assert snapshot["unexpected_effort_values"] == []
    assert len(snapshot["section_sha256"]) == 64


def test_extractor_isolates_only_the_in_scope_span() -> None:
    mod = _load("extract_codex_reasoning")
    span = mod.isolate_in_scope(SAMPLE_MD.read_text())
    # The span is bounded by the first/last in-scope key; the neighbouring keys
    # kept in the fixture must NOT leak in.
    assert "model_reasoning_effort" in span
    assert "model_verbosity" in span
    assert "amazon-bedrock" not in span
    assert "model_supports_reasoning_summaries" not in span


def test_extractor_cli_writes_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "codex.json"
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), "--input", str(SAMPLE_MD), "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    assert data["reasoning_effort"] == ["minimal", "low", "medium", "high", "xhigh"]


def test_committed_snapshot_matches_extractor_on_fixture() -> None:
    """The committed snapshot's reasoning vocabulary must equal what the
    extractor produces from the faithful fixture slice — a guard that the
    committed copy was not hand-edited away from the docs."""
    mod = _load("extract_codex_reasoning")
    fixture = mod.build_snapshot(SAMPLE_MD.read_text(), source_url="file://sample")
    committed = json.loads(REAL_CODEX_SNAPSHOT.read_text())
    for key in ("reasoning_effort", "plan_mode_reasoning_effort", "model_verbosity"):
        assert committed[key] == fixture[key], key
    # The fixture is a byte-faithful slice, so the in-scope span hash matches.
    assert committed["section_sha256"] == fixture["section_sha256"]


def test_extractor_raises_on_restructured_docs() -> None:
    mod = _load("extract_codex_reasoning")
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot("# Some other page\n\nNo config table here.\n", source_url="x")


def test_extractor_raises_on_reordered_keys() -> None:
    mod = _load("extract_codex_reasoning")
    md = SAMPLE_MD.read_text()
    # Remove model_verbosity entirely → the end-key anchor is gone.
    md = md.replace('key: "model_verbosity"', 'key: "model_some_other_thing"')
    with pytest.raises(mod.ExtractError):
        mod.build_snapshot(md, source_url="x")


def test_extractor_flags_unexpected_effort_value() -> None:
    mod = _load("extract_codex_reasoning")
    md = SAMPLE_MD.read_text().replace(
        '"minimal | low | medium | high | xhigh"',
        '"minimal | low | medium | high | xhigh | ultra"',
        1,
    )
    snap = mod.build_snapshot(md, source_url="x")
    assert "ultra" in snap["unexpected_effort_values"]
    assert "ultra" in snap["reasoning_effort"]


# --------------------------------------------------------------------------- #
# Token extraction (parser robustness on the real selector)
# --------------------------------------------------------------------------- #


def test_bullet_and_mapping_token_extraction_on_real_selector() -> None:
    mod = _load("validate_effort_conformance")
    selector = REAL_SELECTOR.read_text()
    thinking_flat = mod._collapse(mod.extract_block(selector, mod.THINKING_BLOCK))

    bullet = mod.openai_bullet_reasoning_tokens(thinking_flat)
    mapping = mod.openai_mapping_reasoning_tokens(thinking_flat)

    expected = {"minimal", "low", "medium", "high", "xhigh"}
    assert bullet == expected
    # The mapping must NOT pick up the `gpt-5.3-codex-high` model-id example in
    # the parenthetical, and `extra-high` must normalize to `xhigh`.
    assert mapping == expected


# --------------------------------------------------------------------------- #
# Conformance gate (check D)
# --------------------------------------------------------------------------- #


def test_conformance_passes_on_committed_artifacts() -> None:
    """The real gate: committed selector must conform to the committed snapshots."""
    result = _run_conformance(REAL_SELECTOR, REAL_CC_SNAPSHOT, REAL_CODEX_SNAPSHOT)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout


def test_conformance_flags_undocumented_codex_reasoning_token(tmp_path: Path) -> None:
    """Check D subset: an undocumented reasoning value in the OpenAI bullet → FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`xhigh` (the top",
        "`xhigh`, `ultra` (the top",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_CC_SNAPSHOT, REAL_CODEX_SNAPSHOT)
    assert result.returncode == 1
    assert "check D" in result.stderr
    assert "ultra" in result.stderr


def test_conformance_flags_documented_level_missing_from_bullet(tmp_path: Path) -> None:
    """Check D completeness: dropping xhigh from the bullet enumeration → FAIL.

    This is exactly the drift this tracker reconciled — the docs document
    ``xhigh`` but the bullet omitted it.
    """
    original = REAL_SELECTOR.read_text()
    # Anchor on the LEVEL ENUMERATION, not on the prose that introduces it.
    # This used to include the words "reasoning-effort knob — ", so when the
    # Codex cron renamed that to "`reasoning_effort` knob" the replace matched
    # nothing, `drifted` came back identical to the committed selector, and the
    # test asserted that a PASSING gate fails — it stopped testing drift and
    # started testing the prose. Same failure mode as #526.
    drifted = original.replace(
        "`minimal`, `low`, `medium`, `high`,\n"
        '      `xhigh` (the top "Extra High" tier; model-dependent). Higher',
        "`minimal`, `low`, `medium`, `high`. Higher",
    )
    assert drifted != original, (
        "the drift edit matched nothing — the selector's OpenAI level "
        "enumeration was reworded, so this test is no longer exercising check D"
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_CC_SNAPSHOT, REAL_CODEX_SNAPSHOT)
    assert result.returncode == 1
    assert "check D" in result.stderr
    assert "xhigh" in result.stderr


def test_conformance_flags_undocumented_token_in_mapping(tmp_path: Path) -> None:
    """Check D: an undocumented reasoning token on the LEFT of a mapping arrow
    (and a documented one dropped) → FAIL."""
    drifted = REAL_SELECTOR.read_text().replace(
        "`medium` → `Medium`",
        "`tiny` → `Medium`",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_CC_SNAPSHOT, REAL_CODEX_SNAPSHOT)
    assert result.returncode == 1
    assert "check D" in result.stderr
    assert "tiny" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# --------------------------------------------------------------------------- #
# The 2026-09-22 docs reshape: vocabulary moved from `type` into prose
# --------------------------------------------------------------------------- #

# The exact post-reshape shape OpenAI published: `model_reasoning_effort` and
# `plan_mode_reasoning_effort` typed as a bare `string`, the reasoning values
# living in the description; summary / verbosity unchanged.
_RESHAPED_SPAN = """
    {
      key: "model_reasoning_effort",
      type: "string",
      description:
        "Reasoning effort advertised by the selected model, such as `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`. Available levels depend on the model and client.",
    },
    {
      key: "plan_mode_reasoning_effort",
      type: "string",
      description:
        "Plan-mode-specific reasoning override using a level supported by the selected model. When unset, Plan mode uses its built-in preset default.",
    },
    {
      key: "model_reasoning_summary",
      type: "auto | concise | detailed | none",
      description: "Select reasoning summary detail or disable summaries entirely.",
    },
    {
      key: "model_verbosity",
      type: "low | medium | high",
      description: "Optional GPT-5 Responses API verbosity override.",
    },
"""


def test_extractor_reads_a_vocabulary_that_moved_into_the_description() -> None:
    """The bug that failed the 2026-09-22 cron: reading the bare `type` of a
    `string`-typed key yields ["string"] — a type NAME, not a value — and the
    extractor then wrote that as the entire Codex reasoning vocabulary."""
    mod = _load("extract_codex_reasoning")
    effort = mod.parse_type_enum(_RESHAPED_SPAN, "model_reasoning_effort")
    assert effort == ["low", "medium", "high", "xhigh", "max", "ultra"]
    assert "string" not in effort


def test_a_key_that_defers_to_the_selected_model_inherits_its_vocabulary() -> None:
    """Plan mode now takes "a level supported by the selected model" and names
    none itself; it inherits the reasoning set rather than failing or guessing."""
    mod = _load("extract_codex_reasoning")
    effort = mod.parse_type_enum(_RESHAPED_SPAN, "model_reasoning_effort")
    plan = mod.parse_type_enum(_RESHAPED_SPAN, "plan_mode_reasoning_effort", inherit=effort)
    assert plan == effort


def test_a_string_key_with_no_values_and_nothing_to_inherit_fails_loud() -> None:
    """Never guess a vocabulary. Without values in the prose AND without an
    inherited set, the docs changed shape again and a human should look."""
    mod = _load("extract_codex_reasoning")
    with pytest.raises(mod.ExtractError, match="names no values"):
        mod.parse_type_enum(_RESHAPED_SPAN, "plan_mode_reasoning_effort")


def test_enum_typed_keys_are_unaffected_by_the_reshape() -> None:
    mod = _load("extract_codex_reasoning")
    assert mod.parse_type_enum(_RESHAPED_SPAN, "model_reasoning_summary") == [
        "auto",
        "concise",
        "detailed",
        "none",
    ]
    assert mod.parse_type_enum(_RESHAPED_SPAN, "model_verbosity") == ["low", "medium", "high"]


def test_new_top_rungs_are_flagged_so_the_selector_gets_a_mapping(tmp_path: Path) -> None:
    """`max` and `ultra` are outside the known baseline. They must be FLAGGED,
    not silently absorbed: each needs a THINKING/EFFORT mapping in the
    selector, which the cron's review pass adds and check D then enforces."""
    mod = _load("extract_codex_reasoning")
    md = "## config.toml\n<ConfigTable\n  options={[" + _RESHAPED_SPAN + "  ]}\n/>\n"
    snap = mod.build_snapshot(md, source_url="https://example.invalid/cfg.md")
    assert snap["reasoning_effort"] == ["low", "medium", "high", "xhigh", "max", "ultra"]
    assert snap["unexpected_effort_values"] == ["max", "ultra"]
