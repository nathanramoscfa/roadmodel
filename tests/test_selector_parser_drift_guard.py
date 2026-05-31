"""Drift guard: the bundled selector's <output-format> template and
parse_response must stay in sync.

Regression guard for the 2026-05-31 production incident. PR #122 added the
ORCHESTRATION row to docs/model-selector.txt's <output-format> block, but
parse_response's regex in src/roadmodel/recommend.py was never taught about
it. Every provider response (which correctly followed the new template) then
raised MalformedResponseError once the new selector shipped in roadmodel
0.2.1 — production 500'd on every call for ~4 hours. See PR #130 (the fix)
and issue #134.

The tests below derive the expected response shape from the doc — the source
of truth the providers are instructed to follow — instead of hardcoding field
names. A future PR that adds a selector output field without teaching
parse_response about it fails here at PR time, not in production at the next
release boundary. This mirrors the contract-validation principle in
``feedback_monkeypatched_contract_validation`` applied to a different drift
surface (bundled artifact vs. consuming code).

Source-of-truth note: read from docs/model-selector.txt, NOT the bundled
src/roadmodel/data/ copy. The hatch build hook (hatch_build.py) copies
docs/ -> src/roadmodel/data/ at wheel build, so the in-repo bundled copy is
build output and can be stale in a checkout.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel.recommend import _REQUIRED_KEYS, parse_response  # noqa: E402

SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"

_OUTPUT_FORMAT_RE = re.compile(r"<output-format>(.*?)</output-format>", re.DOTALL)

# A field line in the <output-format> template looks like
#   "    MODEL: [Model Name]" or "    MAX MODE: [On/Off]".
# Field labels are uppercase words (possibly multi-word, e.g. "MAX MODE")
# immediately followed by a colon and a "[...]" placeholder. The trailing
# "[" requirement excludes prose lines such as "CRITICAL: Respond ..." that
# have no bracketed placeholder.
_FIELD_LINE_RE = re.compile(r"^[ \t]*([A-Z][A-Z ]*[A-Z]):[ \t]*\[", re.MULTILINE)

# Field names parse_response accepts beyond the strictly-required six.
# ORCHESTRATION is captured-then-dropped (added in the #130 fix); PROMPT is
# handled as an optional leading prefix / rationale terminator for
# roadmap-annotation mode. A field declared in the selector that is NOT in
# this set union _REQUIRED_KEYS is exactly the 2026-05-31 drift class.
_KNOWN_OPTIONAL_FIELDS = frozenset({"orchestration", "prompt"})

# Realistic single-line values for synthesizing a response that follows the
# template. Unknown/new fields fall back to a generic token so a freshly-added
# selector field still produces a parseable-looking line — letting
# parse_response decide whether the field breaks the regex.
_SAMPLE_VALUES = {
    "model": "Opus 4.8",
    "platform": "Claude Code",
    "max_mode": "Off",
    "thinking": "XHigh",
    "orchestration": "Ultracode",
    "conversation": "New",
    "rationale": "Synthesized from the selector output-format template.",
    "prompt": "1",
}


def _normalize(field_label: str) -> str:
    """Match parse_response's own key normalization (see _normalize_dict_payload)."""
    return field_label.strip().lower().replace(" ", "_")


def _output_format_block() -> str:
    text = SELECTOR_PATH.read_text(encoding="utf-8")
    match = _OUTPUT_FORMAT_RE.search(text)
    assert match, "<output-format>...</output-format> block not found in docs/model-selector.txt"
    return match.group(1)


def _declared_fields() -> list[str]:
    """Ordered, de-duplicated normalized field names from the template(s)."""
    block = _output_format_block()
    ordered: list[str] = []
    for raw in _FIELD_LINE_RE.findall(block):
        name = _normalize(raw)
        if name not in ordered:
            ordered.append(name)
    return ordered


def _synthesize_block(fields: list[str]) -> str:
    """Build a response that follows the template: one "FIELD: value" line per
    field, in the given order, with the template's own spacing for multi-word
    labels (e.g. "max_mode" -> "MAX MODE")."""
    lines = []
    for label in fields:
        marker = label.upper().replace("_", " ")
        lines.append(f"{marker}: {_SAMPLE_VALUES.get(label, 'placeholder')}")
    return "\n".join(lines) + "\n"


def test_output_format_block_is_discoverable() -> None:
    """Guards the extractor itself: if the <output-format> tag or its
    field-line shape changes, the other tests here would silently pass on an
    empty field list. Fail loudly instead, and pin that the required six keys
    are always discoverable in the template."""
    fields = _declared_fields()
    assert fields, "No fields extracted from <output-format>; the extractor regex drifted."
    missing = [key for key in _REQUIRED_KEYS if key not in fields]
    assert not missing, (
        f"Required parse_response keys {missing} are not declared in the selector's "
        f"<output-format>. Either the doc dropped a field or the parser over-requires."
    )


def test_full_template_response_parses() -> None:
    """A response following the *current* selector template — every field it
    declares, in document order — must parse. This is the direct regression
    for 2026-05-31: had this test existed, PR #122's new ORCHESTRATION row
    would have failed it immediately."""
    fields = _declared_fields()
    block = _synthesize_block(fields)
    result = parse_response(block)  # raises MalformedResponseError on drift
    assert result["model"] == _SAMPLE_VALUES["model"]
    assert result["platform"] == _SAMPLE_VALUES["platform"]
    assert all(result.get(key) for key in _REQUIRED_KEYS), (
        f"parse_response accepted the block but dropped required keys.\n"
        f"Declared fields: {fields}\nSynthesized block:\n{block}"
    )


def test_required_only_template_response_parses() -> None:
    """The legacy shape — only the required six fields, optional fields
    (ORCHESTRATION, PROMPT) omitted — must still parse, so a provider that
    omits an optional field never breaks the parser."""
    fields = [f for f in _declared_fields() if f in _REQUIRED_KEYS]
    block = _synthesize_block(fields)
    result = parse_response(block)
    assert all(result.get(key) for key in _REQUIRED_KEYS), (
        f"Required-only block failed to yield all required keys:\n{block}"
    )


def test_every_declared_field_is_recognized() -> None:
    """The contract assertion with the clearest failure message: every field
    the selector declares must be one parse_response recognizes. Catches both
    the breaking case (new field mid-block) and the silent case (new field the
    parser ignores) at PR time."""
    declared = set(_declared_fields())
    recognized = set(_REQUIRED_KEYS) | _KNOWN_OPTIONAL_FIELDS
    unknown = declared - recognized
    assert not unknown, (
        f"docs/model-selector.txt <output-format> declares field(s) {sorted(unknown)} that "
        f"parse_response does not recognize. This is the 2026-05-31 drift class. Fix: teach "
        f"src/roadmodel/recommend.py's _RESPONSE_BLOCK_RE about the field, then add it to "
        f"_KNOWN_OPTIONAL_FIELDS in this test (or _REQUIRED_KEYS if the field is mandatory)."
    )
