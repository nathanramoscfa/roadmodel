"""Admit typed refresh data while preserving reviewed agent instructions.

Run this trusted code on data blobs, never on code from a candidate PR.
Editorial prose and capabilities require an ordinary reviewed PR. Deterministic
prose is reconstructed from BASE prose and validated numbers.

A model joins or retires by rule (update/lifecycle_rules.py): a new ``<model>``
must be exactly the discovery lane's template filled with validated values,
lifecycle tags and access lists may name only catalogued ids, and a decline
line must carry a rule's reason. Everything else outside the typed fields
still needs review.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

UPDATE = Path(__file__).resolve().parent
if str(UPDATE) not in sys.path:
    sys.path.insert(0, str(UPDATE))

import build_catalog  # noqa: E402
import derive_ratings  # noqa: E402
import lifecycle_rules as rules  # noqa: E402
import model_prose  # noqa: E402
import render_md  # noqa: E402
import sync_static_availability  # noqa: E402

ROOT = UPDATE.parent
SELECTOR = "docs/model-selector.txt"
COST = "docs/model-tier-cost-scale.md"
BENCH = "docs/benchmarks.json"
CATALOG = "docs/catalog.json"
MARKDOWN = "docs/model-selector.md"
AVAILABILITY = "infra/model-availability.json"
SNAPSHOTS = tuple(f"update/{row[0]}" for row in build_catalog.EFFORT_SOURCES)
# Each provider's price snapshot, read by the discovery lane and the price
# overlay; data for scripts, never prompt text.
PROVIDER_SNAPSHOTS = tuple(
    f"update/catalog-{provider}.json"
    for provider in ("anthropic", "openai", "google", "xai", "deepseek", "zai", "mistral", "groq")
)
CONTEXT_WINDOWS = "docs/context-windows.json"
EFFORT_RATINGS = "docs/effort-ratings.json"
INPUTS = (
    SELECTOR,
    COST,
    BENCH,
    CATALOG,
    MARKDOWN,
    AVAILABILITY,
    *SNAPSHOTS,
    *PROVIDER_SNAPSHOTS,
    CONTEXT_WINDOWS,
    EFFORT_RATINGS,
)
BODY = r'(?:[^"/]|/(?!>)|"(?:[^"\\]|\\.)*")*?'
PAIR = re.compile(r'([a-z][a-z0-9-]*)="((?:[^"\\]|\\.)*)"', re.S)
ELEMENT = re.compile(rf"^[ \t]*<model\s+({BODY})/>[ \t]*(?:\n|$)", re.M)
METHOD = re.compile(rf"<method\s+({BODY})\s*/>", re.S)
SUPPORTS = re.compile(r'(supports-models=")([^"]*)(")')
PRICE_FIELDS = {"input-price-per-1m", "output-price-per-1m"}
RATING_FIELDS = {f"tier-{category}" for category in build_catalog.TASK_CATEGORIES}
TYPED_FIELDS = PRICE_FIELDS | RATING_FIELDS


def money(value: str) -> bool:
    return bool(re.fullmatch(r"\$\d{1,5}(?:\.\d{1,6})?", value)) and (
        Decimal(0) <= Decimal(value[1:]) <= Decimal(10000)
    )


def models(text: str) -> tuple[dict[str, dict[str, str]], dict[str, re.Match[str]]]:
    sections = list(
        re.finditer(r"^  <model-options>\n(.*?)^  </model-options>$", text, re.M | re.S)
    )
    if len(sections) != 1:
        raise ValueError("selector_section_count")
    section = sections[0]
    rows: dict[str, dict[str, str]] = {}
    spans: dict[str, re.Match[str]] = {}
    for match in ELEMENT.finditer(text, section.start(1), section.end(1)):
        pairs = PAIR.findall(match.group(1))
        attrs = dict(pairs)
        if len(pairs) != len(attrs) or PAIR.sub("", match.group(1)).strip():
            raise ValueError("selector_attribute_syntax")
        mid = attrs.get("id", "")
        if not mid or mid in rows:
            raise ValueError("selector_model_identity")
        rows[mid], spans[mid] = attrs, match
    residue = ELEMENT.sub("", section.group(1))
    if not rows or re.search(r"<model(?:\s|/?>)", residue):
        raise ValueError("selector_unparsed_model")
    return rows, spans


def typed_seed(base: str, proposed: str) -> str:
    """Copy only typed values into the exact base document, retaining all prose."""
    old, spans = models(base)
    new, _ = models(proposed)
    if old.keys() != new.keys():
        raise ValueError("selector_identity_change_requires_review")
    expected = base
    for mid, match in sorted(spans.items(), key=lambda item: -item[1].start()):
        element = match.group(0)
        for field in TYPED_FIELDS:
            if field not in old[mid] or field not in new[mid]:
                raise ValueError("selector_missing_typed_field")
            value = new[mid][field]
            if value == old[mid][field]:
                continue
            if (field in PRICE_FIELDS and not money(value)) or (
                field in RATING_FIELDS and value not in {"S", "A", "B", "C", "D"}
            ):
                raise ValueError("selector_invalid_typed_value")

            def replace_value(match: re.Match[str], value: str = value) -> str:
                return match[1] + value + match[3]

            element = re.sub(
                rf'({field}=")((?:[^"\\]|\\.)*)(")',
                replace_value,
                element,
                count=1,
            )
        expected = expected[: match.start()] + element + expected[match.end() :]
    return expected


def raw_selector(base: str, proposed: str) -> None:
    if typed_seed(base, proposed) != proposed:
        raise ValueError("selector_instructions_require_review")


# A new model carries the discovery lane's template fields, the prose marker
# update/model_prose.py writes, and the trailing day and lifecycle tags.
NEW_MODEL_REQUIRED = frozenset(
    {
        "id",
        "name",
        "input-price-per-1m",
        "output-price-per-1m",
        "jurisdiction",
        "headline-benchmarks",
        "pricing-notes",
        "best-for",
        *RATING_FIELDS,
    }
)
NEW_MODEL_FIELDS = NEW_MODEL_REQUIRED | {model_prose.MARKER, *rules.TRAILING_FIELDS}


def _trailing(
    attrs: dict[str, str], known: set[str], fields: tuple[str, ...]
) -> list[tuple[str, str]]:
    """A model's validated ``fields`` among the trailing ones, in its order."""
    out: list[tuple[str, str]] = []
    for key, value in attrs.items():
        if key not in fields:
            continue
        if key in rules.DATE_FIELDS and not rules.valid_date(value):
            raise ValueError("selector_invalid_lifecycle_value")
        if key == "superseded-by" and value not in known:
            raise ValueError("selector_invalid_lifecycle_value")
        out.append((key, value))
    return out


