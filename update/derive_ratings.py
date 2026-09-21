#!/usr/bin/env python3
"""Derive the measurable S→D ratings from the uniform benchmark layer.

Four of the seven per-model ratings in docs/model-selector.txt have a
single-source, same-scale benchmark behind them in docs/benchmarks.json
(Artificial Analysis, see update/fetch_aa_benchmarks.py):

    tier-coding        ← artificial_analysis_coding_index   (0–100 index)
    tier-agentic       ← terminalbench_v2_1                  (% of tasks)
    tier-long-context  ← lcr  (AA Long Context Reasoning)    (% correct)
    tier-knowledge     ← hle  (Humanity's Last Exam)         (% correct)

This script makes those four letters a FUNCTION of the data instead of an
editorial judgment: the letter is the model's gap to the category leader,
in points on that benchmark's scale, banded as

    S  ≤ 5      frontier-class — the rule the daily cron already applies to S
    A  ≤ 20     strong, near-frontier
    B  ≤ 35     competent
    C  ≤ 50     limited
    D  > 50     far from the frontier

(Equal 15-point widths below S. Narrower middle bands read wrong on HLE,
whose leader is 59 with most of the field at 35–50: a 15-point A band
called GPT-5.4 / Grok 4.6 / Terra "competent" at HLE 43–44.)

A model AA has not measured on a category's benchmark keeps its editorial
letter (the report says so). Planning, multimodal, and speed are never
touched: planning and multimodal have no single-source public benchmark,
and AA's tokens/s is measured on the provider's first-party endpoint at max
effort (gpt-oss-20b reads 181 tok/s there and ~1,000 on Groq, which is what
the catalog's speed letter reflects), so it is the wrong evidence for a
speed class.

    python update/derive_ratings.py --report   # markdown diff, no edits
    python update/derive_ratings.py --write    # apply to docs/model-selector.txt
    python update/derive_ratings.py --check    # exit 1 if the selector disagrees

--write also regenerates the coding S-tier candidate enumeration in the
selector's <selection-algorithm> guardrails (the cron prompt's "Coding
S-tier guardrail" regeneration rule), which must list exactly the models
whose tier-coding is S, cheapest first. Run update/render_md.py and
update/build_catalog.py afterwards, as for any selector edit.

The catalog cron and the benchmark cron both run --write before opening a
PR, and tests/test_derived_ratings.py runs --check, so the committed
selector can never drift from the committed benchmark layer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from selector_re import MODEL_RE  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
BENCHMARKS_PATH = REPO_ROOT / "docs" / "benchmarks.json"
REPORT_PATH = REPO_ROOT / "update" / ".last-ratings-report.md"

# category → (benchmarks.json evaluations key, multiplier to points, label)
CATEGORY_EVIDENCE: dict[str, tuple[str, float, str]] = {
    "coding": ("artificial_analysis_coding_index", 1.0, "AA Coding Index"),
    "agentic": ("terminalbench_v2_1", 100.0, "Terminal-Bench 2.1"),
    "long-context": ("lcr", 100.0, "AA-LCR"),
    "knowledge": ("hle", 100.0, "HLE"),
}

# Gap to the category leader (points) → letter. Checked in order.
BANDS: list[tuple[float, str]] = [(5.0, "S"), (20.0, "A"), (35.0, "B"), (50.0, "C")]
FLOOR_LETTER = "D"

_ID_RE = re.compile(r'\bid="([^"]+)"')
_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_CODING_ENUM_RE = re.compile(
    r"(- For PRIMARY = `coding` at S-tier requirement, the candidate set is\n\s*)"
    r"[^\n]*(;\s*cost tie-breaker favors\n\s*)[^\s]+( when the ratings are equivalent for the prompt\.)"
)


def letter_for_gap(gap: float) -> str:
    for limit, letter in BANDS:
        if gap <= limit:
            return letter
    return FLOOR_LETTER


def points(row: dict[str, Any], category: str) -> float | None:
    key, scale, _ = CATEGORY_EVIDENCE[category]
    v = (row.get("evaluations") or {}).get(key)
    if v is None:
        return None
    return float(v) * scale


def derive(benchmarks: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """{category: {model_id: {value, leader, gap, letter}}} for measured rows."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for category in CATEGORY_EVIDENCE:
        measured = {
            cid: p for cid, row in benchmarks.items() if (p := points(row, category)) is not None
        }
        if not measured:
            out[category] = {}
            continue
        leader = max(measured.values())
        out[category] = {
            cid: {
                "value": v,
                "leader": leader,
                "gap": round(leader - v, 1),
                "letter": letter_for_gap(leader - v),
            }
            for cid, v in measured.items()
        }
    return out


def current_tiers(selector: str) -> dict[str, dict[str, str]]:
    """{model_id: {category: letter}} from <model-options>, plus output price."""
    block = _OPTIONS_RE.search(selector)
    if not block:
        raise ValueError("<model-options> block not found")
    tiers: dict[str, dict[str, str]] = {}
    for m in MODEL_RE.finditer(block.group(1)):
        body = m.group(1)
        mid = _ID_RE.search(body)
        if not mid:
            continue
        attrs = {cat: re.search(rf'tier-{cat}="([SABCD])"', body) for cat in CATEGORY_EVIDENCE}
        entry = {cat: a.group(1) for cat, a in attrs.items() if a}
        price = re.search(r'output-price-per-1m="\$?\s*([\d.]+)"', body)
        entry["_output_price"] = price.group(1) if price else "0"
        entry["_coding_all"] = (re.search(r'tier-coding="([SABCD])"', body) or [None, ""])[1]
        tiers[mid.group(1)] = entry
    return tiers


