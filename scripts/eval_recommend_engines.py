#!/usr/bin/env python3
"""Differential engine eval for the roadmodel recommender.

Runs the 12-probe battery (from scripts/diag-recommend-capture.ts) through the
package's recommend_structured_ladder for a CONFIGURABLE list of engine models,
then diffs each engine against a baseline on: model-pick agreement (per tier),
ladder health, structured-field completeness, and deterministic instruction-
adherence checks (the durable T1 finding — the pick is usually fine; the gap is
adherence AROUND the pick). Emits a markdown report + raw JSONL.

Scope note: this compares ENGINE behavior on the ANON path (bundled user-context,
user_context_text=None), isolating the model from funding personalization — the
same basis as the T1 gold report and the high-volume public path.

Keys: reads {PROVIDER}_API_KEY from the environment. Only engines whose key is
present are run; others are skipped and reported as such. So GPT-5 mini requires
OPENAI_API_KEY, Claude Haiku requires ANTHROPIC_API_KEY.

Usage (from repo root, in the verify venv):
  GOOGLE_API_KEY=... [OPENAI_API_KEY=...] python scripts/eval_recommend_engines.py
  # optional: --engines gemini-2.5-pro,gpt-5-mini  --out /tmp/eval  --probes 6
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from roadmodel.config import Config  # noqa: E402
from roadmodel.recommend import recommend_structured_ladder  # noqa: E402

# The 12-probe battery — kept in sync with scripts/diag-recommend-capture.ts.
PROBES: list[dict[str, str]] = [
    {"id": "creative", "task": "Write a short story about a robot learning to garden."},
    {
        "id": "coding-cli",
        "task": "Help me build a small Python CLI that fetches weather data and caches it locally.",
    },
    {
        "id": "planning",
        "task": "Draft a one-week study plan for a graduate-level linear algebra exam.",
    },
    {
        "id": "data-analysis",
        "task": "Analyze a 2 GB CSV of retail sales and surface seasonal demand trends with charts.",
    },
    {
        "id": "legacy-refactor",
        "task": "Refactor a 50-file legacy Django monolith into modular services with tests.",
    },
    {
        "id": "math-proof",
        "task": "Prove that the square root of 2 is irrational, step by step, rigorously.",
    },
    {
        "id": "vision-ocr",
        "task": "Extract line-item tables from a scanned PDF invoice image and output CSV.",
    },
    {"id": "ambiguous", "task": "help"},
    {"id": "non-english", "task": "Écris un poème sur la mer, en français, avec des rimes riches."},
    {
        "id": "cost-bulk",
        "task": "Cheapest capable model to classify 10,000 support tickets by sentiment; accuracy matters.",
    },
    {
        "id": "fenced-json",
        "task": 'Review this config and flag risks:\n```json\n{"retries":5,"timeout_ms":0}\n```',
    },
    {
        "id": "agentic-tooluse",
        "task": "Build an autonomous agent that monitors my inbox, drafts replies, and books meetings via API.",
    },
]


@dataclass
class Engine:
    """One candidate engine. `api_model` is the ACTUAL provider API id (catalog
    ids like 'gemini-3-pro' are NOT the API id — the API id is
    'gemini-3-pro-preview'). `ga` flags production-readiness."""

    key: str  # short label
    provider: str  # "google" | "openai" | "anthropic"
    api_model: str
    thinking_budget: int | None = None
    max_output_tokens: int | None = 3072
    temperature: float | None = 0.0
    ga: bool = True
    note: str = ""


# Callable, verified (via the models list + smoke test). thinking params mirror
# how each surface behaves: 2.5 uses numeric thinking_budget; 3.x retired it
# (discrete levels) so pass None. Gemini 3 Pro/Flash previews are flagged.
ENGINES: list[Engine] = [
    Engine(
        "gemini-2.5-pro",
        "google",
        "gemini-2.5-pro",
        thinking_budget=512,
        ga=True,
        note="current frontier (baseline)",
    ),
    Engine(
        "gemini-2.5-flash",
        "google",
        "gemini-2.5-flash",
        thinking_budget=0,
        ga=True,
        note="current anon",
    ),
    Engine(
        "gemini-2.5-flash-lite",
        "google",
        "gemini-2.5-flash-lite",
        thinking_budget=0,
        ga=True,
        note="cheaper anon candidate",
    ),
    Engine(
        "gemini-3.1-pro-preview",
        "google",
        "gemini-3.1-pro-preview",
        thinking_budget=None,
        ga=False,
        note="PREVIEW; ~2.5x slower",
    ),
    Engine(
        "gemini-3.5-flash",
        "google",
        "gemini-3.5-flash",
        thinking_budget=None,
        ga=True,
        note="GA stronger flash",
    ),
    Engine(
        "gemini-3-pro-preview",
        "google",
        "gemini-3-pro-preview",
        thinking_budget=None,
        ga=False,
        note="PREVIEW; 404'd in smoke",
    ),
    # Requires OPENAI_API_KEY — the anon recommendation from the review.
    Engine(
        "gpt-5-mini",
        "openai",
        "gpt-5-mini",
        thinking_budget=None,
        ga=True,
        note="anon recommendation; needs OPENAI_API_KEY",
    ),
    Engine(
        "gpt-5-nano",
        "openai",
        "gpt-5-nano",
        thinking_budget=None,
        ga=True,
        note="cheapest; needs OPENAI_API_KEY",
    ),
]

BASELINE = "gemini-2.5-pro"
UC_ANON = REPO / "docs" / "user-context.example.md"

_COST_DEMOTION = re.compile(
    r"\b(cheaper|less expensive|lower cost|to save (?:cost|money)|budget[- ]friendly)\b", re.I
)


def _key_for(provider: str) -> str | None:
    return os.environ.get(f"{provider.upper()}_API_KEY") or None


def _run_one(eng: Engine, prompt: str) -> dict[str, Any]:
    key = _key_for(eng.provider)
    if not key:
        return {"skipped": f"no {eng.provider.upper()}_API_KEY"}
    cfg = Config(provider=eng.provider, model=eng.api_model, api_key=key, user_context_path=UC_ANON)
    t0 = time.time()
    try:
        r = recommend_structured_ladder(
            prompt,
            cfg,
            user_context_text=None,
            max_output_tokens=eng.max_output_tokens,
            thinking_budget=eng.thinking_budget,
            temperature=eng.temperature,
        )
    except Exception as e:  # noqa: BLE001 - record every failure mode
        return {
            "error": f"{type(e).__name__}: {str(e)[:160]}",
            "latency_s": round(time.time() - t0, 1),
        }
    latency = round(time.time() - t0, 1)
    picks = r.get("picks", {}) or {}
    guard = r.get("guard", {}) or {}
    out = {"latency_s": latency, "healthy": bool(guard.get("healthy")), "picks": {}, "checks": {}}
    all_fields = True
    task_leak = False
    cost_demotion = False
    sections_ok = True
    for tier in ("cost", "balanced", "quality"):
        p = picks.get(tier) or {}
        settings = p.get("settings") or {}
        rat = p.get("rationale") or ""
        out["picks"][tier] = {
            "model": p.get("model"),
            "platform": p.get("platform"),
            "settings": settings,
            "backup": (
                p.get("backup")
                if isinstance(p.get("backup"), str)
                else (p.get("backup") or {}).get("model")
                if isinstance(p.get("backup"), dict)
                else p.get("backup")
            ),
        }
        if not (
            p.get("model") and p.get("platform") and settings and rat and p.get("conversation")
        ):
            all_fields = False
        if not p.get("rationale_sections"):
            sections_ok = False
        if "```" in rat or len(rat) > 1100:
            task_leak = True
        # Cost language is LEGITIMATE in the Cost pick's rationale; it is only a
        # defect (quality-demotion against the quality-first directive) in the
        # Balanced/Quality tiers. Flag it there only.
        if tier in ("balanced", "quality") and _COST_DEMOTION.search(rat):
            cost_demotion = True
    out["checks"] = {
        "all_fields": all_fields,
        "sections_parse": sections_ok,
        "no_task_leak": not task_leak,
        "no_cost_demotion": not cost_demotion,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--engines", default="", help="comma list of engine keys; default = all callable"
    )
    ap.add_argument("--probes", type=int, default=0, help="limit to first N probes (0 = all)")
    ap.add_argument(
        "--out",
        default="/tmp/rm-engine-eval",  # noqa: S108 - dev eval artifact, path is overridable
        help="output path prefix",
    )
    args = ap.parse_args()

    selected = [e for e in ENGINES if (not args.engines or e.key in args.engines.split(","))]
    probes = PROBES[: args.probes] if args.probes else PROBES

    rows: list[dict[str, Any]] = []
    jsonl = pathlib.Path(f"{args.out}.jsonl").open("w")
    for eng in selected:
        for probe in probes:
            res = _run_one(eng, probe["task"])
            rec = {"engine": eng.key, "ga": eng.ga, "probe": probe["id"], **res}
            rows.append(rec)
            jsonl.write(json.dumps(rec) + "\n")
            jsonl.flush()
            status = (
                res.get("skipped")
                or res.get("error")
                or f"{res['latency_s']}s Q={res['picks']['quality']['model']}"
            )
            print(f"  {eng.key:24s} {probe['id']:16s} {status}", flush=True)
    jsonl.close()

    # Baseline picks per probe for agreement.
    base = {r["probe"]: r for r in rows if r["engine"] == BASELINE and "picks" in r}

    def agg(eng_key: str) -> dict[str, Any]:
        er = [r for r in rows if r["engine"] == eng_key]
        ran = [r for r in er if "picks" in r]
        if not ran:
            reason = er[0].get("skipped") or er[0].get("error") or "no runs"
            return {"ran": 0, "reason": reason}
        n = len(ran)

        def rate(fn):
            return sum(1 for r in ran if fn(r)) / n

        exact = []
        for r in ran:
            b = base.get(r["probe"])
            if not b:
                continue
            m = sum(
                1
                for t in ("cost", "balanced", "quality")
                if r["picks"][t]["model"] == b["picks"][t]["model"]
            )
            exact.append(m / 3)
        return {
            "ran": n,
            "mean_latency_s": round(sum(r["latency_s"] for r in ran) / n, 1),
            "healthy": round(rate(lambda r: r["healthy"]), 2),
            "all_fields": round(rate(lambda r: r["checks"]["all_fields"]), 2),
            "sections_parse": round(rate(lambda r: r["checks"]["sections_parse"]), 2),
            "no_task_leak": round(rate(lambda r: r["checks"]["no_task_leak"]), 2),
            "no_cost_demotion": round(rate(lambda r: r["checks"]["no_cost_demotion"]), 2),
            "pick_agreement_vs_baseline": round(sum(exact) / len(exact), 2) if exact else None,
        }

    md = [
        "# Recommender engine differential eval\n",
        f"Probes: {len(probes)} · baseline: `{BASELINE}` · anon context (user_context_text=None)\n",
    ]
    md.append("## Summary\n")
    md.append(
        "| engine | GA | ran | lat(s) | healthy | fields | sections | no-leak | no-demote | pick-agree vs base |"
    )
    md.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for eng in selected:
        a = agg(eng.key)
        ga = "GA" if eng.ga else "preview"
        if a["ran"] == 0:
            md.append(f"| `{eng.key}` | {ga} | 0 | — | — | — | — | — | — | _{a['reason']}_ |")
        else:
            md.append(
                f"| `{eng.key}` | {ga} | {a['ran']} | {a['mean_latency_s']} | {a['healthy']} | {a['all_fields']} | {a['sections_parse']} | {a['no_task_leak']} | {a['no_cost_demotion']} | {a['pick_agreement_vs_baseline']} |"
            )
    md.append("\n## Per-probe Quality pick (model) by engine\n")
    ran_engines = [e for e in selected if agg(e.key)["ran"] > 0]
    md.append("| probe | " + " | ".join(f"`{e.key}`" for e in ran_engines) + " |")
    md.append("|---|" + "---|" * len(ran_engines))
    for probe in probes:
        cells = []
        for e in ran_engines:
            r = next(
                (
                    x
                    for x in rows
                    if x["engine"] == e.key and x["probe"] == probe["id"] and "picks" in x
                ),
                None,
            )
            cells.append(r["picks"]["quality"]["model"] if r else "—")
        md.append(f"| {probe['id']} | " + " | ".join(str(c) for c in cells) + " |")

    report = pathlib.Path(f"{args.out}.md")
    report.write_text("\n".join(md) + "\n")
    print(f"\nReport: {report}\nRaw:    {args.out}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