def _typed_value(field: str, value: str) -> None:
    if (field in PRICE_FIELDS and not money(value)) or (
        field in RATING_FIELDS and value not in rules.LETTERS
    ):
        raise ValueError("selector_invalid_typed_value")


def _base_element(element: str, old: dict[str, str], new: dict[str, str], known: set[str]) -> str:
    """A model the base has, with the typed values and lifecycle tags the
    proposal gives it and nothing else."""
    for field in TYPED_FIELDS:
        if field not in old or field not in new:
            raise ValueError("selector_missing_typed_field")
        value = new[field]
        if value == old[field]:
            continue
        _typed_value(field, value)

        def replace_value(match: re.Match[str], value: str = value) -> str:
            return match[1] + value + match[3]

        element = re.sub(rf'({field}=")((?:[^"\\]|\\.)*)(")', replace_value, element, count=1)
    tags = _trailing(new, known, rules.TAG_FIELDS)
    if tags != [(k, v) for k, v in old.items() if k in rules.TAG_FIELDS]:
        element = rules.append_trailing(rules.TAG_ATTR_RE.sub("", element), tags)
    return element


def _new_element(attrs: dict[str, str], jurisdictions: set[str], known: set[str]) -> str:
    """A model the base lacks, rebuilt from the discovery lane's template:
    only an id and a name in a narrow alphabet, prices, letters, a known
    jurisdiction, a fixed pricing note and the trailing tags. Its prose
    starts empty; update/model_prose.py writes it from data."""
    if not NEW_MODEL_REQUIRED <= attrs.keys() <= NEW_MODEL_FIELDS:
        raise ValueError("selector_new_model_fields")
    if not (rules.valid_id(attrs["id"]) and rules.valid_name(attrs["name"])):
        raise ValueError("selector_new_model_identity")
    if (
        attrs["jurisdiction"] not in jurisdictions
        or attrs["pricing-notes"] not in rules.PRICING_NOTES
    ):
        raise ValueError("selector_new_model_fields")
    for field in TYPED_FIELDS:
        _typed_value(field, attrs[field])
    element = rules.model_element(
        attrs["id"],
        attrs["name"],
        attrs["input-price-per-1m"],
        attrs["output-price-per-1m"],
        attrs["jurisdiction"],
        {c: attrs[f"tier-{c}"] for c in rules.CATEGORIES},
        attrs["pricing-notes"],
    )
    return rules.append_trailing(element, _trailing(attrs, known, rules.TRAILING_FIELDS))