def plan_changes(
    selector: str, benchmarks: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Return (changes, unmeasured_by_category)."""
    derived = derive(benchmarks)
    current = current_tiers(selector)
    changes: list[dict[str, Any]] = []
    unmeasured: dict[str, list[str]] = {cat: [] for cat in CATEGORY_EVIDENCE}
    for mid, tiers in current.items():
        for cat in CATEGORY_EVIDENCE:
            d = derived[cat].get(mid)
            if d is None:
                unmeasured[cat].append(mid)
                continue
            cur = tiers.get(cat, "")
            if cur != d["letter"]:
                changes.append({"id": mid, "category": cat, "from": cur, "to": d["letter"], **d})
    return changes, unmeasured


def apply_changes(selector: str, changes: list[dict[str, Any]]) -> str:
    def edit(m: re.Match[str]) -> str:
        body = m.group(1)
        mid = _ID_RE.search(body)
        if not mid:
            return m.group(0)
        for ch in changes:
            if ch["id"] != mid.group(1):
                continue
            body = re.sub(
                rf'tier-{ch["category"]}="[SABCD]"',
                f'tier-{ch["category"]}="{ch["to"]}"',
                body,
                count=1,
            )
        return m.group(0).replace(m.group(1), body, 1)

    block = _OPTIONS_RE.search(selector)
    if not block:
        raise ValueError("<model-options> block not found")
    new_block = MODEL_RE.sub(edit, block.group(1))
    return selector[: block.start(1)] + new_block + selector[block.end(1) :]


def regenerate_coding_enumeration(selector: str) -> str:
    """The <selection-algorithm> guardrail must list every tier-coding="S"
    model, cheapest first, with the cheapest as the tie-breaker."""
    tiers = current_tiers(selector)
    s_models = sorted(
        (mid for mid, t in tiers.items() if t.get("_coding_all") == "S"),
        key=lambda mid: (float(tiers[mid]["_output_price"]), mid),
    )
    if not s_models:
        return selector
    listing = ", ".join(s_models)
    cheapest = s_models[0]
    new, n = _CODING_ENUM_RE.subn(rf"\g<1>{listing}\g<2>{cheapest}\g<3>", selector, count=1)
    if n != 1:
        raise ValueError("coding S-tier candidate enumeration not found in <selection-algorithm>")
    return new


def render_report(
    changes: list[dict[str, Any]], unmeasured: dict[str, list[str]], names: dict[str, str]
) -> str:
    lines = ["## Derived ratings (Artificial Analysis layer)", ""]
    if not changes:
        lines.append("No rating changes — the selector already matches the derivation.")
    else:
        lines += [
            f"{len(changes)} rating(s) change. Letter = gap to the category leader, in points: "
            "S ≤ 5, A ≤ 20, B ≤ 35, C ≤ 50, else D.",
            "",
            "| Model | Category | Evidence | Value | Leader | Gap | Was | Now |",
            "|---|---|---|---:|---:|---:|:-:|:-:|",
        ]
        for ch in sorted(changes, key=lambda c: (c["category"], c["gap"])):
            label = CATEGORY_EVIDENCE[ch["category"]][2]
            lines.append(
                f"| {names.get(ch['id'], ch['id'])} | {ch['category']} | {label} | "
                f"{ch['value']:.1f} | {ch['leader']:.1f} | {ch['gap']:.1f} | {ch['from']} | **{ch['to']}** |"
            )
    lines += ["", "Kept editorial (no AA measurement on the category's benchmark):", ""]
    for cat, ids in unmeasured.items():
        if ids:
            lines.append(f"- **{cat}**: " + ", ".join(names.get(i, i) for i in ids))
    lines.append(
        "- **planning, multimodal, speed**: always editorial (no single-source benchmark; "
        "AA tokens/s is first-party-endpoint-specific)."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true", help="print the diff as markdown")
    mode.add_argument("--write", action="store_true", help="apply to docs/model-selector.txt")
    mode.add_argument("--check", action="store_true", help="exit 1 if the selector disagrees")
    args = parser.parse_args()

    selector = SELECTOR_PATH.read_text()
    benchmarks = json.loads(BENCHMARKS_PATH.read_text())["models"]
    names = {cid: row.get("aa_name") or cid for cid, row in benchmarks.items()}
    catalog_path = REPO_ROOT / "docs" / "catalog.json"
    if catalog_path.exists():
        names.update({m["id"]: m["name"] for m in json.loads(catalog_path.read_text())["models"]})

    changes, unmeasured = plan_changes(selector, benchmarks)
    report = render_report(changes, unmeasured, names)

    if args.check:
        if changes:
            sys.stderr.write(report)
            sys.stderr.write(
                "\ndocs/model-selector.txt disagrees with docs/benchmarks.json.\n"
                "Regenerate with: python update/derive_ratings.py --write && "
                "python update/render_md.py && python update/build_catalog.py\n"
            )
            return 1
        print("selector ratings match the derivation")
        return 0

    if args.report:
        print(report)
        REPORT_PATH.write_text(report)
        return 0

    updated = apply_changes(selector, changes)
    updated = regenerate_coding_enumeration(updated)
    if updated != selector:
        SELECTOR_PATH.write_text(updated)
        print(f"Applied {len(changes)} rating change(s) to {SELECTOR_PATH.relative_to(REPO_ROOT)}")
    else:
        print("No changes.")
    REPORT_PATH.write_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
