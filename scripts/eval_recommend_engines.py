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

Keys: reads each provider's key env (roadmodel.config.PROVIDER_KEY_ENV — e.g.
OPENAI_API_KEY, DEEPSEEK_API_KEY, GROQ_API_KEY). Only engines whose key is
present are run; others are skipped and reported as such. `ollama` engines need
no key — they run whenever a local Ollama server answers on OLLAMA_HOST /
localhost:11434 (and the named model is pulled). NOTE the recommender prompt is
~55k tokens: a local model needs a >=64k context window or the instructions are
silently truncated away.

Usage (from repo root, in the verify venv):
  GOOGLE_API_KEY=... [OPENAI_API_KEY=...] python scripts/eval_recommend_engines.py
  # optional: --engines gemini-2.5-pro,gpt-5-mini  --out /tmp/eval  --probes 6
  # add an ad-hoc engine without editing ENGINES: --extra provider:model[:budget]
  #   e.g. --extra ollama:gemma3:12b:0  --extra deepseek:deepseek-flash:0
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from roadmodel import cost, usage  # noqa: E402
from roadmodel.config import PROVIDER_KEY_ENV, Config  # noqa: E402
from roadmodel.providers.registry import COMPATIBLE_PROVIDERS, OLLAMA_PLACEHOLDER_KEY  # noqa: E402
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
    provider: str  # any roadmodel.config.ProviderName (native or OpenAI-compatible)
    api_model: str
    thinking_budget: int | None = None
    max_output_tokens: int | None = 3072
    temperature: float | None = 0.0
    ga: bool = True
    note: str = ""
    # The docs/catalog.json id whose prices the report bills the run at;
    # defaults to the key (most engine keys ARE catalog ids).
    catalog_id: str | None = None


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
        thinking_budget=0,
        ga=True,
        note="anon recommendation; needs OPENAI_API_KEY",
    ),
    Engine(
        "gpt-5-nano",
        "openai",
        "gpt-5-nano",
        thinking_budget=0,
        ga=True,
        note="cheapest; needs OPENAI_API_KEY",
    ),
    # The GPT-5.6 generation: cheaper AND far higher on the AA index than
    # gpt-5-mini (Luna $0.20/$1.20, index 37.3 vs mini $0.25/$2.00, index 16.8),
    # which is exactly the claim an adherence eval has to check rather than
    # assume — a smarter model is not automatically a more obedient one.
    Engine(
        "gpt-5.6-luna",
        "openai",
        "gpt-5.6-luna",
        thinking_budget=0,
        ga=True,
        note="cheaper + stronger than gpt-5-mini on paper; needs OPENAI_API_KEY",
    ),
    Engine(
        "gpt-5.6-terra",
        "openai",
        "gpt-5.6-terra",
        thinking_budget=0,
        ga=True,
        note="one tier up from Luna; needs OPENAI_API_KEY",
    ),
    # The gpt-6 generation (2026-09): Luna is cheaper than gpt-5.6-luna on paper
    # ($0.10/$0.50 vs $0.20/$1.20) and higher on the AA index; Sol is the
    # mid-tier. Both need the gpt-6 reasoning cap (roadmodel 0.2.56).
    Engine(
        "gpt-6-luna",
        "openai",
        "gpt-6-luna",
        thinking_budget=0,
        max_output_tokens=6144,
        ga=True,
        note="cheapest current OpenAI; needs OPENAI_API_KEY",
    ),
    Engine(
        "gpt-6-sol",
        "openai",
        "gpt-6-sol",
        thinking_budget=0,
        max_output_tokens=6144,
        ga=True,
        note="needs OPENAI_API_KEY",
    ),
    Engine(
        "gpt-6.1-sol",
        "openai",
        "gpt-6.1-sol",
        thinking_budget=0,
        max_output_tokens=6144,
        ga=True,
        note="OpenAI mid-tier flagship; needs OPENAI_API_KEY",
    ),
    # Gemini 3.x takes a thinking LEVEL; budget 0 maps to `low` (0.2.56).
    Engine(
        "gemini-3.8-flash",
        "google",
        "gemini-3.8-flash",
        thinking_budget=0,
        max_output_tokens=6144,
        ga=True,
        note="current Gemini Flash; level low",
    ),
    # Claude engines: cached system prompt + effort low (0.2.56). Opus 5.5
    # cannot disable thinking; low effort keeps it brief.
    Engine(
        "claude-haiku-4-5",
        "anthropic",
        "claude-haiku-4-5",
        thinking_budget=0,
        max_output_tokens=6144,
        ga=True,
        catalog_id="claude-4.5-haiku",
        note="needs ANTHROPIC_API_KEY",
    ),
    Engine(
        "claude-sonnet-5",
        "anthropic",
        "claude-sonnet-5",
        thinking_budget=0,
        max_output_tokens=8192,
        ga=True,
        note="needs ANTHROPIC_API_KEY",
    ),
    Engine(
        "claude-sonnet-5-5",
        "anthropic",
        "claude-sonnet-5-5",
        thinking_budget=0,
        max_output_tokens=8192,
        ga=True,
        note="needs ANTHROPIC_API_KEY",
    ),
    Engine(
        "claude-opus-5-5",
        "anthropic",
        "claude-opus-5-5",
        thinking_budget=0,
        max_output_tokens=8192,
        ga=True,
        note="needs ANTHROPIC_API_KEY",
    ),
    # OpenAI-compatible engines (providers/openai_compatible.py). Local Ollama
    # models are the ones runnable with no hosted key; the hosted entries run
    # only when their key is present. thinking_budget=0 maps to each provider's
    # documented "reasoning off / lowest" rung (see providers/registry.py).
    Engine(
        "ollama:gemma3:12b",
        "ollama",
        "gemma3:12b",
        thinking_budget=0,
        max_output_tokens=2048,
        ga=False,
        note="local; 128k ctx",
    ),
    # A thinking model whose FULL context does not fit in memory needs a
    # derived tag (`FROM qwen3-vl:32b` + `PARAMETER num_ctx 65536`); run such
    # a tag via --extra ollama:<tag>. Thinking models also need a larger
    # max_output_tokens: the reasoning counts against it and arrives in a
    # separate `reasoning` field, so an exhausted budget means NO visible text.
    Engine(
        "deepseek-flash",
        "deepseek",
        "deepseek-flash",
        thinking_budget=0,
        ga=True,
        note="needs DEEPSEEK_API_KEY",
    ),
    Engine(
        "groq:gpt-oss-120b",
        "groq",
        "openai/gpt-oss-120b",
        thinking_budget=0,
        ga=True,
        note="needs GROQ_API_KEY",
    ),
    Engine(
        "mistral-medium",
        "mistral",
        "mistral-medium-latest",
        thinking_budget=None,
        ga=True,
        note="needs MISTRAL_API_KEY",
    ),
    Engine(
        "xai:grok-4.6", "xai", "grok-4.6", thinking_budget=None, ga=True, note="needs XAI_API_KEY"
    ),
    Engine("zai:glm-5.2", "zai", "glm-5.2", thinking_budget=0, ga=True, note="needs ZAI_API_KEY"),
]

