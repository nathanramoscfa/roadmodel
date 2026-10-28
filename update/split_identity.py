#!/usr/bin/env python3
"""Ship what the typed refresh boundary admits; hold the rest for review.

update/automation_integrity.py admits only typed edits to the catalog data
(prices, rating letters, regenerated prose), and the security policy binds every
other committed file to reviewed code (scripts/security_catalog.py). A refresh
carries more than that whenever a provider ships a model: a new ``<model>``, an
access-list entry, a decline line, a provider snapshot, an AA row for a new id.
Until 2026-10 one such change failed the whole run, so for a week no price or
letter shipped either, and Gemini 4 Argon never reached the catalog (#1120).

This script runs before the integrity check. When the working candidate passes
the gate and touches no file outside the data set, it does nothing. Otherwise:

1. it copies the full candidate into ``--hold`` (the review PR's content);
2. it rewrites the working tree to the typed part, built the way the gate
   builds its own expectation, so the gate admits it by construction:
   - every other file the refresh touched goes back to its base copy
     (provider snapshots, context windows, effort ratings, the AA map);
   - the selector keeps only the typed values of the models base already has,
     with provider-direct prices forced back to base's snapshots (tests hold
     the selector to the committed snapshot);
   - the cost scale keeps only the admissible price and tier cells of rows
     base already has, provider-direct prices forced back the same way;
   - benchmarks and availability keep only rows for models base already has;
   - prose and catalog.json are regenerated from those; the workflow then
     runs update/render_md.py, the one writer of the selector markdown;
3. it writes ``update/.last-held.md``, naming what waits for review and the
   gate's reason for refusing the full candidate.

The workflow supplies the base copies (``git archive HEAD``), so this script
runs no subprocess.

    python update/split_identity.py --base-dir BASE --hold DIR --paths P [P ...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

UPDATE = Path(__file__).resolve().parent
if str(UPDATE) not in sys.path:
    sys.path.insert(0, str(UPDATE))

import automation_integrity as ai  # noqa: E402
import build_catalog  # noqa: E402
import derive_ratings  # noqa: E402
import merge_catalog  # noqa: E402
import model_prose  # noqa: E402
import render_md  # noqa: E402
import sync_static_availability  # noqa: E402

ROOT = UPDATE.parent
REPORT = UPDATE / ".last-held.md"
_SUPPORTS = re.compile(r'<method\s+id="([^"]+)"[^>]*?supports-models="([^"]*)"', re.S)
_TABLE_ROW = re.compile(r"[ \t]*\|[^\n]*\|[ \t]*\n?")
_ALLOWED_CELLS = {"Input", "Cache Write", "Cache Read", "Output", "Monthly", "Annual"}
_TIERS = {"Low", "Medium", "High", "Very High"}
_DASHES = {"–", "—", "-"}


def typed_selector(base: str, proposed: str) -> str:
    """``base`` with the typed values ``proposed`` gives the models base has.
    New and dropped models, tags, access lists and prose stay as base has them."""
    old, spans = ai.models(base)
    new, _ = ai.models(proposed)
    out = base
    for mid, match in sorted(spans.items(), key=lambda item: -item[1].start()):
        if mid not in new:
            continue
        element = match.group(0)
        for field in sorted(ai.TYPED_FIELDS):
            value = new[mid].get(field)
            if value is None or field not in old[mid] or value == old[mid][field]:
                continue
            if (field in ai.PRICE_FIELDS and not ai.money(value)) or (
                field in ai.RATING_FIELDS and value not in {"S", "A", "B", "C", "D"}
            ):
                continue

            def replace_value(m: re.Match[str], value: str = value) -> str:
                return m[1] + value + m[3]

            element = re.sub(rf'({field}=")((?:[^"\\]|\\.)*)(")', replace_value, element, count=1)
        out = out[: match.start()] + element + out[match.end() :]
    return out


def _cells(line: str) -> list[str]:
    return [x.strip() for x in line.split("|")[1:-1]]


def _admissible_row(header: list[str], before: str, after: str) -> bool:
    a, b = _cells(before), _cells(after)
    if len(a) != len(header) or len(b) != len(header) or not _TABLE_ROW.fullmatch(after):
        return False
    for key, x, y in zip(header, a, b, strict=True):
        if x == y:
            continue
        if key in _ALLOWED_CELLS and ai.money(y) and (ai.money(x) or x in _DASHES):
            continue
        if key == "Tier" and y in _TIERS:
            continue
        return False
    return True


def _rows(text: str) -> dict[tuple[str, str], str]:
    """``{(heading, first cell): line}`` for every row of a recognised table."""
    rows: dict[tuple[str, str], str] = {}
    heading, header = "", False
    for line in text.splitlines(keepends=True):
        if line.startswith("#"):
            heading = line.strip()
        cells = _cells(line)
        if cells and cells[0] in {"Model", "Subscription"}:
            header = True
        elif not line.strip().startswith("|"):
            header = False
        elif header and cells:
            rows.setdefault((heading, cells[0]), line)
    return rows


def typed_costscale(base: str, proposed: str) -> str:
    """``base`` with each existing row's admissible cells from ``proposed``.
    The same header rule as automation_integrity.costscale: rows outside a
    Model/Subscription table, added rows and prose stay as base has them."""
    head_rows = _rows(proposed)
    out: list[str] = []
    heading, header = "", []
    for line in base.splitlines(keepends=True):
        if line.startswith("#"):
            heading = line.strip()
        cells = _cells(line)
        if cells and cells[0] in {"Model", "Subscription"}:
            header = cells
        elif not line.strip().startswith("|"):
            header = []
        elif header and cells:
            after = head_rows.get((heading, cells[0]))
            if after is not None and after != line:
                if not after.endswith("\n") and line.endswith("\n"):
                    after += "\n"
                if _admissible_row(header, line, after):
                    out.append(after)
                    continue
        out.append(line)
    return "".join(out)


def typed_benchmarks(base: str, proposed: str) -> str:
    """``proposed`` without rows for ids base lacks or rows whose AA model changed."""
    old, new = json.loads(base), json.loads(proposed)
    before, after = old["models"], new["models"]
    keep = {
        mid: (row if row.get("aa_name") == before[mid].get("aa_name") else before[mid])
        for mid, row in after.items()
        if mid in before
    }
    if keep == after:
        return proposed
    new["models"] = keep
    new["model_count"] = len(keep)
    return json.dumps(new, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def typed_availability(base: str, proposed: str, selector: str) -> str:
    """``proposed`` keeping only rows for models the base selector has."""
    known, _ = ai.models(selector)
    new = json.loads(proposed)
    rows = [row for row in new["unavailable"] if row.get("id") in known]
    if rows == new["unavailable"]:
        return proposed
    new["unavailable"] = rows
    return json.dumps(new, indent=2, ensure_ascii=False) + "\n"


def _supports(selector: str) -> dict[str, set[str]]:
    return {
        mid: {x.strip() for x in ids.split(",") if x.strip()}
        for mid, ids in _SUPPORTS.findall(selector)
    }


def held_report(base: dict[str, str], full: dict[str, str], others: list[str], reason: str) -> str:
    """What the review PR carries that the typed refresh does not."""
    lines = ["## Held for review", "", f"The gate refused the full candidate: `{reason}`.", ""]
    old, _ = ai.models(base[ai.SELECTOR])
    new, _ = ai.models(full[ai.SELECTOR])
    for mid in sorted(new.keys() - old.keys()):
        attrs = new[mid]
        lines.append(
            f"- new model `{mid}` ({attrs.get('name', mid)}, "
            f"{attrs.get('input-price-per-1m', '?')}/{attrs.get('output-price-per-1m', '?')})"
        )
    for mid in sorted(old.keys() - new.keys()):
        lines.append(f"- model `{mid}` removed")
    before, after = _supports(base[ai.SELECTOR]), _supports(full[ai.SELECTOR])
    for method in sorted(after):
        added = sorted(after[method] - before.get(method, set()))
        dropped = sorted(before.get(method, set()) - after[method])
        if added:
            lines.append(f"- `{method}` adds {', '.join(f'`{x}`' for x in added)}")
        if dropped:
            lines.append(f"- `{method}` drops {', '.join(f'`{x}`' for x in dropped)}")
    old_lines = set(base[ai.COST].splitlines())
    for line in full[ai.COST].splitlines():
        if line not in old_lines and line.startswith("- ") and "(declined " in line:
            lines.append(f"- decline line: {line[2:]}")
    old_bench = json.loads(base[ai.BENCH])["models"]
    for mid in sorted(json.loads(full[ai.BENCH])["models"].keys() - old_bench.keys()):
        lines.append(f"- Artificial Analysis row for `{mid}`")
    for path in others:
        lines.append(f"- `{path}` changed (outside the typed data set)")
    lines += [
        "",
        "To admit it, a maintainer reviews this diff, branches from it, points "
        "`context_policy.baseline_revision` at the data commit (tagged so it stays "
        "reachable), re-binds `.github/security-allowances.json` and merges that PR.",
    ]
    return "\n".join(lines) + "\n"


def _write(path: str, text: str) -> None:
    target = ROOT / path
    if target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")


def split(base_dir: Path, hold: Path, paths: list[str], day: dt.date) -> str | None:
    """Split the working candidate; return the gate's reason, or None when the
    candidate ships whole."""
    for path in paths:
        if path not in ai.INPUTS and not (base_dir / path).exists():
            raise ValueError(f"no base copy of {path}")

    def base_text(path: str) -> str:
        return (base_dir / path).read_text(encoding="utf-8")

    def head_text(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    others = [p for p in paths if p not in ai.INPUTS and head_text(p) != base_text(p)]
    try:
        ai.validate_documents(base_text, head_text, day)
        reason = "files outside the typed data set changed" if others else None
    except (ValueError, KeyError, TypeError) as error:
        reason = str(error) or type(error).__name__
    if reason is None:
        return None

    base = {p: base_text(p) for p in ai.INPUTS}
    full = {p: head_text(p) for p in ai.INPUTS}
    for path in sorted(set(paths) | set(ai.INPUTS)):
        if (ROOT / path).exists():
            (hold / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, hold / path)

    for path in others:
        _write(path, base_text(path))
    bench_text = typed_benchmarks(base[ai.BENCH], full[ai.BENCH])
    avail_text = typed_availability(base[ai.AVAILABILITY], full[ai.AVAILABILITY], base[ai.SELECTOR])
    _write(ai.BENCH, bench_text)
    _write(ai.AVAILABILITY, avail_text)
    bench = ai.benchmarks(base[ai.BENCH], bench_text)
    available = ai.availability(base[ai.AVAILABILITY], avail_text, base[ai.SELECTOR])

    # Provider-direct prices follow the snapshots, which went back to base above.
    prices = merge_catalog.snapshot_price_map(merge_catalog.provider_snapshots(UPDATE))
    seed = typed_selector(base[ai.SELECTOR], full[ai.SELECTOR])
    seed, _, _ = merge_catalog.apply_price_overlay(seed, prices)
    # Letters by rank are taken over the live models. The candidate's were
    # derived over its own field, which a held retirement narrowed, so the
    # typed part derives them again over the models it keeps.
    changes, _ = derive_ratings.plan_changes(seed, json.loads(bench_text)["models"])
    seed = derive_ratings.apply_changes(seed, changes)
    selector, _ = model_prose.apply(seed, bench, day)
    selector = derive_ratings.regenerate_coding_enumeration(selector)
    selector = derive_ratings.regenerate_multimodal_enumeration(selector)
    if avail_text != base[ai.AVAILABILITY]:
        selector = sync_static_availability.rewrite_selector_text(selector, available)
    cost, _, _ = merge_catalog.apply_cost_scale_price_overlay(
        typed_costscale(base[ai.COST], full[ai.COST]), prices
    )
    _write(ai.SELECTOR, selector)
    _write(ai.COST, cost)
    catalog = build_catalog.build_catalog()
    kept = json.loads(base[ai.CATALOG])
    # Unchanged content keeps base's build timestamp, so no-op files stay no-op.
    if {**catalog, "generated_at_utc": kept["generated_at_utc"]} == kept:
        _write(ai.CATALOG, base[ai.CATALOG])
    else:
        _write(ai.CATALOG, build_catalog.render_json(catalog))

    # The typed part is admitted, its markdown as update/render_md.py writes it next.
    rendered = render_md.render(selector)
    ai.validate_documents(base_text, lambda p: rendered if p == ai.MARKDOWN else head_text(p), day)
    REPORT.write_text(held_report(base, full, others, reason), encoding="utf-8")
    return reason


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-dir", type=Path, required=True, help="base copies of the files")
    parser.add_argument("--hold", type=Path, required=True, help="where the full candidate goes")
    parser.add_argument("--paths", nargs="+", required=True, help="every file the refresh commits")
    args = parser.parse_args()
    REPORT.unlink(missing_ok=True)
    try:
        reason = split(args.base_dir, args.hold, args.paths, dt.datetime.now(dt.UTC).date())
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"split_identity: the typed part does not pass the gate: {error}", file=sys.stderr)
        return 1
    if reason is None:
        print("split_identity: the refresh passes the typed boundary as it is")
    else:
        print(f"split_identity: held the rest for review — the gate refused: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
