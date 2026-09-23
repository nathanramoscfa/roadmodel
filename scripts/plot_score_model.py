#!/usr/bin/env python3
"""Draw the /models Score model for one cost tier: what the fit is, and what a
score of "+6.7" actually measures.

    python scripts/plot_score_model.py --tier very-high --out score.png

Reads the same two files the site reads (docs/catalog.json, docs/benchmarks.json),
fits the same line the page fits — AA Intelligence Index against log10(blended
price), one pooled slope across every measured model, one intercept per cost
tier — and plots the chosen tier: each model as a point, the tier's fitted line,
and each model's SCORE as the vertical distance from the point to that line.

Maintainer tool (matplotlib is not a package dependency); the site renders the
same figures, one per cost tier and interactive, in web/components/ScoreCharts.tsx.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "docs" / "catalog.json"
BENCHMARKS = REPO_ROOT / "docs" / "benchmarks.json"

TIER_LABELS = {
    "low": "Low cost",
    "medium": "Medium cost",
    "high": "High cost",
    "very-high": "Very High cost",
}

# Diverging pair for the residual sign (validated: protan ΔE 23.4, normal 33.3
# against the light surface). Sign is ALSO encoded by direction and by the
# printed value, so color is secondary here.
ABOVE = "#0284c7"
BELOW = "#ea580c"
INK = "#1e293b"
MUTED = "#64748b"
GRID = "#e2e8f0"


def blended(model: dict[str, Any]) -> float:
    return (3.0 * float(model["input_price_per_1m"]) + float(model["output_price_per_1m"])) / 4.0


def load() -> list[dict[str, Any]]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    bench = json.loads(BENCHMARKS.read_text(encoding="utf-8"))["models"]
    rows: list[dict[str, Any]] = []
    for m in catalog["models"]:
        row = bench.get(m["id"])
        idx = None
        if row:
            v = row.get("evaluations", {}).get("artificial_analysis_intelligence_index")
            if isinstance(v, (int, float)) and float(v) > 0:
                idx = float(v)
        if idx is None:
            continue
        rows.append(
            {
                "id": m["id"],
                "name": m["name"],
                "tier": m["tier_cost"],
                "price": blended(m),
                "index": idx,
            }
        )
    return rows


def fit(rows: list[dict[str, Any]]) -> tuple[float, dict[str, float], float]:
    """(pooled slope, per-tier intercept, residual sigma) — the ANCOVA fit the
    site uses: one price gradient, each tier centred on its own peers."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["tier"], []).append(r)
    sxx = sxy = 0.0
    for members in groups.values():
        mx = sum(math.log10(r["price"]) for r in members) / len(members)
        my = sum(r["index"] for r in members) / len(members)
        for r in members:
            x = math.log10(r["price"])
            sxx += (x - mx) ** 2
            sxy += (x - mx) * (r["index"] - my)
    slope = sxy / sxx
    intercepts = {
        tier: (sum(r["index"] for r in members) / len(members))
        - slope * (sum(math.log10(r["price"]) for r in members) / len(members))
        for tier, members in groups.items()
    }
    ss_res = sum(
        (r["index"] - (intercepts[r["tier"]] + slope * math.log10(r["price"]))) ** 2 for r in rows
    )
    dof = max(1, len(rows) - len(groups) - 1)
    return slope, intercepts, math.sqrt(ss_res / dof)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", default="very-high", choices=sorted(TIER_LABELS))
    ap.add_argument("--out", required=True, help="PNG path to write.")
    args = ap.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = load()
    slope, intercepts, sigma = fit(rows)
    tier_rows = sorted((r for r in rows if r["tier"] == args.tier), key=lambda r: r["price"])
    if not tier_rows:
        raise SystemExit(f"no measured models in tier {args.tier!r}")
    intercept = intercepts[args.tier]

    fig, ax = plt.subplots(figsize=(11, 6.8), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    xs = [math.log10(r["price"]) for r in tier_rows]
    pad = max(0.12, (max(xs) - min(xs)) * 0.18)
    line_x = [min(xs) - pad, max(xs) + pad]
    line_y = [intercept + slope * x for x in line_x]

    # The band of a tie: +/- one residual sigma around the line.
    ax.fill_between(
        line_x,
        [y - sigma for y in line_y],
        [y + sigma for y in line_y],
        color=MUTED,
        alpha=0.10,
        linewidth=0,
        zorder=1,
    )
    ax.plot(line_x, line_y, color=INK, linewidth=2, zorder=3)

    # Label placement: beside the point (inside the axes), pushed away from
    # the line when two models share a price — Opus 5 / 4.8 / 4.7 all blend to
    # $10.00 — so text never overlaps a mark or falls off the axes.
    placed: list[tuple[float, float]] = []
    x_span = (max(xs) + pad) - (min(xs) - pad)
    right_edge = min(xs) - pad + x_span * 0.7
    for r in tier_rows:
        x = math.log10(r["price"])
        predicted = intercept + slope * x
        score = r["index"] - predicted
        color = ABOVE if score >= 0 else BELOW
        ax.plot([x, x], [predicted, r["index"]], color=color, linewidth=2, zorder=4)
        ax.scatter([x], [r["index"]], s=90, color=color, zorder=5, edgecolor="white", linewidth=1.5)
        ax.scatter([x], [predicted], s=26, color=INK, zorder=5, alpha=0.55)
        side = "right" if x > right_edge else "left"
        direction = 1.0 if score >= 0 else -1.0
        label_y = r["index"]
        while any(abs(py - label_y) < 2.6 for px, py in placed if abs(px - x) < x_span * 0.22):
            label_y += direction * 2.6
        placed.append((x, label_y))
        # A label pushed off its own point gets a hairline back to it.
        displaced = abs(label_y - r["index"]) > 1.5
        ax.annotate(
            f"{r['name']}  {score:+.1f}",
            xy=(x, r["index"]),
            xytext=(x + (x_span * 0.018 if side == "left" else -x_span * 0.018), label_y),
            textcoords="data",
            ha=side,
            va="center",
            fontsize=9,
            color=INK,
            arrowprops=(
                {"arrowstyle": "-", "color": MUTED, "linewidth": 0.8, "alpha": 0.7}
                if displaced
                else None
            ),
            annotation_clip=False,
        )

    # Leave room for the labels themselves.
    label_ys = [y for _x, y in placed]
    lo = min(min(label_ys), min(line_y) - sigma)
    hi = max(max(label_ys), max(line_y) + sigma)
    ax.set_ylim(lo - (hi - lo) * 0.10, hi + (hi - lo) * 0.10)
    ax.set_xlim(line_x[0], line_x[1] + x_span * 0.02)

    ax.set_title(
        f"Score = AA Intelligence Index − what that price predicts, within the "
        f"{TIER_LABELS[args.tier]} tier",
        fontsize=13,
        color=INK,
        pad=16,
        loc="left",
    )
    ax.set_xlabel("Blended price per 1M tokens (3 input : 1 output), log scale", color=MUTED)
    ax.set_ylabel("AA Intelligence Index (0–100)", color=MUTED)
    ticks = sorted({round(x, 2) for x in xs})
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"${10**t:,.2f}" for t in ticks], fontsize=9)
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=MUTED)

    mid_x = (line_x[0] + line_x[1]) / 2
    ax.annotate(
        "the price line: what this tier's models\ntypically score at that price",
        (mid_x, intercept + slope * mid_x),
        textcoords="offset points",
        xytext=(18, -46),
        fontsize=9,
        color=MUTED,
        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 1},
    )
    inside = sum(
        1
        for r in tier_rows
        if abs(r["index"] - (intercept + slope * math.log10(r["price"]))) < sigma
    )
    caption = (
        f"Pooled fit over {len(rows)} measured models: {slope:.1f} index points per 10× price; "
        f"residual σ {sigma:.1f} (shaded). {inside} of {len(tier_rows)} models in this tier sit "
        f"inside that band — their scores are ties, not a ranking.\n"
        f"Source: Artificial Analysis benchmark snapshot; prices from the roadmodel catalog."
    )
    fig.text(0.012, 0.012, caption, fontsize=8.5, color=MUTED, linespacing=1.5)
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(args.out, facecolor="white")
    print(f"wrote {args.out}  (tier={args.tier}, n={len(tier_rows)}, sigma={sigma:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
