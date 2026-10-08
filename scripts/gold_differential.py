#!/usr/bin/env python3
# scripts/gold_differential.py
"""The T1 gold differential, re-runnable: the app's picks against Opus@selector.

Phase 4.5 Task 1 (2026-06-05) measured the gap between the app's /recommend and
what the maintainer gets by handing docs/model-selector.txt to Opus: on the
bundled user-context, the app's pick was quality-equivalent-or-better in 7 of
12 probes, and six defect classes (#185-#190) were filed. This script repeats
that measurement against any soak run (scripts/soak-recommend.ts JSONL):

1. gold: for each probe of scripts/soak_probes.json, Opus reads the bundled
   selector (IDE framing stripped, as the app's prompt strips it) and the
   bundled user-context, and returns its single recommendation as structured
   output. Cached in --gold, so a re-run against a new soak costs nothing.
2. diff: the app's PRIMARY (Balanced, the anonymous default) and QUALITY picks
   against the gold model, by letter in the gold's primary category; the
   gold's classification against the probe's hand labels; platform and effort
   agreement.

Opus runs through Claude Code headless (`claude -p`, no tools) on the
subscription, never an API key.

Usage (repo root, a venv with roadmodel installed):
  python scripts/gold_differential.py --rows /tmp/rm-soak-recommend.jsonl \
      --gold private/gold-differential/gold.json --out private/gold-differential/diff.json
  # --probes creative,planning   limit the gold run to some probes
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from typing import Any

from roadmodel import cost as _cost
from roadmodel import recommend

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import judge_recommend as jr  # noqa: E402

LETTERS = "DCBAS"
T1_PROBES = 12  # the original battery, the like-for-like comparison with T1

GOLD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(jr.scoring.CATEGORIES)},
        "secondary_category": {"type": "string"},
        "complexity": {"type": "string", "enum": list(jr.scoring.COMPLEXITIES)},
        "novel": {"type": "boolean"},
        "model": {"type": "string"},
        "platform": {"type": "string"},
        "effort": {"type": "string"},
        "backup_model": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": [
        "category",
        "complexity",
        "novel",
        "model",
        "platform",
        "effort",
        "backup_model",
        "rationale",
    ],
    "additionalProperties": False,
}

GOLD_INSTRUCTIONS = """\
You are the model selector specified below, run for the person whose user
context follows it. For the task you are given, follow the selection algorithm
and the access selection exactly and return your single recommendation: the
task's primary category, complexity and whether it is novel; the MODEL (its
catalog display name), the PLATFORM (the access method's display name), the
effort or thinking level to set there ("N/A" where the platform has no dial),
the BACKUP model, and a two-sentence rationale. Recommend only; never perform
the task itself.
"""


def system_prompt() -> str:
    selector = (resources.files("roadmodel.data") / "model-selector.txt").read_text(
        encoding="utf-8"
    )
    return (
        f"{GOLD_INSTRUCTIONS}\n<selector>\n{recommend._strip_ide_framing(selector)}\n</selector>\n"
        f"<user-context>\n{jr.bundled_context()}\n</user-context>\n"
    )


def run_gold(
    probes: list[dict[str, Any]], model: str, concurrency: int
) -> dict[str, dict[str, Any]]:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(system_prompt())
    cmd = [
        "claude",
        "-p",
        "--safe-mode",
        "--model",
        model,
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(GOLD_SCHEMA),
        "--system-prompt-file",
        fh.name,
    ]
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    def one(probe: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        for _ in range(2):
            proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv, no shell
                cmd,
                input=f"<task>\n{probe['task']}\n</task>",
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
            if proc.returncode == 0:
                out = json.loads(proc.stdout)
                if out.get("structured_output"):
                    gold: dict[str, Any] = out["structured_output"]
                    gold["_list_cost_usd"] = out.get("total_cost_usd")
                    return probe["id"], gold
        return probe["id"], {"error": (proc.stderr or proc.stdout)[-300:]}

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            return dict(pool.map(one, probes))
    finally:
        os.unlink(fh.name)


def letter(name: str | None, category: str, by_name: dict[str, Any]) -> str:
    return str(by_name.get(name or "", {}).get("tiers", {}).get(category, "-"))


def compare(app: str | None, gold: str, category: str, by_name: dict[str, Any]) -> str:
    """exact | level (same letter in the gold's category) | stronger | weaker | unknown"""
    if app == gold:
        return "exact"
    a, g = letter(app, category, by_name), letter(gold, category, by_name)
    if a not in LETTERS or g not in LETTERS:
        return "unknown"
    return "level" if a == g else ("stronger" if LETTERS.index(a) > LETTERS.index(g) else "weaker")


def diff(
    probes: list[dict[str, Any]],
    rows: dict[str, dict[str, Any]],
    gold: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name = {m["name"]: m for m in _cost._load_catalog()["models"]}
    out: list[dict[str, Any]] = []
    for probe in probes:
        g, row = gold.get(probe["id"]), rows.get(probe["id"])
        if not g or "error" in g or row is None:
            continue
        picks = jr.app_picks(row)
        cat = g["category"]
        primary, quality = picks.get("balanced"), picks.get("quality")
        out.append(
            {
                "probe": probe["id"],
                "gold": {
                    k: g[k]
                    for k in ("category", "complexity", "novel", "model", "platform", "effort")
                },
                "labels_agree": (g["category"], g["complexity"], bool(g["novel"]))
                == (probe["category"], probe["complexity"], probe["novel"]),
                "primary": primary.__dict__ if primary else None,
                "quality": quality.__dict__ if quality else None,
                "primary_vs_gold": compare(primary and primary.model, g["model"], cat, by_name),
                "quality_vs_gold": compare(quality and quality.model, g["model"], cat, by_name),
                "platform_agrees": bool(primary) and primary.platform == g["platform"],
            }
        )
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def count(key: str, values: tuple[str, ...]) -> dict[str, int]:
        return {v: sum(1 for r in rows if r[key] == v) for v in values}

    kinds = ("exact", "level", "stronger", "weaker", "unknown")
    return {
        "probes": len(rows),
        "primary_vs_gold": count("primary_vs_gold", kinds),
        "quality_vs_gold": count("quality_vs_gold", kinds),
        "primary_equivalent_or_better": sum(
            1 for r in rows if r["primary_vs_gold"] in ("exact", "level", "stronger")
        ),
        "quality_equivalent_or_better": sum(
            1 for r in rows if r["quality_vs_gold"] in ("exact", "level", "stronger")
        ),
        "platform_agrees": sum(1 for r in rows if r["platform_agrees"]),
        "gold_matches_hand_labels": sum(1 for r in rows if r["labels_agree"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", required=True, type=pathlib.Path)
    ap.add_argument("--gold", required=True, type=pathlib.Path, help="gold cache (read/write)")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--model", default=jr.JUDGE_MODEL)
    ap.add_argument("--probes", default="", help="comma-separated probe ids (default: all)")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args(argv)

    probes = jr.load_probes()
    if args.probes:
        wanted = set(args.probes.split(","))
        probes = [p for p in probes if p["id"] in wanted]
    gold: dict[str, dict[str, Any]] = (
        json.loads(args.gold.read_text(encoding="utf-8")) if args.gold.exists() else {}
    )
    missing = [p for p in probes if p["id"] not in gold or "error" in gold[p["id"]]]
    if missing:
        print(f"gold: running Opus@selector on {len(missing)} probes", file=sys.stderr)
        gold.update(run_gold(missing, args.model, args.concurrency))
        args.gold.parent.mkdir(parents=True, exist_ok=True)
        args.gold.write_text(
            json.dumps(gold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    rows = jr.judged_rows(jr.load_rows(args.rows))
    table = diff(probes, rows, gold)
    t1 = [r for r in table if r["probe"] in {p["id"] for p in probes[:T1_PROBES]}]
    report = {"all": summary(table), "t1_battery": summary(t1), "rows": table}
    if args.out:
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    for r in table:
        p, q = r["primary"] or {}, r["quality"] or {}
        print(
            f"{r['probe']:22} gold {r['gold']['model']} @ {r['gold']['platform']} · {r['gold']['effort']}"
            f" [{r['gold']['category']}/{r['gold']['complexity']}{'/novel' if r['gold']['novel'] else ''}]"
            f" | app BAL {p.get('model')} ({r['primary_vs_gold']}) QUAL {q.get('model')} ({r['quality_vs_gold']})"
        )
    print(json.dumps({"all": report["all"], "t1_battery": report["t1_battery"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
