#!/usr/bin/env python3
# scripts/eval_keyless_agreement.py
"""Keyless agreement eval: do the scoring core's picks match the engine's?

For each probe of the 12-probe battery (scripts/eval_recommend_engines.py
PROBES):

1. the engine ladder runs ``--runs`` times (default 3) through the deployed
   service's ``/v1/recommend/ladder`` on the default engine, and each rung's
   modal model is taken (a tie goes to the earliest run's model);
2. the scorer runs once with the probe's hand labels
   (scripts/keyless_probe_labels.json): through the deployed ``/v1/score``, or
   in-process through the same service app with ``--scorer local`` (before the
   endpoint is deployed);
3. each rung agrees when the scorer's model is the engine's modal model.

Both sides get the same funding profile, ``EVAL_CONTEXT``: an API key at every
pay-per-token provider. It puts every catalog model in the pool, which gives
the same picks as an empty profile on every row of the ladder table (the
keyless visitor's pool), and it keeps the engine on that same pool: the service
reads an empty profile as the bundled operator-like template, so an empty
profile would compare two different pools.

The bar: ``agree`` >= 27 of 36 rungs AND ``under_tier`` == 0, where a Quality
rung is under tier when its model's rating in the probe's category is below the
selector's Step 3 minimum for the probe's complexity (Low -> B, Medium -> A,
High -> S).

Writes docs/keyless-eval.json (no token, key or probe text) and prints a
summary. The engine runs are real spend on the operator's key: GPT-6 Luna, a
cent or less per ladder.

Usage (repo root, verify venv):
  scripts/with-prod-secrets.sh python scripts/eval_keyless_agreement.py --scorer local
  scripts/with-prod-secrets.sh python scripts/eval_keyless_agreement.py   # scorer via the service
  scripts/with-prod-secrets.sh python scripts/eval_keyless_agreement.py --check-scorer
      # free: re-run only the deployed scorer and compare it with the record
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from eval_recommend_engines import PROBES  # noqa: E402

from roadmodel import cost  # noqa: E402

SERVICE = "https://roadmodel-api.vercel.app"
LABELS = REPO / "scripts" / "keyless_probe_labels.json"
OUT = REPO / "docs" / "keyless-eval.json"
ENGINES = REPO / "service" / "app" / "engines.json"
TIERS = ("quality", "balanced", "cost")
BAR_AGREE = 27
# The selector's <selection-algorithm> Step 3: the minimum rating in the
# PRIMARY category for each overall complexity.
STEP3_MINIMUM = {"low": "B", "medium": "A", "high": "S"}
LETTERS = "DCBAS"
# An API key at every pay-per-token provider in the catalog (see the module
# docstring for why the profile is not empty).
EVAL_CONTEXT: dict[str, Any] = {
    "api_providers": [
        "anthropic",
        "deepseek",
        "google",
        "groq",
        "mistral",
        "openai",
        "openrouter",
        "xai",
        "zai",
    ],
    "consumption_headroom": "capped",
}


def _post(url: str, path: str, body: dict[str, Any], token: str, timeout: int) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise SystemExit("the service URL must be https://")
    req = urllib.request.Request(  # noqa: S310 - https only, checked above
        f"{url.rstrip('/')}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    # https only, checked above.
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        data: dict[str, Any] = json.load(resp)
    return data


def _get(url: str, path: str) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise SystemExit("the service URL must be https://")
    # https only, checked above.
    with urllib.request.urlopen(f"{url.rstrip('/')}{path}", timeout=30) as resp:  # noqa: S310  # nosec B310
        data: dict[str, Any] = json.load(resp)
    return data


def _engine_cost(hint: str | None, usage: dict[str, Any] | None) -> float | None:
    """The call's cost at the engine's catalog prices (the formula
    eval_recommend_engines.py bills by)."""
    if not hint or not usage:
        return None
    engines = {e["hint"]: e for e in json.loads(ENGINES.read_text())["engines"]}
    spec = engines.get(hint)
    models = {m["id"]: m for m in cost._load_catalog()["models"]}
    m = models.get(spec["catalog_id"]) if spec else None
    if m is None:
        return None
    p_in = m["input_price_per_1m"]
    p_cache = m.get("cache_read_per_1m") or p_in * 0.1
    cached = usage.get("cached_input_tokens", 0) or 0
    writes = usage.get("cache_write_tokens", 0) or 0
    uncached = (usage.get("input_tokens", 0) or 0) - cached - writes
    return (
        uncached * p_in
        + cached * p_cache
        + writes * p_in * 1.25
        + (usage.get("output_tokens", 0) or 0) * m["output_price_per_1m"]
    ) / 1_000_000


def engine_run(url: str, task: str, token: str, attempts: int = 3) -> dict[str, Any]:
    """One engine ladder through the service: each tier's model, the engine
    that answered, its classification and cost. Retries a failed call."""
    last = ""
    for _ in range(attempts):
        try:
            r = _post(
                url,
                "/v1/recommend/ladder",
                {"task_description": task, "context": EVAL_CONTEXT},
                token,
                timeout=180,
            )
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            time.sleep(2)
            continue
        except Exception as e:  # noqa: BLE001 - record every failure mode, then retry
            last = type(e).__name__
            time.sleep(2)
            continue
        picks = r.get("picks") or {}
        return {
            "models": {t: (picks.get(t) or {}).get("model") for t in TIERS},
            "engine": r.get("engine"),
            "classification": (r.get("guard") or {}).get("classification"),
            "cost_usd": _engine_cost(r.get("engine"), r.get("usage")),
        }
    return {"error": last}


def score_body(labels: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": labels["category"],
        "complexity": labels["complexity"],
        "novel": labels["novel"],
        "budget_priority": "balanced",
        **EVAL_CONTEXT,
    }


def _local_client() -> Any:
    """The service app in-process: the endpoint's own code, on this tree's
    package. The bearer is a throwaway set for this process only."""
    sys.path.insert(0, str(REPO / "service"))
    # A throwaway bearer for the in-process app only; it guards nothing.
    os.environ["ROADMODEL_INTERNAL_TOKEN"] = "local-eval"  # noqa: S105  # nosec B105
    from app.main import app  # type: ignore[import-not-found]
    from fastapi.testclient import TestClient

    return TestClient(app, headers={"Authorization": "Bearer local-eval"})


def scorer_run(body: dict[str, Any], *, url: str, token: str, local: Any) -> dict[str, str]:
    """The scorer's model name per tier."""
    if local is not None:
        resp = local.post("/v1/score", json=body)
        resp.raise_for_status()
        data = resp.json()
    else:
        data = _post(url, "/v1/score", body, token, timeout=60)
    return {r["priority"]: r["model_name"] for r in data["rungs"]}


