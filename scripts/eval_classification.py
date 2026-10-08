#!/usr/bin/env python3
# scripts/eval_classification.py
"""How the recommender engine classifies the soak's probes, before a release.

The picks come from the ladder table; the one judgement left to the engine is
the task's classification (category / complexity / novel), which picks the
table's row. This runs the production default engine (service/app/engines.json)
through the package's own ladder path, ``recommend_structured_ladder``, on the
bundled user-context (the anonymous lane's), ``--runs`` times per probe of
scripts/soak_probes.json, and reads the row each run landed on
(``guard.classification``). Per probe:

- agrees: the modal row is the gold label's or a listed alternative's;
- under: some run read a lower complexity than every accepted reading (the
  error that demotes the picks, B2);
- stable: every run landed on the same row (B7's cause).

It reads the package from this checkout (src/), so it measures a prompt or
parser change before it ships. The engine calls are real spend on the key in
OPENAI_API_KEY (GPT-6 Luna: under a cent a call; 33 probes x 3 runs is about
$0.65 cold).

Usage (repo root, verify venv):
  OPENAI_API_KEY=... python scripts/eval_classification.py [--runs 3] [--probes a,b] [--out f]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from roadmodel import scoring, usage  # noqa: E402
from roadmodel.config import PROVIDER_KEY_ENV, Config  # noqa: E402
from roadmodel.recommend import recommend_structured_ladder  # noqa: E402

PROBES_FILE = REPO / "scripts" / "soak_probes.json"
ENGINES_FILE = REPO / "service" / "app" / "engines.json"
COMPLEXITY_ORDER = {c: i for i, c in enumerate(scoring.COMPLEXITIES)}


def default_engine() -> dict[str, Any]:
    reg = json.loads(ENGINES_FILE.read_text(encoding="utf-8"))
    engine: dict[str, Any] = next(e for e in reg["engines"] if e["hint"] == reg["default"])
    return engine


def accepted_keys(probe: dict[str, Any]) -> list[str]:
    readings = [probe, *probe.get("alternatives", [])]
    return [scoring.table_key(r["category"], r["complexity"], bool(r["novel"])) for r in readings]


def complexity_of(key: str) -> str:
    return key.split("/")[1]


def score_probe(probe: dict[str, Any], keys: list[str | None]) -> dict[str, Any]:
    ok = [k for k in keys if k]
    accepted = accepted_keys(probe)
    modal = Counter(ok).most_common(1)[0][0] if ok else None
    floor = min(COMPLEXITY_ORDER[complexity_of(k)] for k in accepted)
    return {
        "probe": probe["id"],
        "label": accepted[0],
        "runs": keys,
        "modal": modal,
        "agrees": modal in accepted,
        "under": any(COMPLEXITY_ORDER[complexity_of(k)] < floor for k in ok),
        "stable": len(set(keys)) == 1 and None not in keys,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--probes", default="", help="comma-separated probe ids (default: all)")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--out", type=pathlib.Path)
    args = ap.parse_args(argv)

    engine = default_engine()
    key = os.environ.get(PROVIDER_KEY_ENV.get(engine["provider"], ""), "")
    if not key:
        print(
            f"set {PROVIDER_KEY_ENV.get(engine['provider'])} for {engine['hint']}", file=sys.stderr
        )
        return 2
    probes: list[dict[str, Any]] = json.loads(PROBES_FILE.read_text(encoding="utf-8"))["probes"]
    if args.probes:
        wanted = set(args.probes.split(","))
        probes = [p for p in probes if p["id"] in wanted]

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(
            (resources.files("roadmodel.data") / "user-context.example.md").read_text(
                encoding="utf-8"
            )
        )
    cfg = Config(
        provider=engine["provider"],
        model=engine["model"],
        api_key=key,
        user_context_path=pathlib.Path(fh.name),
    )

    def classify(probe: dict[str, Any]) -> str | None:
        try:
            result = recommend_structured_ladder(
                probe["task"],
                cfg,
                user_context_text=None,
                max_output_tokens=engine["ladder_max_output_tokens"],
                thinking_budget=engine["thinking_budget"],
                temperature=engine["temperature"],
            )
        except Exception as exc:  # noqa: BLE001 - a failed run reads as no classification
            print(f"{probe['id']}: {type(exc).__name__}: {str(exc)[:120]}", file=sys.stderr)
            return None
        cls = (result.get("guard") or {}).get("classification")
        return str(cls) if cls else None

    usage.reset()
    jobs = [p for p in probes for _ in range(args.runs)]
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            results = list(pool.map(classify, jobs))
    finally:
        os.unlink(fh.name)
    by_probe: dict[str, list[str | None]] = {}
    for probe, cls in zip(jobs, results, strict=True):
        by_probe.setdefault(probe["id"], []).append(cls)
    rows = [score_probe(p, by_probe[p["id"]]) for p in probes]

    for r in rows:
        flags = " ".join(
            f
            for f, on in (("AGREE", r["agrees"]), ("UNDER", r["under"]), ("STABLE", r["stable"]))
            if on
        )
        print(
            f"{r['probe']:22} label {r['label']:22} runs {', '.join(map(str, r['runs']))}  {flags}"
        )
    summary = {
        "engine": engine["hint"],
        "probes": len(rows),
        "runs": args.runs,
        "agree": sum(r["agrees"] for r in rows),
        "under": sum(r["under"] for r in rows),
        "stable": sum(r["stable"] for r in rows),
        "calls": len(jobs),
    }
    print(json.dumps(summary))
    if args.out:
        args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
