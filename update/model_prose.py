#!/usr/bin/env python3
"""Write each model's ``best-for`` and ``headline-benchmarks`` from data.

The /models page shows both fields ("Best for", "Benchmarks cited"), the
recommender reads them in its prompt, and docs/catalog.json carries them to the
MCP catalog. The catalog cron used to fill them, for a model it added, with
placeholder text ("Auto-added cheap-tier Meta model; pending editorial best-for
refinement.") on the promise that a maintainer would rewrite it. Nothing ever
did, so the placeholders shipped, and the cron's own process notes ("placeholder
tier ratings inherited from X pending editorial review", "per the
equal-output-price replacement rule") leaked into the text of the models it
kept.

This pass makes the text a FUNCTION of the data, the way
update/derive_ratings.py does for four of the letters and update/supersede.py
for the lifecycle tags. It takes over a field when the field is empty, narrates
the pipeline instead of describing the model (PROCESS_RE), or, for
``headline-benchmarks``, cites none of the Artificial Analysis figures the
catalog holds for the model. It records each field it owns in the element's
``prose-generated`` attribute and rewrites that field on every run, so the text
follows the letters, prices and benchmarks it is built from. A field it does
not own is left exactly as written.

    best-for             what the model's letters say it does best, at what
                         cost tier; where its AA Intelligence Index ranks in the
                         catalog and the catalog-wide records it holds (highest
                         index, highest at its price, cheapest S in a category);
                         its weakest categories; its successor.
    headline-benchmarks  the Artificial Analysis figures (docs/benchmarks.json):
                         the Intelligence Index and the benchmarks behind the
                         derived letters, then the field's other sourced claims
                         (LMArena, vendor-reported results, context window), in
                         their original order. A model AA has not measured says
                         so, since its letters are then estimates.

    python update/model_prose.py            # report what --write would change
    python update/model_prose.py --write    # apply to docs/model-selector.txt
    python update/model_prose.py --check    # exit 1 if the selector disagrees

Run it after derive_ratings.py and supersede.py (it reads the letters and tags
they write), then render_md.py and build_catalog.py, as for any selector edit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UPDATE_DIR = Path(__file__).resolve().parent
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

from build_catalog import TASK_CATEGORIES, _parse_attrs, _parse_models  # noqa: E402
from selector_re import MODEL_RE  # noqa: E402

REPO_ROOT = UPDATE_DIR.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
BENCHMARKS_PATH = REPO_ROOT / "docs" / "benchmarks.json"

MARKER = "prose-generated"
FIELDS = ("best-for", "headline-benchmarks")

# Text about the catalog's own process rather than the model: the cron's
# placeholders and the bookkeeping it wrote into prose. A field that matches
# is the generator's from then on. tests/test_model_prose.py holds the whole
# selector to this, so a cron PR cannot ship one.
PROCESS_RE = re.compile(
    r"auto-added|pending|placeholder|editorial|inherit|next refresh|"
    r"replacement rule|dry-run|head-to-head|catalog cron|no benchmark figures",
    re.IGNORECASE,
)

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_MARKER_ATTR_RE = re.compile(rf'\s+{MARKER}="[^"]*"')
_VARIANT_RE = re.compile(r"\(([^()]+)\)\s*$")

# The six task categories; speed is a property of the output, not a task.
TASKS = tuple(c for c in TASK_CATEGORIES if c != "speed")
LETTERS = "SABCD"
NOUN = {
    "coding": "coding",
    "planning": "planning",
    "agentic": "agentic work",
    "multimodal": "multimodal input",
    "long-context": "long context",
    "knowledge": "knowledge",
    "speed": "speed",
}
# The meaning of each letter in <model-options> of the selector.
LEVEL = {"S": "Frontier-class", "A": "Strong", "B": "Competent", "C": "Limited", "D": "Basic"}
COST = {"low": "low", "medium": "medium", "high": "high", "very-high": "very high"}

# The clauses this pass writes into headline-benchmarks, recognised so a rerun
# replaces them with the current figures. A vendor-reported figure under the
# same name ("... (DeepSeek-reported)") is a different claim and stays.
_OWN_CLAUSE_RE = re.compile(
    r"^(?:AA Intelligence Index|HLE|SciCode|Terminal-Bench 4\.0|AA-LCR)\s+\d"
)
_UNMEASURED_RE = re.compile(r"^Artificial Analysis has not measured ")


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    tier_cost: str
    blended: float | None
    letters: dict[str, str]
    bench: dict[str, Any] | None  # its docs/benchmarks.json row
    index: float | None  # AA Intelligence Index, measured
    superseded_by: str | None


def _blended(m: dict[str, Any]) -> float | None:
    i, o = m["input_price_per_1m"], m["output_price_per_1m"]
    return None if i is None or o is None else (3 * i + o) / 4


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def load_models(selector_text: str, benchmarks: dict[str, Any]) -> list[Model]:
    """Every model still in the catalog (a retired one has left it)."""
    rows = benchmarks.get("models", {})
    out: list[Model] = []
    for m in _parse_models(selector_text):
        if m["retired_on"]:
            continue
        bench = rows.get(m["id"])
        evals = (bench or {}).get("evaluations") or {}
        out.append(
            Model(
                id=m["id"],
                name=m["name"] or m["id"],
                tier_cost=m["tier_cost"],
                blended=_blended(m),
                letters=m["tiers"],
                bench=bench,
                index=_num(evals.get("artificial_analysis_intelligence_index")),
                superseded_by=m["superseded_by"],
            )
        )
    return out


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _rank(letter: str) -> int:
    return LETTERS.index(letter) if letter in LETTERS else len(LETTERS)


# ---------------------------------------------------------------------------
# best-for
# ---------------------------------------------------------------------------


def _lead(m: Model) -> str:
    """'Frontier-class coding, plus strong agentic work and knowledge, at a low price.'"""
    graded = [c for c in TASKS if m.letters.get(c, "") in LETTERS]
    top = min((m.letters[c] for c in graded), key=_rank, default="")
    parts: list[str] = []
    if top:
        parts.append(f"{LEVEL[top]} {_join([NOUN[c] for c in graded if m.letters[c] == top])}")
        strong = [NOUN[c] for c in graded if m.letters[c] == "A"]
        if top == "S" and strong:
            parts.append(f"plus strong {_join(strong)}")
    speed = m.letters.get("speed", "")
    if speed in ("S", "A"):
        parts.append("with very fast output" if speed == "S" else "with fast output")
    cost = f"at a {COST.get(m.tier_cost, m.tier_cost)} price"
    if not parts:
        return f"General use {cost}."
    return ", ".join(parts) + ("," if len(parts) > 1 else "") + f" {cost}."


def _index_sentence(m: Model, catalog: list[Model]) -> str | None:
    if m.index is None:
        return None
    measured = [o for o in catalog if o.index is not None]
    above = [o for o in measured if o.index > m.index]  # type: ignore[operator]
    figure = f"Its AA Intelligence Index of {m.index:.1f}"
    if not above:
        return f"{figure} is the highest in the catalog."
    sentence = f"{figure} ranks {_ordinal(len(above) + 1)} of {len(measured)} measured models"
    if m.blended is not None and not any(
        o.blended is not None and o.blended <= m.blended for o in above
    ):
        sentence += ", the highest of any model at its price or lower"
    return sentence + "."


def _cheapest_sentence(m: Model, catalog: list[Model]) -> str | None:
    if m.blended is None:
        return None
    held = [
        c
        for c in TASKS
        if m.letters.get(c) == "S"
        and all(
            o.blended is not None and o.blended > m.blended
            for o in catalog
            if o.id != m.id and o.letters.get(c) == "S"
        )
    ]
    if not held:
        return None
    return f"It is the cheapest model in the catalog rated S for {_join([NOUN[c] for c in held])}."


def _weakest_sentence(m: Model) -> str | None:
    groups = []
    for letter in ("D", "C"):
        cats = [NOUN[c] for c in TASK_CATEGORIES if m.letters.get(c) == letter]
        if cats:
            groups.append(f"{_join(cats)} ({letter})")
    return f"Weakest at {', then '.join(groups)}." if groups else None


def best_for(m: Model, catalog: list[Model]) -> str:
    names = {o.id: o.name for o in catalog}
    sentences = [
        _lead(m),
        _index_sentence(m, catalog),
        _cheapest_sentence(m, catalog),
        _weakest_sentence(m),
        f"Superseded by {names.get(m.superseded_by, m.superseded_by)}."
        if m.superseded_by
        else None,
    ]
    return " ".join(s for s in sentences if s)


# ---------------------------------------------------------------------------
# headline-benchmarks
# ---------------------------------------------------------------------------


def split_clauses(text: str) -> list[str]:
    """Split on the ';' between claims, not the ones inside parentheses."""
    clauses: list[str] = []
    depth, start = 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == ";" and depth == 0:
            clauses.append(text[start:i])
            start = i + 1
    clauses.append(text[start:])
    return [c.strip() for c in clauses if c.strip()]


def aa_clauses(bench: dict[str, Any] | None) -> list[str]:
    """The Artificial Analysis figures, in the catalog's established notation:
    the composite first, then the benchmark behind each derived letter
    (knowledge, coding, agentic, long context).

    AA's tokens/s stays out: it is measured on the maker's own endpoint at max
    effort, which is the wrong evidence for the speed letter (see
    derive_ratings.py) and contradicts a hosted figure such as gpt-oss on Groq.
    The /models grid shows it in its own column."""
    if not bench:
        return []
    ev = bench.get("evaluations") or {}
    out: list[str] = []
    index = _num(ev.get("artificial_analysis_intelligence_index"))
    if index is not None:
        variant = _VARIANT_RE.search(str(bench.get("aa_name", "")))
        out.append(
            f"AA Intelligence Index {index:.1f}"
            + (f" ({variant.group(1).lower()})" if variant else "")
        )
    # (label, key, scale, format): AA stores fractions; the catalog writes
    # HLE as a percentage, SciCode and Terminal-Bench as points, AA-LCR as is.
    figures: tuple[tuple[str, str, float, str], ...] = (
        ("HLE", "hle", 100, "{:.1f}%"),
        ("SciCode", "scicode", 100, "{:.1f}"),
        ("Terminal-Bench 4.0", "terminalbench_v4_0", 100, "{:.1f}"),
        ("AA-LCR", "lcr", 1, "{:.3f}"),
    )
    for label, key, scale, fmt in figures:
        v = _num(ev.get(key))
        if v is not None:
            out.append(f"{label} {fmt.format(v * scale)}")
    return out


def headline(m: Model, current: str) -> str:
    own = aa_clauses(m.bench)
    kept = [
        c
        for c in split_clauses(current)
        if not PROCESS_RE.search(c) and not _UNMEASURED_RE.match(c)
    ]
    if not own:
        # Commas, not a semicolon: the field's claims are ';'-separated.
        note = f"Artificial Analysis has not measured {m.name} yet, so its letters are estimates"
        return "; ".join([*kept, note])
    kept = [c for c in kept if not (_OWN_CLAUSE_RE.match(c) and "reported" not in c.lower())]
    return "; ".join(own + kept)


# ---------------------------------------------------------------------------
# Ownership and the selector edit
# ---------------------------------------------------------------------------


def owned_fields(attrs: dict[str, str], m: Model) -> list[str]:
    """The fields this pass writes for one element, in FIELDS order."""
    marked = set(attrs.get(MARKER, "").split())
    out: list[str] = []
    for field in FIELDS:
        text = attrs.get(field, "").strip()
        if field in marked or not text or PROCESS_RE.search(text):
            out.append(field)
        elif (
            field == "headline-benchmarks"
            and m.index is not None
            and "Intelligence Index" not in text
        ):
            out.append(field)
    return out


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _set_attr(element: str, name: str, value: str) -> str:
    pattern = re.compile(rf'(\s{re.escape(name)}=")((?:[^"\\]|\\.)*)(")')
    m = pattern.search(element)
    if m is None:
        raise ValueError(f"element has no {name} attribute: {element[:80]!r}")
    return element[: m.start(2)] + _escape(value) + element[m.end(2) :]


def _set_marker(element: str, fields: list[str]) -> str:
    """Write ``prose-generated`` on the line before ``best-for`` (same indent),
    or remove it when the pass owns nothing."""
    value = " ".join(fields)
    current = re.search(rf'\s{MARKER}="([^"]*)"', element)
    if current is not None:
        if not fields:
            return _MARKER_ATTR_RE.sub("", element, count=1)
        return element[: current.start(1)] + value + element[current.end(1) :]
    if not fields:
        return element
    anchor = re.search(r'(\s+)best-for="', element)
    if anchor is None:
        raise ValueError(f"element has no best-for attribute: {element[:80]!r}")
    return (
        element[: anchor.start()]
        + anchor.group(1)
        + f'{MARKER}="{value}"'
        + element[anchor.start() :]
    )


@dataclass(frozen=True)
class Change:
    id: str
    field: str
    old: str
    new: str


def apply(selector_text: str, benchmarks: dict[str, Any]) -> tuple[str, list[Change]]:
    """The selector with every owned field rewritten, and what changed."""
    catalog = load_models(selector_text, benchmarks)
    by_id = {m.id: m for m in catalog}
    options = _OPTIONS_RE.search(selector_text)
    if options is None:
        raise ValueError("<model-options> block not found in selector text")
    base = options.start(1)
    spans = []
    for el in MODEL_RE.finditer(options.group(1)):
        spans.append((base + el.start(), base + el.end(), _parse_attrs(el.group(1))))

    text = selector_text
    changes: list[Change] = []
    # Edit from the end so earlier spans stay valid.
    for start, end, attrs in sorted(spans, key=lambda s: -s[0]):
        m = by_id.get(attrs.get("id", ""))
        if m is None:
            continue  # retired: the record stays as it was
        element = text[start:end]
        fields = owned_fields(attrs, m)
        for field in fields:
            old = attrs.get(field, "")
            new = best_for(m, catalog) if field == "best-for" else headline(m, old)
            if new != old:
                element = _set_attr(element, field, new)
                changes.append(Change(m.id, field, old, new))
        element = _set_marker(element, fields)
        if element != text[start:end]:
            text = text[:start] + element + text[end:]
    changes.reverse()
    return text, changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write model prose from the catalog's data.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="apply to docs/model-selector.txt")
    mode.add_argument("--check", action="store_true", help="exit 1 if the selector disagrees")
    args = parser.parse_args(argv)

    selector_text = SELECTOR_PATH.read_text()
    benchmarks = json.loads(BENCHMARKS_PATH.read_text()) if BENCHMARKS_PATH.exists() else {}
    new_text, changes = apply(selector_text, benchmarks)

    for c in changes:
        print(f"PROSE {c.id} {c.field}: {c.new}")
    if args.check:
        if new_text != selector_text:
            print(
                "docs/model-selector.txt disagrees with update/model_prose.py — run "
                "`python update/model_prose.py --write`, then render_md.py and build_catalog.py.",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.write and new_text != selector_text:
        SELECTOR_PATH.write_text(new_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