# The engine prod runs today; --baseline overrides it.
BASELINE = "gpt-5.6-luna"
UC_ANON = REPO / "docs" / "user-context.example.md"

_COST_DEMOTION = re.compile(
    r"\b(cheaper|less expensive|lower cost|to save (?:cost|money)|budget[- ]friendly)\b", re.I
)


def _key_for(provider: str) -> str | None:
    env_name = PROVIDER_KEY_ENV.get(provider)
    if env_name is None:
        return None
    key = os.environ.get(env_name) or None
    spec = COMPATIBLE_PROVIDERS.get(provider)
    if key is None and spec is not None and not spec.key_required:
        return OLLAMA_PLACEHOLDER_KEY
    return key


def _parse_extra(raw: str, max_output_tokens: int | None) -> Engine:
    """``provider:model[:thinking_budget]`` — model ids may themselves contain
    ':' (Ollama tags), so the budget is only split off when the LAST segment is
    an integer."""
    provider, _, rest = raw.partition(":")
    if provider not in PROVIDER_KEY_ENV or not rest:
        raise SystemExit(f"--extra {raw!r}: expected provider:model[:budget]")
    budget: int | None = None
    head, sep, tail = rest.rpartition(":")
    if sep and tail.lstrip("-").isdigit():
        rest, budget = head, int(tail)
    engine = Engine(f"{provider}:{rest}", provider, rest, thinking_budget=budget, ga=False)
    if max_output_tokens is not None:
        engine.max_output_tokens = max_output_tokens
    return engine


