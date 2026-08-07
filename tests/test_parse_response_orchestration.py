"""Tests for parse_response's handling of the optional SETTING rows —
MAX MODE, EFFORT, THINKING and ORCHESTRATION — across both output contract
versions.

Regression coverage for the 2026-05-31 production incident in which the
parser rejected every Gemini and Anthropic Haiku response because the
new selector schema emits ORCHESTRATION between THINKING and CONVERSATION
and the regex was never updated to match.

Contract v2 generalised that lesson: EVERY setting line is now optional, because
each is emitted only on a platform that exposes that dial. The v1 blocks below
are kept deliberately — cached engine responses, older roadmodel releases in
prod, and previously-exported offline planning kits still emit them.
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
from roadmodel.recommend import _structured_settings, parse_response  # noqa: E402

# --- v2 blocks: every setting field is platform-conditional -------------------

_V2_CLAUDE_CODE = """\
MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: PerPrompt
CONVERSATION: New
RATIONALE: Claude Code has no Max Mode, so the block emits no MAX MODE line.
"""

_V2_CLAUDE_CODE_ULTRACODE = """\
MODEL: Opus 4.8
PLATFORM: Claude Code
EFFORT: Ultracode
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: Ultracode is the TOP value of EFFORT, above Max.
"""

_V2_CURSOR = """\
MODEL: Composer 2.5
BACKUP: GPT-5.5
PLATFORM: Cursor
MAX MODE: On
CONVERSATION: New
RATIONALE: Cursor exposes Max Mode and no reasoning dial, so no EFFORT/THINKING.
"""

_V2_ANTHROPIC_API = """\
MODEL: Opus 4.8
PLATFORM: Anthropic API
EFFORT: Max
THINKING: On
CONVERSATION: New
RATIONALE: The Anthropic API has no Max Mode, so the line is omitted entirely.
"""

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


def test_v2_claude_code_block_without_max_mode_parses() -> None:
    """THE v2 regression: Claude Code has no Max Mode, so its block omits the
    line. Under v1 MAX MODE was mandatory in the regex and this block would have
    raised MalformedResponseError on every Claude Code pick."""
    result = parse_response(_V2_CLAUDE_CODE)
    assert result["model"] == "Opus 4.8"
    assert result["platform"] == "Claude Code"
    assert result["effort"] == "XHigh"
    assert result["thinking"] == "On"
    assert result["orchestration"] == "PerPrompt"
    assert result["conversation"] == "New"
    # An omitted line means "this surface has no such dial" — never a stray key.
    assert "max_mode" not in result


def test_v2_claude_code_emits_no_max_mode_setting() -> None:
    """...and the display layer must agree: no MAX MODE line in, no max_mode
    key out. The D1 rule end-to-end."""
    settings = _structured_settings(parse_response(_V2_CLAUDE_CODE))
    assert settings == {"effort": "XHigh", "thinking": "On"}
    assert "max_mode" not in settings


def test_v2_thinking_is_never_an_effort_word_on_claude_code() -> None:
    """D2: the reasoning LEVEL lands in effort and THINKING stays a two-position
    toggle. "THINKING: Max" — the v1 bug — can no longer reach the display."""
    settings = _structured_settings(parse_response(_V2_CLAUDE_CODE))
    assert settings["thinking"] in {"On", "Off"}
    assert settings["effort"] == "XHigh"


def test_v2_effort_ultracode_round_trips() -> None:
    """D3: Ultracode is the TOP value of EFFORT (above Max), not an
    ORCHESTRATION value — it must survive parse -> display verbatim."""
    parsed = parse_response(_V2_CLAUDE_CODE_ULTRACODE)
    assert parsed["effort"] == "Ultracode"
    # ORCHESTRATION: None still means "no orchestration" -> dropped as absent.
    assert "orchestration" not in parsed
    settings = _structured_settings(parsed)
    assert settings == {"effort": "Ultracode", "thinking": "On"}


def test_v2_cursor_block_without_effort_or_thinking_parses() -> None:
    """Cursor exposes Max Mode and NO reasoning dial, so a v2 Cursor block emits
    neither EFFORT nor THINKING. It must parse, and must not grow an empty
    effort key at the display layer."""
    parsed = parse_response(_V2_CURSOR)
    assert parsed["model"] == "Composer 2.5"
    assert parsed["max_mode"] == "On"
    assert "effort" not in parsed
    assert "thinking" not in parsed
    settings = _structured_settings(parsed)
    assert settings == {"max_mode": "ON", "thinking": "On"}


def test_v2_non_cursor_surface_without_max_mode_line() -> None:
    """A non-Cursor, non-Claude-Code surface: the catch-all display branch must
    also honour the absent MAX MODE line instead of inventing "OFF"."""
    parsed = parse_response(_V2_ANTHROPIC_API)
    assert "max_mode" not in parsed
    settings = _structured_settings(parsed)
    assert settings == {"effort": "Max", "thinking": "On"}


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


def test_v1_orchestration_ultracode_still_folds_into_effort() -> None:
    """LEGACY ACCEPTANCE: a v1 block has no EFFORT line, so ORCHESTRATION:
    Ultracode must still fold into the effort VALUE (Claude Code's top rung) and
    THINKING must still display as the On/Off toggle."""
    settings = _structured_settings(parse_response(_ORCHESTRATION_BLOCK))
    assert settings == {"effort": "Ultracode", "thinking": "On"}
    assert "orchestration" not in settings
    assert "max_mode" not in settings  # Claude Code never shows a Max Mode row


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
        parse_response("just some prose, not the block format at all")


def test_the_four_always_on_fields_are_still_mandatory() -> None:
    """Relaxing the SETTING fields to optional must not relax MODEL / PLATFORM /
    CONVERSATION / RATIONALE. Here every dial is present but CONVERSATION is
    missing — that is still a malformed block, not a dial-less platform."""
    with pytest.raises(MalformedResponseError):
        parse_response(
            "MODEL: Opus 4.8\n"
            "PLATFORM: Claude Code\n"
            "EFFORT: Max\n"
            "THINKING: On\n"
            "RATIONALE: No CONVERSATION line.\n"
        )
