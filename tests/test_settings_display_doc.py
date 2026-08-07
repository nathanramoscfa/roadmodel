"""docs/settings-display.md is the OFFLINE contract for turning a selector block
into a surface's real controls.

It exists because those rules live in Python (`_structured_settings`) and
deliberately NOT in the selector — the daily effort/thinking conformance tracker
pins the selector's vocabulary and would revert them. So `read_catalog` / the
planning kit had no way to know that Claude Code's THINKING is a TOGGLE (with the
reasoning level in EFFORT, Ultracode topmost), and emitted raw selector
vocabulary ("Effort: Extra High / Thinking: XHigh") instead.

Since output contract v2 the division of labour is sharper: the SELECTOR owns the
EMISSION rule (which dials a platform exposes at all — a dial it lacks is an
ABSENT line, never "Off"/"N/A"), and this doc owns the DISPLAY rule (what to call
them per surface). Both shapes reach the parser — cached responses, older
releases and exported planning kits still emit v1 — so the table covers BOTH.

A hand-written doc rots. These pin every row of its conformance table to the real
`_structured_settings`, so the doc and the code cannot disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from roadmodel.recommend import _structured_settings

DOC = Path(__file__).resolve().parent.parent / "docs" / "settings-display.md"

_TABLE_RE = re.compile(
    r"<!-- conformance-table:start -->(?P<body>.*?)<!-- conformance-table:end -->",
    re.DOTALL,
)

# The table's marker for "the block carried NO such line" — the v2 signal that
# the platform has no such dial. Distinct from an explicit "Off"/"N/A" value,
# which means the dial exists and reads that way.
_ABSENT = "—"

# Input columns, in table order, mapped to the parsed-block keys they drive.
_INPUT_COLUMNS = ("max_mode", "effort", "thinking", "orchestration")

Row = tuple[str, dict[str, str], dict[str, str]]


def _rows() -> list[Row]:
    """Parse the table into ``(platform, block_fields, expected_settings)``.

    ``block_fields`` holds ONLY the fields the row says the block carried, so an
    ``—`` cell produces a MISSING key rather than an empty string — exactly how
    `parse_response` represents an omitted line.
    """
    body = _TABLE_RE.search(DOC.read_text()).group("body")  # type: ignore[union-attr]
    rows: list[Row] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 6 or cells[0] == "PLATFORM":
            continue
        platform, *inputs, expected_raw = cells
        block = {
            key: value
            for key, value in zip(_INPUT_COLUMNS, inputs, strict=True)
            if value != _ABSENT
        }
        expected = {}
        for pair in expected_raw.split(";"):
            key, _, value = pair.partition("=")
            expected[key.strip()] = value.strip()
        rows.append((platform, block, expected))
    return rows


def _row_id(row: Row) -> str:
    platform, block, _ = row
    dials = ",".join(f"{k}={v}" for k, v in block.items()) or "no-dials"
    return f"{platform}-{dials}"


def test_the_doc_actually_has_a_conformance_table() -> None:
    assert len(_rows()) >= 20, "conformance table missing or truncated"


def test_the_table_covers_both_contract_versions() -> None:
    """The table must exercise v2 (an explicit EFFORT line) AND v1 (no EFFORT,
    with the level hiding in THINKING) — a table that drifted to one shape would
    stop guarding the other, and both still arrive in production."""
    rows = _rows()
    assert any("effort" in block for _, block, _ in rows), "no v2 (explicit EFFORT) rows"
    assert any("effort" not in block and "thinking" in block for _, block, _ in rows), (
        "no v1 legacy rows (THINKING carrying the effort level)"
    )
    assert any("max_mode" not in block for _, block, _ in rows), (
        "no rows with an ABSENT MAX MODE line — the v2 D1 case is unguarded"
    )


@pytest.mark.parametrize("row", _rows(), ids=_row_id)
def test_documented_mapping_matches_structured_settings(row: Row) -> None:
    platform, block, expected = row
    got = _structured_settings({"platform": platform, **block})
    assert got == expected, (
        f"docs/settings-display.md says {platform} / {block} -> {expected}, "
        f"but _structured_settings returned {got}"
    )


def test_claude_code_never_surfaces_a_max_mode_or_orchestration_row() -> None:
    """The two failure modes the doc exists to prevent (v1 legacy input)."""
    got = _structured_settings(
        {
            "platform": "Claude Code",
            "max_mode": "On",
            "thinking": "XHigh",
            "orchestration": "Ultracode",
        }
    )
    assert set(got) == {"effort", "thinking"}
    assert got["effort"] == "Ultracode"  # folded, not a separate row
    assert got["thinking"] == "On"  # a toggle — never "XHigh"


def test_claude_code_v2_block_has_no_max_mode_key() -> None:
    """D1 at the display layer: a v2 Claude Code block carries no MAX MODE line
    (Claude Code has no such control), so no max_mode key may appear."""
    got = _structured_settings(
        {"platform": "Claude Code", "effort": "Max", "thinking": "On", "orchestration": "None"}
    )
    assert got == {"effort": "Max", "thinking": "On"}
    assert "max_mode" not in got


def test_non_cursor_surface_without_a_max_mode_line_shows_no_max_mode() -> None:
    """The catch-all branch's D1 fix: v1 pinned MAX MODE to "Off" everywhere, so
    an Anthropic-API pick displayed a Max Mode row for a dial that surface does
    not have. With the line absent, the row must be absent too."""
    got = _structured_settings({"platform": "Anthropic API", "effort": "Max", "thinking": "On"})
    assert got == {"effort": "Max", "thinking": "On"}
    assert "max_mode" not in got


def test_openai_api_surfaces_intelligence_not_max_mode() -> None:
    """The dogfood display bug: a GPT pick on the direct OpenAI API showed a
    spurious "Max Mode: On" and hid its reasoning effort. OpenAI's reasoning
    surface must render as Intelligence (like Codex), with NO max_mode key —
    even if the selector erroneously emitted MAX MODE On."""
    got = _structured_settings(
        {"platform": "OpenAI API", "max_mode": "On", "thinking": "High", "orchestration": "None"}
    )
    assert got == {"intelligence": "High"}
    assert "max_mode" not in got
