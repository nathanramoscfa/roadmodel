"""Structural guard on attribute quoting in docs/model-selector.txt.

A raw `"` inside an attribute value ENDS that attribute. The parser in
``update/build_catalog.py`` then reads a value silently truncated at the stray
quote and ships it — the catalog gets a `best_for` cut off mid-sentence, a
`supports-models` missing its tail, an anchor that no longer matches. Nothing
raises; the doc just quietly says less than it reads.

The daily crons rewrite these attributes with an LLM, and prose about a UI
naturally wants quotes around a control name (`"Project instructions"`,
`"Dynamic workflow size"`, `\\"ultracode\\": true`). One refresh dropped the
backslashes on all three and truncated the claude-code method's `best_for` to
a third of its length.

`test_claude_code_best_for_is_not_truncated` catches that ONE field by looking
for a word it should contain. This test is the general form, and needs no
knowledge of what any attribute is supposed to say: after every well-formed
`name="value"` is removed from an element's attribute blob, what is left must
be nothing. Residue means a quote closed an attribute early, and the residue
itself points at where.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"

# Mirrors update/build_catalog.py's _ATTR_RE: a value may embed \" and \\.
_ATTR_RE = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"', re.DOTALL)
# An element open-tag, allowing quoted values to contain anything but an
# unescaped quote. A tag whose blob holds NO attribute at all is prose in
# angle brackets (the output-format section writes `<the prompt's ...>`), not
# an element, so it is skipped rather than reported.
_ELEM_RE = re.compile(r'<([\w-]+)((?:[^<>"]|"(?:[^"\\]|\\.)*")*)/?>', re.DOTALL)


def _malformed(text: str) -> list[str]:
    out: list[str] = []
    for match in _ELEM_RE.finditer(text):
        blob = match.group(2)
        if not _ATTR_RE.search(blob):
            continue
        residue = _ATTR_RE.sub(" ", blob).replace("/", " ").strip()
        if residue:
            line = text[: match.start()].count("\n") + 1
            out.append(f"line {line}: <{match.group(1)}> leftover -> {residue[:120]!r}")
    return out


def test_every_attribute_value_is_closed_by_its_own_quote() -> None:
    offenders = _malformed(SELECTOR.read_text(encoding="utf-8"))
    assert not offenders, (
        'An attribute in docs/model-selector.txt is ended early by a raw `"` in '
        "its value, so build_catalog.py ships that value truncated. Escape the "
        "inner quotes as \\\" (the doc's existing convention):\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "value",
    [
        'configurable under "Project instructions" in `/config`',
        'via `/effort ultracode` or `"ultracode": true`',
        'a `/config` "Dynamic workflow size" advisory guideline',
    ],
)
def test_the_guard_fires_on_the_quotes_a_refresh_actually_dropped(value: str) -> None:
    """The three sites one refresh un-escaped. Escaped, each parses whole;
    raw, each ends the attribute early and leaves residue behind."""
    raw = f'<method id="m" best-for="prefix {value} suffix" />'
    assert _malformed(raw), f"guard missed a raw quote in: {value}"

    escaped = raw.replace(f"{value}", value.replace('"', '\\"'))
    assert not _malformed(escaped)
    parsed = dict(_ATTR_RE.findall(escaped))
    assert parsed["best-for"].endswith(" suffix"), "escaped value must parse whole"
