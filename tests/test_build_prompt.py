# tests/test_build_prompt.py
"""SaaS prompt-hardening (issues #185/#186/#187/#188/#189).

build_prompt assembles the recommender's system prompt from the bundled
model-selector.txt. Two hardening changes are covered here:

1. The selector's <instruction>/<usage> blocks frame its IDE roadmap-ANNOTATION
   mode ("Execute the requested task in full") — counterproductive for the SaaS
   recommender, which only classifies — so they are stripped from the system
   prompt while the bundled file stays intact for IDE use.
2. A SaaS header front-loads the quality-first / funded-platform / no-thinking /
   classify-don't-execute rules the recommender model most often violates, and
   the user prompt is wrapped in <task-to-classify> so it reads as input.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel.recommend import _strip_ide_framing, build_prompt  # noqa: E402

_UCTX = "## Active subscriptions\nplaceholder user context\n"


def test_build_prompt_strips_ide_annotation_framing() -> None:
    system, _task = build_prompt("pick a model", user_context_text=_UCTX)
    # The IDE annotation framing that licenses task-execution is gone (#187).
    assert "<instruction>" not in system
    assert "</instruction>" not in system
    assert "<usage>" not in system
    assert "Execute the requested task in full" not in system
    # ...but the rest of the selector spec survives.
    assert "<model-selector>" in system
    assert "<selection-algorithm>" in system
    assert "<output-format>" in system


def test_build_prompt_header_front_loads_binding_rules() -> None:
    system, _task = build_prompt("pick a model", user_context_text=_UCTX)
    assert "PROMPT TO CLASSIFY" in system  # classify, don't execute (#187)
    # The objective now FOLLOWS the budget priority (Cost/Balanced/Quality)
    # instead of hard quality-first — and the budget priority itself yields to
    # the FLAT-FUNDING GATE (see the dedicated test below).
    assert "THE BUDGET PRIORITY IS THE OBJECTIVE" in system
    assert "LOWER capability tier" in system
    assert "FUNDED surface" in system  # platform cost posture (#186)
    assert "no thinking dial" in system  # Cursor/xAI expose neither dial (#188)
    assert "multi-file" in system  # category worked example (#189)
    assert "BACKUP is the fallback model" in system  # backup elicited (Step 7)
    # The user context is still appended.
    assert "placeholder user context" in system


def test_build_prompt_header_states_the_conditional_field_set() -> None:
    """Output contract v2: the header must tell the model WHICH lines to emit —
    the four always-on fields, plus only the dials the chosen platform exposes,
    in the fixed order MAX MODE / EFFORT / THINKING / ORCHESTRATION."""
    system, _task = build_prompt("pick a model", user_context_text=_UCTX)
    for field in ("MODEL", "BACKUP", "PLATFORM", "CONVERSATION", "RATIONALE"):
        assert field in system
    assert "MAX MODE" in system
    assert "EFFORT" in system
    assert "ORCHESTRATION" in system
    # D1 — an unexposed dial is an ABSENT line, never a placeholder value.
    assert "OMIT A DIAL THE PLATFORM LACKS" in system
    assert "Never 'Off', never 'N/A'" in system
    # D2 — THINKING is a toggle; the effort word belongs in EFFORT.
    assert "'THINKING: Max' is invalid" in system
    # D3 — Ultracode is the top EFFORT rung, not an orchestration value.
    assert "Ultracode is the TOP rung" in system


def test_build_prompt_header_carries_the_flat_funding_gate() -> None:
    """D4: on a funded flat subscription a lower rung saves the user NOTHING, so
    the header must tell the model to hold the tier and top effort on EVERY
    posture — including Cost — and to SAY SO when the rungs converge instead of
    manufacturing a spread."""
    system, _task = build_prompt("pick a model", user_context_text=_UCTX)
    assert "FLAT-FUNDING GATE" in system
    assert "top useful rung on EVERY posture INCLUDING Cost" in system
    assert "latency, context fit, or blast radius" in system
    assert "SAY SO plainly in the RATIONALE" in system
    # ...while a real per-token path keeps the ordinary tier-down behavior.
    assert "Per-token (pay-per-use) paths keep the ordinary tier-down" in system


def test_build_prompt_ladder_header_is_v2_and_gated() -> None:
    """Ladder mode emits three blocks that may land on three DIFFERENT platforms
    and therefore three different field sets — and the flat-funding gate has to
    outrank the "three distinct tiers" rule, or a $0-funded ladder gets forced
    into a spread that costs quality and saves nothing."""
    system, _ = build_prompt("pick a model", user_context_text=_UCTX, ladder=True)
    assert "LADDER MODE" in system
    assert "OMIT A DIAL THE PLATFORM LACKS" in system
    assert "emit DIFFERENT field sets; that is correct" in system
    assert "THINKING is an On/Off toggle ONLY" in system
    assert "FLAT-FUNDING GATE (see <objective>) OVERRIDES the three rules above" in system
    assert "emit the SAME model and settings for the converged rungs" in system
    # The ordinary ladder rules survive underneath the gate.
    assert "three DISTINCT pricing tiers" in system


def test_build_prompt_wraps_user_prompt_as_input() -> None:
    _system, task = build_prompt("  build a SQL agent  ", user_context_text=_UCTX)
    assert task == "<task-to-classify>\nbuild a SQL agent\n</task-to-classify>"


def test_build_prompt_injects_runtime_availability_override() -> None:
    """A runtime unavailable_models list adds a Step-0a override naming each id —
    the hook the SaaS service uses to bench a model without a package release."""
    system, _task = build_prompt(
        "pick a model",
        user_context_text=_UCTX,
        unavailable_models=["claude-fable-5", "some-other-id"],
    )
    assert "RUNTIME AVAILABILITY OVERRIDE" in system
    assert "Step 0a" in system
    assert "claude-fable-5" in system
    assert "some-other-id" in system


def test_build_prompt_budget_override_steers_cost_below_quality() -> None:
    """The selector's <objective> BUDGET-PRIORITY OVERRIDE must tell the model to
    lower the Cost pick's CAPABILITY TIER and EFFORT (not just its price) where
    the spend is real, and hold the frontier for Quality."""
    system, _ = build_prompt("pick a model", user_context_text=_UCTX)
    assert "BUDGET-PRIORITY OVERRIDE" in system
    assert "lowest-tier model that is still an ADEQUATE fit" in system
    # Quality still holds the frontier at top useful effort.
    assert "highest USEFUL reasoning effort" in system


def test_build_prompt_selector_flat_funding_gate_outranks_the_postures() -> None:
    """D4 in the SELECTOR body (not just the header): when funding is flat the
    gate suspends the Cost posture's tier/effort floors instead of letting it
    trade quality for a saving that does not exist."""
    system, _ = build_prompt("pick a model", user_context_text=_UCTX)
    assert "FLAT-FUNDING GATE" in system
    assert "out-of-pocket price is FLAT across the candidates" in system
    assert "HOLD the capability tier" in system
    assert "on EVERY posture including `cheap`" in system


def test_build_prompt_no_override_without_unavailable_models() -> None:
    """No runtime list (the default, and every CLI/MCP call) → no override section;
    an empty or whitespace-only list is also a no-op."""
    base, _ = build_prompt("pick a model", user_context_text=_UCTX)
    assert "RUNTIME AVAILABILITY OVERRIDE" not in base
    empty, _ = build_prompt("pick a model", user_context_text=_UCTX, unavailable_models=[])
    assert "RUNTIME AVAILABILITY OVERRIDE" not in empty
    blank, _ = build_prompt("pick a model", user_context_text=_UCTX, unavailable_models=["  "])
    assert "RUNTIME AVAILABILITY OVERRIDE" not in blank


def test_build_prompt_authoritative_supersedes_static_fallback() -> None:
    """authoritative=True marks the runtime list as the COMPLETE unavailable set and
    supersedes the <availability-context> fallback — the hook that lets a restored
    model be recommended without a package release."""
    system, _ = build_prompt(
        "pick a model",
        user_context_text=_UCTX,
        unavailable_models=["some-other-id"],
        availability_authoritative=True,
    )
    assert "AUTHORITATIVE" in system
    assert "some-other-id" in system


def test_build_prompt_authoritative_empty_reenables_everything() -> None:
    """authoritative=True with an empty list still emits a note (unlike additive
    mode) that disregards the static fallback — this is what re-enables a model in
    prod once the availability service reports it restored."""
    system, _ = build_prompt(
        "pick a model",
        user_context_text=_UCTX,
        unavailable_models=[],
        availability_authoritative=True,
    )
    assert "AUTHORITATIVE" in system
    assert "NO models currently unavailable" in system


def test_strip_ide_framing_is_targeted_and_idempotent() -> None:
    # No-op on text without the framing tags.
    plain = "<model-selector>\n  <objective>x</objective>\n</model-selector>"
    assert _strip_ide_framing(plain) == plain
    # Removes both tags (and only those) when present.
    withframing = "<model-selector>\n  <instruction>do it</instruction>\n  <usage>u</usage>\n  <objective>keep</objective>\n</model-selector>"
    stripped = _strip_ide_framing(withframing)
    assert "<instruction>" not in stripped
    assert "<usage>" not in stripped
    assert "<objective>keep</objective>" in stripped
    assert "<model-selector>" in stripped
