"""update/selector_re.repair_attribute_quotes: a raw quote an LLM wrote inside
an attribute value is escaped before the selector is saved, so a tracker PR
no longer opens with a truncated value (#663, #692) — and nothing else in the
file changes."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "update"))

from selector_re import ATTR_RE, repair_attribute_quotes  # noqa: E402

SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"


def test_the_phrases_the_trackers_keep_unescaping_are_repaired() -> None:
    for value in (
        'configurable under "Project instructions" in `/config`',
        'via `/effort ultracode` or `"ultracode": true`',
        'a `/config` "Dynamic workflow size" advisory guideline',
    ):
        broken = f'             best-for="prefix {value} suffix" />'
        fixed, notes = repair_attribute_quotes(broken)
        pairs = ATTR_RE.findall(fixed)
        assert len(pairs) == 1 and pairs[0][0] == "best-for"
        assert pairs[0][1].endswith(" suffix"), "the value must now parse whole"
        assert pairs[0][1].replace('\\"', '"') == f"prefix {value} suffix"
        assert notes == ["escaped a raw quote in `best-for` on line 1"]


def test_well_formed_lines_are_never_touched() -> None:
    text = (
        '      <model id="claude-opus-5-5" name="Opus 5.5"\n'
        '             best-for="already \\"escaped\\" prose" />\n'
        '  prose with a "quote" outside any element\n'
    )
    assert repair_attribute_quotes(text) == (text, [])


def test_a_line_holding_several_attributes_is_left_for_the_guard() -> None:
    """Which quote ends which value is ambiguous there, so no guess is made."""
    text = '      <model id="x" name="The "Big" One" />'
    assert repair_attribute_quotes(text) == (text, [])


def test_the_committed_selector_is_a_fixed_point() -> None:
    text = SELECTOR.read_text(encoding="utf-8")
    assert repair_attribute_quotes(text) == (text, [])