def _swap(text: str, spans: dict[str, re.Match[str]], elements: dict[str, str]) -> str:
    """``text`` with each model element replaced by ``elements[id]`` (the
    element itself; the whitespace around it stays)."""
    for mid, match in sorted(spans.items(), key=lambda item: -item[1].start()):
        end = match.start() + len(match.group(0).rstrip())
        text = text[: match.start()] + elements[mid] + text[end:]
    return text


def _supports(text: str, known: set[str] | None) -> dict[str, str]:
    """Each access method's ``supports-models`` list; with ``known``, every id
    in it must be one of those."""
    lists: dict[str, str] = {}
    for match in METHOD.finditer(text):
        attrs = dict(PAIR.findall(match.group(1)))
        mid, value = attrs.get("id", ""), attrs.get("supports-models")
        if not mid or mid in lists:
            raise ValueError("selector_method_identity")
        if value is not None:
            ids = [x.strip() for x in value.split(",")]
            unknown = known is not None and value and not all(x in known for x in ids)
            if unknown or re.search(r",(?! ?\S)", value):
                raise ValueError("selector_access_list")
            lists[mid] = value
    return lists


def _with_supports(text: str, lists: dict[str, str]) -> str:
    def edit(match: re.Match[str]) -> str:
        mid = dict(PAIR.findall(match.group(1))).get("id", "")
        if mid not in lists:
            return match.group(0)
        return SUPPORTS.sub(lambda m: m[1] + lists[mid] + m[3], match.group(0), count=1)

    return METHOD.sub(edit, text)


def _generated(text: str, available: dict[str, Any] | None) -> str:
    """``text`` with the parts other layers regenerate written the same way."""
    text = derive_ratings.regenerate_coding_enumeration(text)
    text = derive_ratings.regenerate_multimodal_enumeration(text)
    if available is not None:
        text = sync_static_availability.rewrite_selector_text(text, available)
    return text


def lifecycle_seed(base: str, proposed: str, available: dict[str, Any] | None = None) -> str:
    """The proposal with every element rebuilt from what the rules allow, its
    prose as base has it (empty for a new model): typed values, lifecycle tags,
    access lists naming catalogued ids, and new models from the template. No
    model leaves the selector; a retired one keeps its element."""
    old, old_spans = models(base)
    new, new_spans = models(proposed)
    if old.keys() - new.keys():
        raise ValueError("selector_identity_removed")
    known = set(new)
    added = known - old.keys()
    jurisdictions = {attrs["jurisdiction"] for attrs in old.values() if "jurisdiction" in attrs}
    elements = {
        mid: _base_element(match.group(0).rstrip(), old[mid], new[mid], known)
        for mid, match in old_spans.items()
    }
    elements.update({mid: _new_element(new[mid], jurisdictions, known) for mid in added})
    # An id base already lists (a model since dropped from the options) may stay.
    base_lists = _supports(base, None)
    listed = {x.strip() for value in base_lists.values() for x in value.split(",")}
    lists = _supports(proposed, known | listed)
    if set(lists) != set(base_lists):
        raise ValueError("selector_method_identity")
    seed = _swap(proposed, new_spans, elements)
    # Without the new models, the seed must be base with only those edits.
    without, without_spans = seed, models(seed)[1]
    for mid in sorted(added, key=lambda m: -without_spans[m].start()):
        match = without_spans[mid]
        without = without[: match.start()] + without[match.end() :]
    expected = _with_supports(_swap(base, old_spans, elements), lists)
    if _generated(without, available) != _generated(expected, available):
        raise ValueError("selector_instructions_require_review")
    return seed


