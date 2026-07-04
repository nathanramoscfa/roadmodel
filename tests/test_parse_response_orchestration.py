"""Tests for parse_response's handling of the optional ORCHESTRATION row
introduced by the Ultracode dimension in the bundled model-selector.txt.

Regression coverage for the 2026-05-31 production incident in which the
parser rejected every Gemini and Anthropic Haiku response because the
new selector schema emits ORCHESTRATION between THINKING and CONVERSATION
and the regex was never updated to match.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel.errors import MalformedResponseError  # noqa: E402
from roadmodel.recommend import parse_response  # noqa: E402

_LEGACY_BLOCK = """\
MODEL: Opus 4.7
PLATFORM: Claude Code
MAX MODE: Off
THINKING: High
CONVERSATION: New
RATIONALE: Some legacy six-field response with no ORCHESTRATION line.
"""

_ORCHESTRATION_BLOCK = """\
MODEL: Opus 4.8
PLATFORM: Claude Code
MAX MODE: Off
THINKING: XHigh
ORCHESTRATION: Ultracode
CONVERSATION: New
RATIONALE: The primary task is planning a SQL agent, which demands an S-tier model. Opus 4.8 is selected for its S-tier rating in planning.
"""

_ORCHESTRATION_NA = """\
MODEL: GPT-5.5
PLATFORM: Codex
MAX MODE: Off
THINKING: XHigh
ORCHESTRATION: N/A
CONVERSATION: New
RATIONALE: GPT-5.5 on Codex; ORCHESTRATION is N/A for non-Claude-Code platforms.
"""


def test_legacy_block_still_parses() -> None:
    """Pre-Ultracode responses (no ORCHESTRATION row) must continue to parse."""
    result = parse_response(_LEGACY_BLOCK)
    assert result["model"] == "Opus 4.7"
    assert result["platform"] == "Claude Code"
    assert result["max_mode"] == "Off"
    assert result["thinking"] == "High"
    assert result["conversation"] == "New"
    assert "RATIONALE" not in result["rationale"]  # field stripped
    assert "no ORCHESTRATION line" in result["rationale"]
    # ORCHESTRATION must NOT appear in the returned dict when absent — the
    # downstream contract for legacy callers stays exactly six keys.
    assert "orchestration" not in result


def test_orchestration_row_does_not_break_parsing() -> None:
    """Regression: PR #122 added ORCHESTRATION to the selector but didn't
    update parse_response's regex. Production was 500'ing on every call
    because Gemini correctly followed the new schema. This test pins the
    fix so the same regression can't recur silently."""
    result = parse_response(_ORCHESTRATION_BLOCK)
    assert result["model"] == "Opus 4.8"
    assert result["platform"] == "Claude Code"
    assert result["max_mode"] == "Off"
    assert result["thinking"] == "XHigh"
    assert result["conversation"] == "New"
    assert "Opus 4.8 is selected" in result["rationale"]
    # ORCHESTRATION is now surfaced as an optional key (0.2.15) so the
    # comparison matrix can render an Orchestration row; a meaningful value
    # (Ultracode / PerPrompt) is carried through.
    assert result["orchestration"] == "Ultracode"


def test_orchestration_na_also_parses() -> None:
    """ORCHESTRATION: N/A (the value emitted for non-Claude-Code surfaces) is
    treated as absent — _attach_optional drops "None"/"N/A", so the key stays
    out of the returned dict on those surfaces (only meaningful values surface)."""
    result = parse_response(_ORCHESTRATION_NA)
    assert result["model"] == "GPT-5.5"
    assert result["platform"] == "Codex"
    assert result["thinking"] == "XHigh"
    assert "orchestration" not in result


def test_truly_malformed_still_raises() -> None:
    """Negative test: a response missing required fields must still raise."""
    with pytest.raises(MalformedResponseError):
        parse_response("just some prose, not the six-field format at all")
