"""Tests for the single-call Cost/Balanced/Quality ladder (tasks #1/#3).

The recommender emits the whole ladder in ONE response — Quality anchored first,
then Balanced and Cost as strictly-lower rungs — instead of three independent
calls that can collapse onto the same model. These tests cover the parser
(``parse_ladder_response``), the deterministic tier-distinctness guard
(``_ladder_tier_guard``), and the structured wiring
(``recommend_structured_ladder``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel import recommend as recommend_module  # noqa: E402
from roadmodel.config import Config  # noqa: E402
from roadmodel.errors import MalformedResponseError  # noqa: E402
from roadmodel.recommend import (  # noqa: E402
    _ladder_tier_guard,
    parse_ladder_response,
    recommend_structured_ladder,
)

# --- parse_ladder_response ---------------------------------------------------

_GOOD_LADDER = """\
TIER: QUALITY
MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
MAX MODE: Off
THINKING: Max
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: Opus 4.8 is S-tier. RUN: Claude Code, Max effort.

TIER: BALANCED
MODEL: Sonnet 4.6
BACKUP: GPT-5.5
PLATFORM: Claude Code
MAX MODE: Off
THINKING: High
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: Sonnet 4.6 is A-tier. RUN: Claude Code, High effort.

TIER: COST
MODEL: Composer 2.5
BACKUP: GPT-5.4-mini
PLATFORM: Cursor
MAX MODE: Off
THINKING: N/A
CONVERSATION: New
RATIONALE: TASK: Coding. PICK: Composer 2.5 is A-tier at low cost. RUN: Cursor pool.
"""


def test_parse_ladder_splits_three_blocks() -> None:
    ladder = parse_ladder_response(_GOOD_LADDER)
    assert set(ladder) == {"quality", "balanced", "cost"}
    assert ladder["quality"]["model"] == "Opus 4.8"
    assert ladder["balanced"]["model"] == "Sonnet 4.6"
    assert ladder["cost"]["model"] == "Composer 2.5"
    # Each block parses like a single-prompt block, so optional BACKUP surfaces.
    assert ladder["quality"]["backup"] == "GPT-5.5"
    assert ladder["cost"]["platform"] == "Cursor"


def test_parse_ladder_is_case_insensitive_on_labels() -> None:
    ladder = parse_ladder_response(_GOOD_LADDER.replace("TIER:", "tier:"))
    assert set(ladder) == {"quality", "balanced", "cost"}


def test_parse_ladder_missing_tier_raises() -> None:
    # Drop the COST block entirely -> all-or-nothing: must raise so the edge
    # falls back to the per-priority fan-out.
    only_two = _GOOD_LADDER.split("TIER: COST")[0]
    with pytest.raises(MalformedResponseError):
        parse_ladder_response(only_two)


def test_parse_ladder_no_tier_labels_raises() -> None:
    with pytest.raises(MalformedResponseError):
        parse_ladder_response("MODEL: Opus 4.8\nPLATFORM: Claude Code\n")


def test_parse_ladder_malformed_block_raises() -> None:
    # QUALITY block missing required fields -> parse_response raises for it.
    broken = _GOOD_LADDER.replace(
        "MODEL: Opus 4.8\nBACKUP: GPT-5.5\nPLATFORM: Claude Code",
        "MODEL: Opus 4.8",
    )
    with pytest.raises(MalformedResponseError):
        parse_ladder_response(broken)


# --- _ladder_tier_guard ------------------------------------------------------


def _picks(quality: str, balanced: str, cost: str) -> dict[str, dict[str, object]]:
    return {
        "quality": {"model": quality},
        "balanced": {"model": balanced},
        "cost": {"model": cost},
    }


def test_guard_healthy_when_three_distinct_decreasing_tiers() -> None:
    guard = _ladder_tier_guard(_picks("Opus 4.8", "Sonnet 4.6", "Composer 2.5"))
    assert guard["tiers"] == {
        "quality": "very-high",
        "balanced": "high",
        "cost": "low",
    }
    assert guard["distinct_tiers"] is True
    assert guard["duplicate_models"] is False
    assert guard["misordered"] is False
    assert guard["healthy"] is True


def test_guard_flags_duplicate_models() -> None:
    # Balanced collapsed onto Quality (the exact bug this whole task targets).
    guard = _ladder_tier_guard(_picks("Opus 4.8", "Opus 4.8", "Composer 2.5"))
    assert guard["duplicate_models"] is True
    assert guard["healthy"] is False


def test_guard_flags_rank_inversion() -> None:
    # Cost pricier (very-high) than Balanced (high) -> a misorder.
    guard = _ladder_tier_guard(_picks("Opus 4.8", "Sonnet 4.6", "Fable 5"))
    assert guard["misordered"] is True
    assert guard["healthy"] is False


def test_guard_same_tier_tie_is_allowed_when_models_differ() -> None:
    # Two Very-High models (Opus 4.8 + Fable 5) at Quality/Balanced: a permitted
    # catalog-limited tie — distinct models, non-increasing ranks -> still healthy
    # even though the tiers aren't all distinct.
    guard = _ladder_tier_guard(_picks("Opus 4.8", "Fable 5", "Composer 2.5"))
    assert guard["distinct_tiers"] is False
    assert guard["duplicate_models"] is False
    assert guard["misordered"] is False
    assert guard["healthy"] is True


# --- recommend_structured_ladder wiring --------------------------------------


def _config(tmp_path: Path) -> Config:
    ctx = tmp_path / "user-context.md"
    ctx.write_text("# ctx\n", encoding="utf-8")
    return Config(provider="anthropic", model=None, api_key="test-key", user_context_path=ctx)


def _fake_ladder(*_args: object, **_kwargs: object) -> dict[str, dict[str, str]]:
    def block(model: str, platform: str, thinking: str, max_mode: str = "Off") -> dict[str, str]:
        return {
            "model": model,
            "platform": platform,
            "max_mode": max_mode,
            "thinking": thinking,
            "conversation": "New",
            "rationale": f"TASK: Coding. PICK: {model} fits. RUN: {platform}.",
        }

    return {
        "quality": block("opus-4.8", "Claude Code", "Max"),
        "balanced": block("sonnet-4.6", "Claude Code", "High"),
        "cost": block("composer-2.5", "Cursor", "N/A"),
    }


def test_recommend_structured_ladder_shapes_three_picks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recommend_module, "recommend_ladder", _fake_ladder)
    result = recommend_structured_ladder("build a SQL agent", _config(tmp_path))

    assert set(result["picks"]) == {"quality", "balanced", "cost"}
    # Models are canonicalized to catalog display names, and each pick is shaped
    # like a single recommend_structured payload (settings, no cost fields yet).
    assert result["picks"]["quality"]["model"] == "Opus 4.8"
    assert result["picks"]["cost"]["model"] == "Composer 2.5"
    assert result["picks"]["quality"]["settings"]["effort"] == "Max"
    # Cursor cost pick uses the display reframe from task #2.
    assert result["picks"]["cost"]["settings"]["thinking"] == "On"
    assert result["picks"]["quality"]["session_cost_estimate"] is None

    # The deterministic guard confirms a healthy, distinct-tier ladder.
    assert result["guard"]["healthy"] is True
    assert result["guard"]["distinct_tiers"] is True
