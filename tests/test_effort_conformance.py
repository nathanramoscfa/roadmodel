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
- Conformance FAILS on an undocumented value in the EFFORT enum (check A1), an
  effort word smuggled back into the THINKING toggle (check A2 — the v1
  ``THINKING: Max`` regression), an unsupported per-model effort claim
  (check B), and ultracode/ultrathink conflation (check C).
- ``Ultracode`` passes check A only while the docs snapshot still documents
  ultracode as a real ``/effort`` setting — the acceptance is evidence-based,
  not a hardcoded allowance.
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
# The live in-scope span as published 2026-09-04, captured verbatim. The docs
# reworded the ultrathink pass-through sentence in mid-August, which the
# extractor's prose-fragment anchor treated as a restructure — it failed every
# day from 2026-08-12 to 2026-09-04 over a rewrite that changed no fact it
# parses. SAMPLE_MD keeps the older wording, so the pair pins both.
LIVE_MD = REPO_ROOT / "tests" / "fixtures" / "model-config-sample-2026-09.md"

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


def test_parse_effort_table_splits_oxford_comma_list() -> None:
    """Regression: the live docs (2026-07-14) list a row's models as an
    Oxford-comma list ("Sonnet 5, Opus 4.8, and Opus 4.7"), not just "and".
    Splitting on "and" alone left the bogus name "Sonnet 5, Opus 4.8," which
    the tracker flagged as a new model every day (11 dup issues). Each named
    model must become its own key; no comma-joined fragment survives."""
    mod = _load_extractor()
    table = (
        "| Model | Levels |\n"
        "| --- | --- |\n"
        "| Sonnet 5, Opus 4.8, and Opus 4.7 | `low`, `high`, `max` |\n"
        "| Opus 4.6 and Sonnet 4.6 | `low`, `high` |\n"
    )
    per_model = mod.parse_effort_table(table)

    assert set(per_model) == {"Sonnet 5", "Opus 4.8", "Opus 4.7", "Opus 4.6", "Sonnet 4.6"}
    assert not any("," in name for name in per_model), (
        f"comma-joined name survived: {list(per_model)}"
    )
    assert per_model["Sonnet 5"] == ["low", "high", "max"]
    assert per_model["Opus 4.7"] == ["low", "high", "max"]
    assert per_model["Sonnet 4.6"] == ["low", "high"]


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
    """Check A1: an undocumented value in the EFFORT enum → FAIL.

    Output contract v2 moved the reasoning scale out of THINKING and into
    EFFORT, so EFFORT is the enum the vocabulary check must police.
    """
    drifted = REAL_SELECTOR.read_text().replace(
        "EFFORT: [Low/Medium/High/XHigh/Max/Ultracode]",
        "EFFORT: [Low/Medium/High/XHigh/Max/Ultracode/Ultra]",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "check A" in result.stderr
    assert "Ultra" in result.stderr


def test_conformance_flags_effort_word_in_thinking_toggle(tmp_path: Path) -> None:
    """Check A2: an effort word back in the THINKING enum → FAIL.

    ``THINKING: Max`` is the v1 bug the EFFORT/THINKING split exists to kill: no
    surface's thinking toggle has a `Max` position, so it is a setting no
    operator can apply. A cron re-merging the two fields must go red.
    """
    drifted = REAL_SELECTOR.read_text().replace(
        "THINKING: [On/Off]",
        "THINKING: [On/Off/Max]",
    )
    selector = tmp_path / "selector.txt"
    selector.write_text(drifted)

    result = _run_conformance(selector, REAL_SNAPSHOT)
    assert result.returncode == 1
    assert "check A (thinking toggle)" in result.stderr
    assert "Max" in result.stderr


def test_conformance_ultracode_acceptance_is_snapshot_gated(tmp_path: Path) -> None:
    """``Ultracode`` is accepted in EFFORT only on the snapshot's own evidence.

    It is not a row in the docs' effort table — it is the session SETTING set
    through the same `/effort` command. Demote it in the snapshot (docs retire
    it) and the selector's `Ultracode` value must fail check A rather than ride
    a hardcoded allowance.
    """
    snapshot = json.loads(REAL_SNAPSHOT.read_text())
    assert snapshot["ultracode"]["is_setting"] is True  # the fact being relied on
    snapshot["ultracode"]["is_setting"] = False
    drifted_snapshot = tmp_path / "effort.json"
    drifted_snapshot.write_text(json.dumps(snapshot))

    result = _run_conformance(REAL_SELECTOR, drifted_snapshot)
    assert result.returncode == 1
    assert "check A (effort vocabulary)" in result.stderr
    assert "Ultracode" in result.stderr


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


def test_extractor_parses_the_current_live_docs_wording() -> None:
    """Regression for the 24-day outage: the 2026-09 docs must parse.

    The docs reworded '... are not recognized as keywords' to '... doesn't
    recognize them as keywords'. The extractor anchored on the prose fragment
    rather than the fact, so it exited 4 ("expected docs anchors missing
    (restructure?)") every day while the facts it extracts were unchanged.
    """
    mod = _load_extractor()
    snapshot = mod.build_snapshot(LIVE_MD.read_text(), source_url="file://live")

    # Every model row the current table lists, including the two added since
    # the older fixture was captured.
    assert snapshot["per_model_effort"]["Fable 5.1"] == ["low", "medium", "high", "xhigh", "max"]
    assert snapshot["per_model_effort"]["Opus 5"] == ["low", "medium", "high", "xhigh", "max"]
    assert snapshot["per_model_effort"]["Sonnet 4.6"] == ["low", "medium", "high", "max"]
    assert snapshot["effort_levels"] == ["low", "medium", "high", "xhigh", "max"]

    # The reworded sentence still yields the pass-through keyword facts.
    assert snapshot["ultrathink"]["is_per_turn_keyword"] is True
    assert snapshot["ultrathink"]["changes_session_effort"] is False
    assert "think hard" in snapshot["ultrathink"]["not_recognized"]

    # ultracode stays a setting that sends xhigh — the gate depends on it.
    assert snapshot["ultracode"]["is_setting"] is True
    assert snapshot["ultracode"]["sends_effort"] == "xhigh"

    # Both no-disable models, not just the last one in the sentence.
    assert snapshot["extended_thinking"]["cannot_disable_on"] == ["Fable 5.1", "Fable 5"]

    # The docs moved the default-effort fact from a sentence into a list item;
    # "*" is the blanket default, with per-model carve-outs beside it.
    assert snapshot["default_effort"] == {"*": "high", "Opus 4.7": "xhigh"}

    # Opus 5 is in the catalog already; Fable 5.1 is not, so it — and only it —
    # is handed to the catalog cron.
    assert snapshot["unexpected_models"] == ["Fable 5.1"]


def test_extractor_survives_prose_rewording_around_its_facts() -> None:
    """Anchors must track facts, not sentence grammar.

    Paraphrasing the sentences that carry the in-scope facts, while leaving
    the facts themselves intact, must NOT read as a restructure.
    """
    mod = _load_extractor()
    md = (
        LIVE_MD.read_text()
        .replace(
            "Claude Code passes other phrases such as",
            "Claude Code treats other phrases, among them",
        )
        .replace("and doesn't recognize them as keywords.", "as plain text.")
    )
    snapshot = mod.build_snapshot(md, source_url="x")
    assert "think hard" in snapshot["ultrathink"]["not_recognized"]


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


# --------------------------------------------------------------------------- #
# Provider-bullet locators (issue #517)
#
# Checks D/E/F used to find each provider's enumeration by grepping a prose
# phrase out of the whole <thinking-context>. That prose is written by the same
# cron Opus pass the checks gate, so a legitimate reword ("reasoning-effort
# knob" -> "`reasoning_effort` knob") made the anchor miss, check D report
# "could not find the enumeration", and the Codex lane deadlock: the gate is
# fatal and runs BEFORE the PR-open step, so every later run retried the same
# edit and failed the same way.
#
# These pin the two properties that fix requires: TOLERANT to rewording, still
# STRICT about content.
# --------------------------------------------------------------------------- #

# A miniature <thinking-context> with the same bullet shape as the real one:
# a dial-description list, then an output-mapping list.
_BULLETS = """    - OpenAI (Codex, OpenAI API): {openai_dial} — `minimal`, `low`,
      `medium`, `high`, `xhigh` (the top tier; model-dependent).
    - Gemini (Google API, Gemini CLI): a discrete {gemini_dial} —
      `low`, `medium`, `high` — across generations.
    - DeepSeek (DeepSeek API): a thinking toggle (`enabled` /
      `disabled`, default `enabled`) plus a {deepseek_dial} —
      `high`, `max` (default `high`).
    - OpenAI `minimal` \u2192 `Off`; `low` \u2192 `Low`; `medium` \u2192 `Medium`;
      `high` \u2192 `High`; `xhigh` (e.g. `gpt-5.3-codex-high`) \u2192 `XHigh`.
"""


def _thinking(
    openai_dial="reasoning-effort knob",
    gemini_dial="thinking-level knob",
    deepseek_dial="reasoning-effort enum",
):
    mod = _load_conformance()
    text = _BULLETS.format(
        openai_dial=openai_dial, gemini_dial=gemini_dial, deepseek_dial=deepseek_dial
    )
    return mod, mod._collapse(text)


@pytest.mark.parametrize(
    "dial",
    [
        "reasoning-effort knob",  # the original wording
        "`reasoning_effort` knob",  # the exact reword that deadlocked the lane
        "reasoning_effort control",
        "reasoning effort levels",
        "reasoning-effort dial",
    ],
)
def test_codex_enumeration_survives_dial_rewording(dial: str) -> None:
    mod, flat = _thinking(openai_dial=dial)
    assert mod.openai_bullet_reasoning_tokens(flat) == {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }, f"dial wording {dial!r} broke the OpenAI enumeration locator"


@pytest.mark.parametrize(
    "dial",
    [
        "thinking-level knob",
        "thinking level control",
        "`thinking_level` setting",
        "thinking levels",
    ],
)
def test_gemini_enumeration_survives_dial_rewording(dial: str) -> None:
    mod, flat = _thinking(gemini_dial=dial)
    assert mod.gemini_level_tokens(flat) == {"low", "medium", "high"}


def test_deepseek_enumeration_survives_rename_that_collides_with_openai() -> None:
    """DeepSeek renamed to OpenAI's noun must NOT pick up OpenAI's levels.

    The old code told the two apart by "knob" (OpenAI) vs "enum" (DeepSeek), so
    this rename would have silently cross-contaminated them. Bullet scoping
    makes the noun irrelevant.
    """
    mod, flat = _thinking(deepseek_dial="reasoning-effort knob")
    assert mod.deepseek_effort_tokens(flat) == {"high", "max"}
    assert mod.openai_bullet_reasoning_tokens(flat) == {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }


def test_deepseek_toggle_scoped_to_its_own_bullet() -> None:
    mod, flat = _thinking()
    assert mod.deepseek_toggle_tokens(flat) == {"enabled", "disabled"}


def test_openai_mapping_not_pinned_to_vocabulary_endpoints() -> None:
    """The mapping locator must not hardcode the first/last level.

    The old anchor was ``OpenAI `minimal` ... \u2192 `XHigh```, so adding a tier at
    either end emptied the set and the check reported "could not find the
    mapping" instead of the real disagreement.
    """
    mod, flat = _thinking()
    assert mod.openai_mapping_reasoning_tokens(flat) == {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }


def test_enumeration_falls_back_when_no_dial_phrase_matches() -> None:
    """An unrecognisable dial noun degrades to the structural locator, not to empty.

    Empty is what deadlocked the lane; a slightly-less-precise read keeps it moving.
    """
    mod, flat = _thinking(openai_dial="wibble")
    assert mod.openai_bullet_reasoning_tokens(flat) == {
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }


def test_fallback_ignores_lone_backticked_non_levels() -> None:
    """A single backticked config key or model id is not an enumeration."""
    mod = _load_conformance()
    assert (
        mod._fallback_enumeration("- Foo (bar): set `MAX_THINKING_TOKENS=0` to disable.") == set()
    )
    assert mod._fallback_enumeration("- Foo (bar): `low`, `high` are the levels.") == {
        "low",
        "high",
    }


def test_missing_provider_bullet_is_still_a_failure() -> None:
    """Tolerance is about WORDING only — a genuinely absent bullet must be caught."""
    mod = _load_conformance()
    flat = mod._collapse("    - Gemini (Google API): a thinking-level knob — `low`, `high`.\n")
    assert mod.openai_bullet_reasoning_tokens(flat) == set()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