def modal(values: list[str | None]) -> str | None:
    """The most frequent value; a tie goes to the earliest run's."""
    present = [v for v in values if v]
    if not present:
        return None
    counts = Counter(present)
    top = max(counts.values())
    return next(v for v in present if counts[v] == top)


def under_tier(model_name: str, labels: dict[str, Any], by_name: dict[str, Any]) -> bool:
    m = by_name.get(model_name.lower())
    letter = str(((m or {}).get("tiers") or {}).get(labels["category"], "D")).upper()
    return LETTERS.find(letter) < LETTERS.find(STEP3_MINIMUM[labels["complexity"]])


def _letter(model_name: str, category: str, by_name: dict[str, Any]) -> str:
    m = by_name.get(model_name.lower())
    return str(((m or {}).get("tiers") or {}).get(category, "?")).upper()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--service", default=SERVICE, help="the deployed service (https)")
    ap.add_argument("--runs", type=int, default=3, help="engine ladders per probe")
    ap.add_argument(
        "--scorer",
        choices=("service", "local"),
        default="service",
        help="run /v1/score on the deployed service or in-process (same code)",
    )
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument(
        "--check-scorer",
        action="store_true",
        help="no engine runs: re-score every probe on the deployed service and compare "
        "with the record in --out",
    )
    args = ap.parse_args()

    token = os.environ.get("ROADMODEL_INTERNAL_TOKEN", "")
    if not token and not (args.scorer == "local" and args.check_scorer):
        raise SystemExit("needs ROADMODEL_INTERNAL_TOKEN (run under scripts/with-prod-secrets.sh)")
    labels = {row["probe_id"]: row for row in json.loads(LABELS.read_text())["labels"]}
    missing = [p["id"] for p in PROBES if p["id"] not in labels]
    if missing:
        raise SystemExit(f"no labels for: {', '.join(missing)}")
    # Read before _local_client, which sets its own in-process bearer.
    local = _local_client() if args.scorer == "local" else None

    if args.check_scorer:
        record = json.loads(pathlib.Path(args.out).read_text())
        diffs = 0
        for row in record["probes"]:
            got = scorer_run(score_body(row["labels"]), url=args.service, token=token, local=local)
            for rung in row["rungs"]:
                same = got[rung["priority"]] == rung["scorer"]
                diffs += not same
                print(
                    f"{row['probe_id']:16} {rung['priority']:8} record={rung['scorer']:18} "
                    f"now={got[rung['priority']]:18} {'ok' if same else 'DIFFERS'}"
                )
        print(f"\n{diffs} rung(s) differ from the record")
        return 1 if diffs else 0

    health = _get(args.service, "/healthz")
    by_name = {m["name"].lower(): m for m in cost._load_catalog()["models"]}
    import roadmodel

    if args.scorer == "local" and health.get("roadmodel_version") != roadmodel.__version__:
        print(
            f"WARNING: the service runs roadmodel {health.get('roadmodel_version')}, "
            f"this tree {roadmodel.__version__}; the record must be taken against production's.",
            file=sys.stderr,
        )

    rows: list[dict[str, Any]] = []
    spend = 0.0
    engines: Counter[str] = Counter()
    for probe in PROBES:
        lab = labels[probe["id"]]
        runs = [engine_run(args.service, probe["task"], token) for _ in range(args.runs)]
        for r in runs:
            spend += r.get("cost_usd") or 0.0
            if r.get("engine"):
                engines[r["engine"]] += 1
        scored = scorer_run(score_body(lab), url=args.service, token=token, local=local)
        rungs = []
        for tier in TIERS:
            engine_modal = modal([(r.get("models") or {}).get(tier) for r in runs])
            rungs.append(
                {
                    "priority": tier,
                    "engine_runs": [(r.get("models") or {}).get(tier) for r in runs],
                    "engine_modal": engine_modal,
                    "scorer": scored[tier],
                    "agree": engine_modal is not None
                    and engine_modal.lower() == scored[tier].lower(),
                }
            )
        quality = scored["quality"]
        rows.append(
            {
                "probe_id": probe["id"],
                "labels": {k: lab[k] for k in ("category", "complexity", "novel")},
                "engine_classifications": [r.get("classification") for r in runs],
                "engine_errors": [r["error"] for r in runs if "error" in r],
                "quality_rating": _letter(quality, lab["category"], by_name),
                "quality_minimum": STEP3_MINIMUM[lab["complexity"]],
                "under_tier": under_tier(quality, lab, by_name),
                "rungs": rungs,
            }
        )
        agreed = sum(r["agree"] for r in rungs)
        print(f"{probe['id']:16} {agreed}/3  engine says {rows[-1]['engine_classifications']}")

    agree = sum(r["agree"] for row in rows for r in row["rungs"])
    total = sum(len(row["rungs"]) for row in rows)
    under = sum(row["under_tier"] for row in rows)
    record = {
        "_comment": (
            "docs/keyless-eval.json: generated by scripts/eval_keyless_agreement.py; do not "
            "hand-edit. Per probe of the 12-probe battery: the engine ladder's modal model per "
            "rung over the runs, the scoring core's pick for the probe's hand labels "
            "(scripts/keyless_probe_labels.json), both on the same funding profile. The bar: "
            f"agree >= {BAR_AGREE} of 36 and under_tier == 0. tests/test_keyless_eval_shape.py "
            "pins it."
        ),
        "evaluated_on": datetime.date.today().isoformat(),
        "roadmodel_version": health.get("roadmodel_version"),
        "scorer_via": args.scorer,
        "engines": dict(engines),
        "runs_per_probe": args.runs,
        "context": EVAL_CONTEXT,
        "engine_spend_usd": round(spend, 4),
        "agree": agree,
        "total": total,
        "under_tier": under,
        "probes": rows,
    }
    pathlib.Path(args.out).write_text(json.dumps(record, indent=2) + "\n")

    print(f"\n{'probe':16} {'labels':26} " + " ".join(f"{t:>30}" for t in TIERS))
    for row in rows:
        lab = row["labels"]
        key = f"{lab['category']}/{lab['complexity']}" + ("/novel" if lab["novel"] else "")
        cells = [
            f"{'=' if r['agree'] else 'x'} {r['scorer'][:13]:13}|{(r['engine_modal'] or '-')[:13]:13}"
            for r in row["rungs"]
        ]
        print(f"{row['probe_id']:16} {key:26} " + " ".join(f"{c:>30}" for c in cells))
    print(
        f"\nagree {agree}/{total} (bar {BAR_AGREE}) · under_tier {under} (bar 0) · "
        f"engine spend ${spend:.4f} · engines {dict(engines)}"
    )
    print(f"Record: {args.out}")
    return 0 if agree >= BAR_AGREE and under == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
