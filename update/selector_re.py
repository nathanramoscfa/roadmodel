# update/selector_re.py
"""One definition of "how to match an element in model-selector.txt".

The selector is pseudo-XML whose attribute values are PROSE copied from
provider pages, so they contain whatever those pages say — including angle
brackets. Five modules had each written their own
``<model\\s+([^>]+?)\\s*/>``, and `merge_catalog._element_re` even documented
the assumption out loud: "A model element contains no `>` until its closing
`/>`".

That assumption died on 2026-09-04, when Cursor's page described GPT-5.6's
"Fast mode ... for long context (>272k)". One `>` in one pricing note, and:

- ``build_catalog`` dropped gpt-5.6-sol / -terra / -luna from docs/catalog.json
  (the website's table and the wheel's bundled catalog);
- ``render_md`` dropped them from the rendered model-selector.md;
- ``sync_static_availability`` stopped seeing them;
- ``merge_catalog`` could not locate their elements, so the federation overlay
  silently stopped forcing provider-direct prices onto them — a price-integrity
  hole, not just a display bug;
- the doc-schema test's own copy lost them too, and reported the *supports-models*
  lists as referencing "unknown" models.

None of that raised. Match quote-aware instead: consume either a non-quote
character or a complete quoted string (escapes included), so `>` and `/>`
inside a value are data rather than a terminator. Then use
``assert_no_element_lost`` so a future prose surprise fails loudly instead of
quietly shipping a shorter catalog.
"""

from __future__ import annotations

import re

# Either a character that cannot start a quoted value, or a whole quoted value
# (with backslash escapes, matching _ATTR_RE in build_catalog).
ELEMENT_BODY = r'(?:[^"]|"(?:[^"\\]|\\.)*")*?'

MODEL_RE = re.compile(rf"<model\s+({ELEMENT_BODY})\s*/>", re.DOTALL)
METHOD_RE = re.compile(rf"<method\s+({ELEMENT_BODY})\s*/>", re.DOTALL)

# Openers, for counting what the document DECLARES versus what a parse matched.
MODEL_OPEN_RE = re.compile(r"<model\s")
METHOD_OPEN_RE = re.compile(r"<method\s")


# Same idea as ELEMENT_BODY, but it may not cross an element terminator that
# sits OUTSIDE quotes. ELEMENT_BODY alone is fine when the pattern's own `/>`
# is the next thing to match (it is non-greedy, so it stops at the first one);
# it is NOT fine when an anchor follows the body — `id="…"` appears after it in
# model_element_re, so an unconstrained body happily runs through a preceding
# element's `/>` and returns two elements glued together.
_ELEMENT_BODY_INNER = r'(?:[^"/]|/(?!>)|"(?:[^"\\]|\\.)*")*?'


def model_element_re(model_id: str) -> re.Pattern[str]:
    """Match one full, indented ``<model ... id="model_id" ... />`` element."""
    return re.compile(
        rf'^[ \t]*<model\s+{_ELEMENT_BODY_INNER}\bid="{re.escape(model_id)}"'
        rf"{_ELEMENT_BODY_INNER}/>[ \t]*$",
        re.MULTILINE | re.DOTALL,
    )


def assert_no_element_lost(block: str, matched: int, opener: re.Pattern[str], what: str) -> None:
    """Fail if an element regex matched fewer elements than the doc declares.

    A regex that stops matching mid-document does not error — it just returns
    less, and every consumer downstream inherits the omission as fact.
    """
    declared = len(opener.findall(block))
    if matched != declared:
        raise ValueError(
            f"{what}: parsed {matched} element(s) but the selector declares "
            f"{declared}. An attribute value probably contains something the "
            f"element regex cannot span — do NOT ship a catalog missing an entry."
        )


# ---------------------------------------------------------------------------
# Raw quotes in LLM-written attribute values
#
# The daily trackers have an LLM return the WHOLE selector, and prose about a
# UI keeps wanting quotes around a control name: `configurable under
# "Project instructions"`. Written raw inside a `"`-delimited attribute, that
# quote ENDS the attribute — build_catalog then ships the value cut off
# mid-sentence (#663, #692: the same three phrases, twice). The guard test
# catches it, but only after the PR is open, and the PR then sits failing.
#
# So repair it before the file is written. Deliberately narrow: only a line
# that holds ONE attribute and does not already parse cleanly is touched, the
# raw quotes inside its value are escaped (`\"`, the doc's own convention),
# and the edit is kept only if the line then parses as exactly that one
# attribute. Anything else is left for the guard test to report.
# ---------------------------------------------------------------------------

# Mirrors build_catalog's _ATTR_RE: a value may embed \" and \\.
ATTR_RE = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"', re.DOTALL)
# `<tag ` is optional so a first attribute sharing its element's line counts.
_ONE_ATTR_LINE = re.compile(
    r'^(?P<head>[ \t]*(?:<[\w-]+[ \t]+)?[\w-]+=")(?P<value>.*)(?P<tail>"[ \t]*(?:/?>)?[ \t]*)$'
)
_TAG_OPEN = re.compile(r"^[ \t]*<[\w-]+[ \t]+")
_NEXT_ATTR = re.compile(r'"\s+[\w-]+="')
_TAG_CLOSE = re.compile(r"[ \t]*/?>[ \t]*$")


def _residue(line: str) -> str:
    """What is left of an attribute line once every well-formed pair is gone."""
    blob = _TAG_CLOSE.sub("", _TAG_OPEN.sub("", line))
    return ATTR_RE.sub(" ", blob).strip()


def repair_attribute_quotes(text: str) -> tuple[str, list[str]]:
    """Escape raw quotes that would end a one-attribute line's value early.

    Returns (text, notes); each note names a repaired line, for the PR's
    warnings so a reviewer sees what was touched."""
    notes: list[str] = []
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if '="' not in line or not _residue(line):
            continue  # no attribute here, or it already parses whole
        m = _ONE_ATTR_LINE.match(line)
        # `" name="` inside the "value" is the next attribute, not prose: the
        # line holds several attributes and which quote ends which is a guess.
        if not m or _NEXT_ATTR.search(m.group("value")):
            continue
        value = re.sub(r'(?<!\\)"', r'\\"', m.group("value"))
        fixed = m.group("head") + value + m.group("tail")
        pairs = ATTR_RE.findall(_TAG_CLOSE.sub("", _TAG_OPEN.sub("", fixed)))
        if _residue(fixed) or len(pairs) != 1:
            continue
        lines[n] = fixed
        notes.append(f"escaped a raw quote in `{pairs[0][0]}` on line {n + 1}")
    return "\n".join(lines), notes
