"""Admit typed refresh data while preserving reviewed agent instructions.

Run this trusted code on data blobs, never on code from a candidate PR. New
identities, capabilities and editorial prose require an ordinary reviewed PR.
Deterministic prose is reconstructed from BASE prose and validated numbers.
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
INPUTS = (SELECTOR, COST, BENCH, CATALOG, MARKDOWN, AVAILABILITY, *SNAPSHOTS)
BODY = r'(?:[^"/]|/(?!>)|"(?:[^"\\]|\\.)*")*?'
PAIR = re.compile(r'([a-z][a-z0-9-]*)="((?:[^"\\]|\\.)*)"', re.S)
ELEMENT = re.compile(rf"^[ \t]*<model\s+({BODY})/>[ \t]*(?:\n|$)", re.M)
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


def costscale(base: str, proposed: str) -> None:
    """Only numeric cells in existing pricing rows; all names and prose stay fixed."""
    old, new = base.splitlines(keepends=True), proposed.splitlines(keepends=True)
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
    seed = typed_seed(base, proposed)
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
    available = availability(base[AVAILABILITY], head[AVAILABILITY], base[SELECTOR])
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