def _declined(lines: list[str]) -> tuple[list[str], list[str]]:
    """The declined section's decline lines and its other non-blank lines."""
    decl = [line for line in lines if rules.DECLINED_LINE_RE.match(line.strip())]
    rest = [line for line in lines if line.strip() and line not in decl]
    return decl, rest


def _section(lines: list[str]) -> tuple[int, int]:
    """(first, end) of the declined section: its heading to the next heading."""
    try:
        first = next(i for i, line in enumerate(lines) if line.strip() == rules.DECLINED_HEADING)
    except StopIteration:
        return len(lines), len(lines)
    end = next((i for i in range(first + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    return first, end


def declined_section(base: list[str], proposed: list[str]) -> None:
    """A decline line may go; one may join only with a rule's reason, a
    provider the catalog knows and a model name in the narrow alphabet."""
    old_decl, old_rest = _declined(base)
    new_decl, new_rest = _declined(proposed)
    if old_rest != new_rest:
        raise ValueError("costscale_prose_requires_review")
    kept = set(old_decl)
    for line in new_decl:
        if line in kept:
            continue
        m = rules.DECLINED_LINE_RE.match(line.strip())
        if m is None or line != line.rstrip() or not rules.valid_date(m["date"]):
            raise ValueError("costscale_decline_line")
        alias = rules.ALIAS_RE.fullmatch(m["reason"].split(", which", 1)[0])
        reason_ok = m["reason"] in rules.RULE_REASONS or (
            alias is not None and m["reason"] == rules.alias_reason(alias["id"])
        )
        slug_ok = rules.valid_name(m["slug"]) or rules.valid_id(m["slug"])
        if not (reason_ok and slug_ok and m["provider"] in rules.PROVIDER_LABEL):
            raise ValueError("costscale_decline_line")


_PLAIN_TEXT = re.compile(r"[^\x00-\x1f<>\"`\\]{0,300}")


def _plain(value: Any, depth: int = 0) -> None:
    """Plain data: short text without markup, bounded finite numbers."""
    if depth > 6:
        raise ValueError("data_depth")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or not 0 <= value <= 1_000_000_000:
            raise ValueError("data_number")
    elif isinstance(value, str):
        if not _PLAIN_TEXT.fullmatch(value):
            raise ValueError("data_text")
    elif isinstance(value, list):
        for item in value:
            _plain(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            _plain(key, depth + 1)
            _plain(item, depth + 1)
    else:
        raise ValueError("data_type")


def provider_snapshot(base: str, proposed: str) -> None:
    """A provider's price snapshot: scripts read it, the recommender never
    does. Each field keeps base's value or holds plain data (short text
    without markup, bounded numbers), so a reader may add a field."""
    old, new = json.loads(base), json.loads(proposed)
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise ValueError("snapshot_structure")
    for key, value in new.items():
        if old.get(key, _MISSING) != value:
            _plain(key)
            _plain(value)


_MISSING = object()


def context_windows(base: str, proposed: str, known: set[str]) -> None:
    old, new = json.loads(base), json.loads(proposed)
    if not isinstance(new, dict) or new.keys() != old.keys():
        raise ValueError("context_windows_structure")
    if any(new[key] != old[key] for key in new if key != "models"):
        raise ValueError("context_windows_fixed_field")
    rows = new["models"]
    if not isinstance(rows, dict) or not rows.keys() <= known | old["models"].keys():
        raise ValueError("context_windows_identity")
    if any(type(v) is not int or not 1_000 <= v <= 100_000_000 for v in rows.values()):
        raise ValueError("context_windows_value")


def effort_ratings(base: str, proposed: str, known: set[str]) -> None:
    old, new = json.loads(base), json.loads(proposed)
    if not isinstance(new, dict) or new.keys() != old.keys():
        raise ValueError("effort_ratings_structure")
    if any(new[key] != old[key] for key in new if key != "models"):
        raise ValueError("effort_ratings_fixed_field")
    rows = new["models"]
    if not isinstance(rows, dict) or not rows.keys() <= known:
        raise ValueError("effort_ratings_identity")
    for efforts in rows.values():
        if not isinstance(efforts, dict):
            raise ValueError("effort_ratings_value")
        for effort, letters in efforts.items():
            if not re.fullmatch(r"[a-z]{2,12}", effort) or not isinstance(letters, dict):
                raise ValueError("effort_ratings_value")
            for category, letter in letters.items():
                if category not in rules.CATEGORIES or letter not in rules.LETTERS:
                    raise ValueError("effort_ratings_value")


def costscale(base: str, proposed: str) -> None:
    """Only numeric cells in existing pricing rows and rule decline lines; all
    names and prose stay fixed."""
    old, new = base.splitlines(keepends=True), proposed.splitlines(keepends=True)
    a0, a1 = _section(old)
    b0, b1 = _section(new)
    declined_section(
        [line.rstrip("\n") for line in old[a0:a1]], [line.rstrip("\n") for line in new[b0:b1]]
    )
    old, new = old[:a0] + old[a1:], new[:b0] + new[b1:]
    if len(old) != len(new):
        raise ValueError("costscale_structure_requires_review")
    header: list[str] = []
    for a, b in zip(old, new, strict=True):
        cells_a = [x.strip() for x in a.split("|")[1:-1]]
        cells_b = [x.strip() for x in b.split("|")[1:-1]]
        if cells_a and cells_a[0] in {"Model", "Subscription"}:
            header = cells_a
        elif not a.strip().startswith("|"):
            header = []
        if a == b:
            continue
        if not header or len(cells_a) != len(header) or len(cells_b) != len(header):
            raise ValueError("costscale_prose_requires_review")
        allowed = {"Input", "Cache Write", "Cache Read", "Output", "Monthly", "Annual"}
        for key, before, after in zip(header, cells_a, cells_b, strict=True):
            if before == after:
                continue
            if key in allowed and money(after) and (money(before) or before in {"–", "—", "-"}):
                continue
            if key == "Tier" and after in {"Low", "Medium", "High", "Very High"}:
                continue
            raise ValueError("costscale_frozen_cell")
        # Changes outside table cells (including hidden trailing markup) fail.
        if not re.fullmatch(r"[ \t]*\|[^\n]*\|[ \t]*\n?", b):
            raise ValueError("costscale_table_syntax")


def benchmarks(base: str, proposed: str) -> dict[str, Any]:
    old, new = json.loads(base), json.loads(proposed)
    before, after = old["models"], new["models"]
    if not isinstance(after, dict) or not after.keys() <= before.keys():
        raise ValueError("benchmark_identity_requires_review")
    for mid, row in after.items():
        if row.get("aa_name") != before[mid].get("aa_name"):
            raise ValueError("benchmark_name_requires_review")
        if row.get("release_date") is not None:
            dt.date.fromisoformat(row["release_date"])
        values = list(row.get("evaluations", {}).values())
        values += [row.get("median_output_tokens_per_second")]
        if any(
            value is not None
            and (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= 1_000_000
            )
            for value in values
        ):
            raise ValueError("benchmark_invalid_number")
    return dict(new)


def availability(base: str, proposed: str, selector: str) -> dict[str, Any]:
    """``selector`` names the catalogued models (the proposal's, whose new ids
    final_selector admits by rule)."""
    old, new = json.loads(base), json.loads(proposed)
    old_rows = {row["id"]: row for row in old["unavailable"]}
    known, _ = models(selector)
    rows = new["unavailable"]
    if not isinstance(rows, list) or len(rows) > len(known):
        raise ValueError("availability_bounds")
    seen = set()
    for row in rows:
        mid = row["id"]
        if mid not in known or mid in seen:
            raise ValueError("availability_identity")
        seen.add(mid)
        since = dt.date.fromisoformat(row["since"]).isoformat()
        reason = (
            "Auto-detected unavailable by the daily availability probe on "
            f"{since} (provider API reported not-found)."
        )
        if row.get("reason") not in (old_rows.get(mid, {}).get("reason"), reason):
            raise ValueError("availability_reason_requires_review")
    return dict(new)


def final_selector(
    base: str,
    proposed: str,
    bench: dict[str, Any],
    day: dt.date,
    available: dict[str, Any] | None = None,
) -> None:
    seed = lifecycle_seed(base, proposed, available)
    expected, _ = model_prose.apply(seed, bench, day)
    expected = derive_ratings.regenerate_coding_enumeration(expected)
    expected = derive_ratings.regenerate_multimodal_enumeration(expected)
    candidates = [seed, expected]
    if available is not None:
        candidates += [
            sync_static_availability.rewrite_selector_text(text, available) for text in candidates
        ]
    if proposed not in candidates:
        raise ValueError("selector_generated_content_mismatch")


def validate_documents(
    before: Callable[[str], str], after: Callable[[str], str], day: dt.date
) -> None:
    base = {path: before(path) for path in INPUTS}
    head = {path: after(path) for path in INPUTS}
    costscale(base[COST], head[COST])
    bench = benchmarks(base[BENCH], head[BENCH])
    known = set(models(head[SELECTOR])[0])
    for path in PROVIDER_SNAPSHOTS:
        provider_snapshot(base[path], head[path])
    context_windows(base[CONTEXT_WINDOWS], head[CONTEXT_WINDOWS], known)
    effort_ratings(base[EFFORT_RATINGS], head[EFFORT_RATINGS], known)
    available = availability(base[AVAILABILITY], head[AVAILABILITY], head[SELECTOR])
    final_selector(base[SELECTOR], head[SELECTOR], bench, day, available)
    if head[MARKDOWN] != render_md.render(head[SELECTOR]):
        raise ValueError("selector_markdown_mismatch")
    # Generate using only the trusted checkout's code. Candidate files are data
    # in a new directory; no candidate module, hook, dependency or symlink runs.
    with tempfile.TemporaryDirectory(prefix="roadmodel-integrity-") as temp:
        directory = Path(temp)
        for path, text in head.items():
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        saved = (
            build_catalog.SELECTOR_PATH,
            build_catalog.COST_SCALE_PATH,
            build_catalog._UPDATE_DIR,
        )
        try:
            build_catalog.SELECTOR_PATH = directory / SELECTOR
            build_catalog.COST_SCALE_PATH = directory / COST
            build_catalog._UPDATE_DIR = directory / "update"
            expected_catalog = build_catalog.build_catalog()
        finally:
            (
                build_catalog.SELECTOR_PATH,
                build_catalog.COST_SCALE_PATH,
                build_catalog._UPDATE_DIR,
            ) = saved
    actual_catalog = json.loads(head[CATALOG])
    # Build timestamps are metadata, never instructions; validate their type.
    dt.datetime.fromisoformat(actual_catalog["generated_at_utc"].replace("Z", "+00:00"))
    expected_catalog["generated_at_utc"] = actual_catalog["generated_at_utc"]
    if actual_catalog != expected_catalog:
        raise ValueError("catalog_generated_content_mismatch")


def git_read(ref: str, path: str) -> str:
    return subprocess.check_output(  # noqa: S603 — fixed git, argument vector only
        ["git", "show", f"{ref}:{path}"],  # noqa: S607 — trusted git executable
        cwd=ROOT,
        text=True,
        timeout=30,  # noqa: S607
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--head", help="immutable candidate commit; default: working data")
    args = parser.parse_args()

    def working(path: str) -> str:
        target = ROOT / path
        if target.is_symlink() or target.resolve() != target:
            raise ValueError("data_symlink")
        return target.read_text(encoding="utf-8")

    try:
        report = UPDATE / ".last-prose-guard.md"
        if not args.head and report.exists() and report.stat().st_size:
            raise ValueError("quarantined_source_not_promoted")
        validate_documents(
            lambda p: git_read(args.base, p),
            (lambda p: git_read(args.head, p)) if args.head else working,
            dt.datetime.now(dt.UTC).date(),
        )
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print("Refresh requires reviewed instructions or valid derived data.", file=sys.stderr)
        return 1
    print("Refresh instruction integrity verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
