"""Tests for parse_response's handling of the optional BACKUP row — the
fallback model (Step 7 of the selection algorithm) added to the bundled
selector's <output-format>.

BACKUP sits between MODEL and PLATFORM and, like ORCHESTRATION, is OPTIONAL:
a provider that omits it (or emits the literal "None") must still parse with
no error and no ``backup`` key, so the field can never reintroduce the
parser-500s drift class (2026-05-31). When present and meaningful it is
surfaced in the returned dict.
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

_WITH_BACKUP = """\
MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
MAX MODE: Off
THINKING: XHigh
CONVERSATION: New
RATIONALE: Opus 4.8 leads planning; GPT-5.5 is the cross-provider backup.
"""

_NO_BACKUP = """\
MODEL: Opus 4.8
PLATFORM: Claude Code
MAX MODE: Off
THINKING: High
CONVERSATION: New
RATIONALE: No BACKUP line at all — must still parse cleanly.
"""

_BACKUP_NONE = """\
MODEL: Opus 4.8
BACKUP: None
PLATFORM: Claude Code
MAX MODE: Off
THINKING: High
CONVERSATION: New
RATIONALE: BACKUP is None when no distinct alternative qualifies.
"""

_BACKUP_WITH_ORCHESTRATION = """\
MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
MAX MODE: On
THINKING: XHigh
ORCHESTRATION: Ultracode
CONVERSATION: New
RATIONALE: Full schema — BACKUP and ORCHESTRATION both present.
"""

# Output contract v2: the setting fields are platform-conditional, so this
# Claude Code block carries EFFORT + THINKING and NO MAX MODE line. BACKUP's
# position (between MODEL and PLATFORM) and its optionality are unchanged.
_V2_WITH_BACKUP = """\
MODEL: Opus 4.8
BACKUP: GPT-5.5
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: v2 block — BACKUP survives the platform-conditional setting fields.
"""

_V2_BACKUP_NONE_NO_DIALS = """\
MODEL: Composer 2.5
BACKUP: None
PLATFORM: Cursor
MAX MODE: Off
CONVERSATION: New
RATIONALE: v2 Cursor block — no EFFORT/THINKING lines, and BACKUP is None.
"""


def test_backup_row_is_surfaced() -> None:
    """A present, meaningful BACKUP is captured and returned."""
    result = parse_response(_WITH_BACKUP)
    assert result["model"] == "Opus 4.8"
    assert result["platform"] == "Claude Code"
    assert result["backup"] == "GPT-5.5"
    assert result["thinking"] == "XHigh"


def test_missing_backup_parses_without_key() -> None:
    """The drift-safety guarantee: an omitted BACKUP never errors and never
    leaves a stray key, so prod can't 500 on a provider that skips it."""
    result = parse_response(_NO_BACKUP)
    assert result["model"] == "Opus 4.8"
    assert result["conversation"] == "New"
    assert "backup" not in result


def test_backup_none_is_treated_as_absent() -> None:
    """A literal ``BACKUP: None`` means "no distinct alternative" — it must not
    surface the string "None" as a model."""
    result = parse_response(_BACKUP_NONE)
    assert result["model"] == "Opus 4.8"
    assert "backup" not in result


def test_backup_coexists_with_orchestration() -> None:
    """BACKUP (between MODEL and PLATFORM) and ORCHESTRATION (between THINKING
    and CONVERSATION) are both optional and must parse together."""
    result = parse_response(_BACKUP_WITH_ORCHESTRATION)
    assert result["backup"] == "GPT-5.5"
    assert result["max_mode"] == "On"
    assert result["conversation"] == "New"
    # Both optional fields are now surfaced (0.2.15): BACKUP and a meaningful
    # ORCHESTRATION value (Ultracode) both appear in the returned dict.
    assert result["orchestration"] == "Ultracode"


def test_backup_survives_a_v2_block_with_no_max_mode_line() -> None:
    """BACKUP is orthogonal to the v2 platform-conditional setting fields: a
    Claude Code block that omits MAX MODE entirely must still surface it."""
    result = parse_response(_V2_WITH_BACKUP)
    assert result["backup"] == "GPT-5.5"
    assert result["effort"] == "Max"
    assert result["thinking"] == "On"
    assert "max_mode" not in result
    # ORCHESTRATION: None keeps meaning "no orchestration", not the string "None".
    assert "orchestration" not in result


def test_backup_none_still_absent_on_a_dial_less_v2_block() -> None:
    """The sentinel rule is scoped to BACKUP/ORCHESTRATION, not to the dials: a
    v2 Cursor block (no EFFORT/THINKING at all) still drops "BACKUP: None" while
    keeping its real MAX MODE value."""
    result = parse_response(_V2_BACKUP_NONE_NO_DIALS)
    assert "backup" not in result
    assert result["max_mode"] == "Off"
    assert "effort" not in result
    assert "thinking" not in result


def test_required_fields_still_enforced_with_backup_present() -> None:
    """A block missing required fields must still raise even when BACKUP is
    present — BACKUP is additive, never a substitute for a required field."""
    with pytest.raises(MalformedResponseError):
        parse_response("MODEL: Opus 4.8\nBACKUP: GPT-5.5\nRATIONALE: incomplete\n")
