"""docs/settings-display.md is the OFFLINE contract for turning the selector's
platform-neutral axes (MAX MODE / THINKING / ORCHESTRATION) into a surface's real
controls.

It exists because those rules live in Python (`_structured_settings`) and
deliberately NOT in the selector — the daily effort/thinking conformance tracker
pins the selector's vocabulary and would revert them. So `read_catalog` / the
planning kit had no way to know that Claude Code folds ORCHESTRATION:Ultracode
into Effort and has a Thinking TOGGLE, and emitted raw selector vocabulary
("Effort: Extra High / Thinking: XHigh") instead.

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


def _rows() -> list[tuple[str, str, str, str, dict[str, str]]]:
    body = _TABLE_RE.search(DOC.read_text()).group("body")  # type: ignore[union-attr]
    rows: list[tuple[str, str, str, str, dict[str, str]]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5 or cells[0] == "PLATFORM":
            continue
        platform, max_mode, thinking, orch, expected_raw = cells
        expected = {}
        for pair in expected_raw.split(";"):
            key, _, value = pair.partition("=")
            expected[key.strip()] = value.strip()
        rows.append((platform, max_mode, thinking, orch, expected))
    return rows


def test_the_doc_actually_has_a_conformance_table() -> None:
    assert len(_rows()) >= 10, "conformance table missing or truncated"


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r[0]}-{r[2]}-{r[3]}")
def test_documented_mapping_matches_structured_settings(
    row: tuple[str, str, str, str, dict[str, str]],
) -> None:
    platform, max_mode, thinking, orch, expected = row
    got = _structured_settings(
        {
            "platform": platform,
            "max_mode": max_mode,
            "thinking": thinking,
            "orchestration": orch,
        }
    )
    assert got == expected, (
        f"docs/settings-display.md says {platform} / MAX MODE={max_mode} / "
        f"THINKING={thinking} / ORCHESTRATION={orch} -> {expected}, "
        f"but _structured_settings returned {got}"
    )


def test_claude_code_never_surfaces_a_max_mode_or_orchestration_row() -> None:
    """The two failure modes the doc exists to prevent."""
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
