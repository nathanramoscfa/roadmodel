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


def test_required_fields_still_enforced_with_backup_present() -> None:
    """A block missing required fields must still raise even when BACKUP is
    present — BACKUP is additive, never a substitute for a required field."""
    with pytest.raises(MalformedResponseError):
        parse_response("MODEL: Opus 4.8\nBACKUP: GPT-5.5\nRATIONALE: incomplete\n")