def _service_hint(eng: Engine) -> str:
    """The engines.json hint for an engine: provider + API id."""
    return f"{eng.provider}-{eng.api_model}"


def _run_via_service(eng: Engine, prompt: str, url: str, token: str) -> dict[str, Any]:
    """One probe through the DEPLOYED service's ladder endpoint, forcing this
    engine. Exercises the production path end to end (the service's keys, its
    engine params, its parse + guards) and reads the provider-reported usage
    back from the response."""
    body = json.dumps(
        {"task_description": prompt, "context": {"force_provider": _service_hint(eng)}}
    ).encode()
    if not url.startswith("https://"):
        raise SystemExit("--via-service takes an https:// URL")
    req = urllib.request.Request(  # noqa: S310 - https only, checked above
        f"{url.rstrip('/')}/v1/recommend/ladder",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - fixed https URL
            r = json.load(resp)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "latency_s": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001 - record every failure mode
        return {
            "error": f"{type(e).__name__}: {str(e)[:160]}",
            "latency_s": round(time.time() - t0, 1),
        }
    answered = r.get("engine")
    if answered and answered != _service_hint(eng):
        # The forced engine failed and the fallback chain answered: a failure
        # of THIS engine, whatever the fallback produced.
        return {"error": f"fell back to {answered}", "latency_s": round(time.time() - t0, 1)}
    return _score(r, round(time.time() - t0, 1), r.get("usage"))


def _run_one(eng: Engine, prompt: str) -> dict[str, Any]:
    key = _key_for(eng.provider)
    if not key:
        return {"skipped": f"no {PROVIDER_KEY_ENV.get(eng.provider, 'key')}"}
    cfg = Config(provider=eng.provider, model=eng.api_model, api_key=key, user_context_path=UC_ANON)
    usage.reset()
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
    call_usage = usage.last()
    return _score(r, latency, call_usage.as_dict() if call_usage else None)


def _score(r: dict[str, Any], latency: float, call_usage: dict[str, Any] | None) -> dict[str, Any]:
    """Score one ladder result (package output or a service response)."""
    picks = r.get("picks", {}) or {}
    guard = r.get("guard", {}) or {}
    out: dict[str, Any] = {
        "latency_s": latency,
        "healthy": bool(guard.get("healthy")),
        "picks": {},
        "checks": {},
        "usage": call_usage,
    }
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
    ap.add_argument(
        "--extra",
        action="append",
        default=[],
        help="ad-hoc engine as provider:model[:thinking_budget]; repeatable",
    )
    ap.add_argument(
        "--from-jsonl",
        default="",
        help="skip running; rebuild the report from an existing JSONL (e.g. a killed run)",
    )
    ap.add_argument("--baseline", default=BASELINE, help="engine key the others are diffed against")
    ap.add_argument(
        "--via-service",
        default="",
        help="run each probe through this deployed service URL (needs ROADMODEL_INTERNAL_TOKEN)",
    )
    ap.add_argument(
        "--summary-json",
        default="",
        help="also write the per-engine summary the /recommend menu reads (docs/engine-eval.json)",
    )
    ap.add_argument(
        "--extra-max-output-tokens",
        type=int,
        default=None,
        help="max_output_tokens for --extra engines (thinking models need 4096+)",
    )
    args = ap.parse_args()

    selected = [e for e in ENGINES if (not args.engines or e.key in args.engines.split(","))]
    selected.extend(_parse_extra(raw, args.extra_max_output_tokens) for raw in args.extra)
    probes = PROBES[: args.probes] if args.probes else PROBES

    rows: list[dict[str, Any]] = []
    if args.from_jsonl:
        rows = [json.loads(line) for line in pathlib.Path(args.from_jsonl).read_text().splitlines()]
        known = {e.key: e for e in ENGINES}
        selected = [
            known.get(key)
            or Engine(key, "?", key, ga=next(r["ga"] for r in rows if r["engine"] == key))
            for key in dict.fromkeys(r["engine"] for r in rows)
        ]
    else:
        jsonl = pathlib.Path(f"{args.out}.jsonl").open("w")
        token = os.environ.get("ROADMODEL_INTERNAL_TOKEN", "")
        if args.via_service and not token:
            raise SystemExit("--via-service needs ROADMODEL_INTERNAL_TOKEN")
        for eng in selected:
            for probe in probes:
                res = (
                    _run_via_service(eng, probe["task"], args.via_service, token)
                    if args.via_service
                    else _run_one(eng, probe["task"])
                )
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
    baseline = args.baseline
    base = {r["probe"]: r for r in rows if r["engine"] == baseline and "picks" in r}
    catalog_by_id = {
        m["id"]: m for m in json.loads((REPO / "docs" / "catalog.json").read_text())["models"]
    }
    known_engines = {e.key: e for e in [*ENGINES, *selected]}

    def call_cost(r: dict[str, Any]) -> float | None:
        """What the call cost at the engine's catalog prices, cache reads billed
        at the catalog's cache rate (10% of input where the catalog has none:
        the discount OpenAI, Anthropic and Google all apply to cache reads),
        Anthropic cache writes at 1.25x input."""
        u = r.get("usage")
        eng = known_engines.get(r["engine"])
        m = catalog_by_id.get((eng.catalog_id or eng.key) if eng else r["engine"])
        if not u or not m:
            return None
        p_in = m["input_price_per_1m"]
        p_cache = m.get("cache_read_per_1m") or p_in * 0.1
        uncached = u["input_tokens"] - u["cached_input_tokens"] - u["cache_write_tokens"]
        return (
            uncached * p_in
            + u["cached_input_tokens"] * p_cache
            + u["cache_write_tokens"] * p_in * 1.25
            + u["output_tokens"] * m["output_price_per_1m"]
        ) / 1_000_000

    by_name = {m["name"].lower(): m for m in catalog_by_id.values()}

    def quality_pick_price(name: str | None) -> float | None:
        """The Quality pick's blended price (3 input : 1 output, the /models
        convention): an engine that escalates every task to the dearest model
        in the catalog shows up here."""
        m = by_name.get((name or "").strip().lower())
        if m is None:
            return None
        return (3 * m["input_price_per_1m"] + m["output_price_per_1m"]) / 4

    def resolves(model: str | None) -> bool:
        """Catalog hit for the pick as emitted, or with a leading maker word
        dropped ('Claude Fable 5.1' -> 'Fable 5.1': a display-name variant of a
        real model, not a hallucination — the strict resolver misses it, which
        is a separate canonicalization gap, not an engine defect)."""
        name = (model or "").strip()
        if cost.model_provider(name) is not None:
            return True
        head, _, tail = name.partition(" ")
        return head.lower() in {"claude", "openai", "google", "xai"} and (
            cost.model_provider(tail) is not None
        )

    def on_catalog(r: dict[str, Any]) -> bool:
        """Every tier pick resolves to a catalogued model. Small/local engines
        hallucinate retired ids ('Claude 3 Opus', 'gpt-4') that still PARSE —
        the parser is name-agnostic — so this is the adherence check that
        separates 'produced the block' from 'chose from the catalog'."""
        return all(resolves(r["picks"][t]["model"]) for t in ("cost", "balanced", "quality"))

    def agg(eng_key: str) -> dict[str, Any]:
        er = [r for r in rows if r["engine"] == eng_key]
        ran = [r for r in er if "picks" in r]
        total = len(er)
        if not ran:
            reason = er[0].get("skipped") or er[0].get("error") or "no runs"
            return {"ran": 0, "total": total, "reason": reason}
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
        lats = sorted(r["latency_s"] for r in ran)
        q_prices = [
            p
            for p in (quality_pick_price(r["picks"]["quality"]["model"]) for r in ran)
            if p is not None
        ]
        costs = [c for c in (call_cost(r) for r in ran) if c is not None]
        with_usage = [r["usage"] for r in ran if r.get("usage")]
        return {
            "ran": n,
            "total": total,
            "mean_latency_s": round(sum(r["latency_s"] for r in ran) / n, 1),
            "p50_latency_s": lats[len(lats) // 2],
            "mean_cost_usd": round(sum(costs) / len(costs), 5) if costs else None,
            "mean_in_tokens": round(sum(u["input_tokens"] for u in with_usage) / len(with_usage))
            if with_usage
            else None,
            "mean_out_tokens": round(sum(u["output_tokens"] for u in with_usage) / len(with_usage))
            if with_usage
            else None,
            "quality_pick_blended_per_1m": round(sum(q_prices) / len(q_prices), 2)
            if q_prices
            else None,
            "cached_share": round(
                sum(u["cached_input_tokens"] for u in with_usage)
                / max(1, sum(u["input_tokens"] for u in with_usage)),
                2,
            )
            if with_usage
            else None,
            "healthy": round(rate(lambda r: r["healthy"]), 2),
            "on_catalog": round(rate(on_catalog), 2),
            "all_fields": round(rate(lambda r: r["checks"]["all_fields"]), 2),
            "sections_parse": round(rate(lambda r: r["checks"]["sections_parse"]), 2),
            "no_task_leak": round(rate(lambda r: r["checks"]["no_task_leak"]), 2),
            "no_cost_demotion": round(rate(lambda r: r["checks"]["no_cost_demotion"]), 2),
            "pick_agreement_vs_baseline": round(sum(exact) / len(exact), 2) if exact else None,
        }

    md = [
        "# Recommender engine differential eval\n",
        f"Probes: {len(probes)} · baseline: `{baseline}` · anon context (user_context_text=None)\n",
    ]
    md.append("## Summary\n")
    md.append(
        "| engine | GA | parsed | lat(s) | p50(s) | $/call | in tok | cached | out tok | Q-pick $/1M | healthy | on-catalog | fields | sections | no-leak | no-demote | pick-agree vs base |"
    )
    md.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for eng in selected:
        a = agg(eng.key)
        ga = "GA" if eng.ga else "preview"
        if a["ran"] == 0:
            md.append(
                f"| `{eng.key}` | {ga} | 0/{a['total']} | — | — | — | — | — | — | — | — | — | — | — | — | — | _{a['reason']}_ |"
            )
        else:
            md.append(
                f"| `{eng.key}` | {ga} | {a['ran']}/{a['total']} | {a['mean_latency_s']} | {a['p50_latency_s']} | {a['mean_cost_usd']} | {a['mean_in_tokens']} | {a['cached_share']} | {a['mean_out_tokens']} | {a['quality_pick_blended_per_1m']} | {a['healthy']} | {a['on_catalog']} | {a['all_fields']} | {a['sections_parse']} | {a['no_task_leak']} | {a['no_cost_demotion']} | {a['pick_agreement_vs_baseline']} |"
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
    if args.summary_json:
        # The figures the /recommend engine menu shows, keyed by engines.json
        # hint. Merged into an existing file so engines evaluated by separate
        # runs (local keys vs --via-service) accumulate.
        path = pathlib.Path(args.summary_json)
        summary = json.loads(path.read_text()) if path.exists() else {"engines": {}}
        today = datetime.date.today().isoformat()
        for eng in selected:
            a = agg(eng.key)
            if a["ran"] == 0:
                continue
            checks = ("all_fields", "sections_parse", "no_task_leak", "on_catalog")
            summary["engines"][_service_hint(eng)] = {
                "evaluated_on": today,
                "probes": a["total"],
                "parsed": a["ran"],
                # A probe passes when it parsed with every structured field
                # and section, stayed on the catalog and leaked no task text.
                "passed": sum(
                    1
                    for r in rows
                    if r["engine"] == eng.key
                    and "picks" in r
                    and all(r["checks"][c] for c in checks if c != "on_catalog")
                ),
                "healthy_ladder": a["healthy"],
                "p50_latency_s": a["p50_latency_s"],
                "mean_cost_usd": a["mean_cost_usd"],
                "mean_input_tokens": a["mean_in_tokens"],
                "cached_share": a["cached_share"],
                "quality_pick_blended_per_1m": a["quality_pick_blended_per_1m"],
                "via": "service" if args.via_service else "package",
            }
        summary["_comment"] = (
            "Generated by scripts/eval_recommend_engines.py --summary-json; do not hand-edit. "
            "The 12-probe battery per recommender engine: parse/field adherence, latency, and "
            "the measured cost per three-pick recommendation at catalog prices (cache reads "
            "billed at the cache rate). The /recommend engine menu shows these figures."
        )
        summary["generated_at"] = today
        text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
        path.write_text(text)
        print(f"Summary: {path}")
        # The service deploys from service/ and cannot read docs/, so it reads
        # a copy beside its engine registry (service/app/engines.py EVALUATED,
        # which gates the engines a visitor's key may run).
        # tests/test_engine_eval_mirror.py holds the two equal.
        repo = pathlib.Path(__file__).resolve().parents[1]
        if path.resolve() == repo / "docs" / "engine-eval.json":
            mirror = repo / "service" / "app" / "engine-eval.json"
            mirror.write_text(text)
            print(f"Mirror:  {mirror}")
    print(f"\nReport: {report}\nRaw:    {args.out}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
