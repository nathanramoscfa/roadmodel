#!/usr/bin/env python3
"""Measure how many output tokens each model spends at each effort.

The frontier's price axis is a model's blended list price times the tokens it
draws at the effort it runs (src/roadmodel/scoring.py ``frontier_price``). A
per-token price is the same at every effort (Artificial Analysis lists one
price for every effort row), so the cost of running a model at a higher
effort is all in the extra tokens. Those are not published anywhere we may
read them: AA's API carries no token counts, and its Terms of Use (§3.3)
forbid scraping the site that shows them. So this script measures them.

    python update/measure_effort_tokens.py --plan          # what would run
    python update/measure_effort_tokens.py                 # run + write the file
    python update/measure_effort_tokens.py --summarize     # rewrite from saved runs
    python update/measure_effort_tokens.py --models gpt-6-luna --levels low,high

Every model AA measured at more than one effort (``effort_variants`` in
docs/benchmarks.json) runs a fixed probe set (``PROBES``, eight short tasks
across the categories) ``--samples`` times at each of those efforts, on one
lane:

- ``claude-code``: Anthropic models, ``claude -p --effort <level>`` on the
  operator's Claude subscription, isolated from settings, hooks, MCP and
  tools so a probe draws a few thousand input tokens, not fifty.
- ``codex``: the GPT models a ChatGPT sign-in runs (``CODEX_MODELS``),
  ``codex exec -c model_reasoning_effort=<level>`` on the operator's ChatGPT
  plan. Codex before 0.162 cannot run GPT-6.1 Sol on a ChatGPT account;
  ``--codex-bin`` points at a current one.
- ``openrouter``: everything else, ``reasoning.effort`` on OpenRouter's chat
  endpoint, paid per token; ``--max-usd`` stops new OpenRouter calls once
  their reported cost reaches it.

An effort a lane cannot set (OpenRouter's ``supported_efforts``) is skipped.
Runs go out first sample first, so a cap that stops the OpenRouter lane
leaves each of its efforts measured once. Each run is appended to ``--runs`` as one JSON line, and a run already there
is not repeated, so an interrupted measurement resumes.

docs/effort-tokens.json then holds, per model and effort, the mean output
tokens per probe (reasoning included) and its ``multiplier``: that mean,
fitted so it never falls as the effort rises, over
the reference, the median across measured models of their mean at ``high``.
A typical model at high reads 1.0, as the uniform table in scoring.py
(``EFFORT_TOKEN_MULTIPLIER``) has it; the scorer falls back to that table
for any model and effort not measured here. An effort needs at least
``MIN_SUCCESS_SHARE`` of the probes to have a successful run to be written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

UPDATE_DIR = Path(__file__).resolve().parent
REPO_ROOT = UPDATE_DIR.parent
BENCH_PATH = REPO_ROOT / "docs" / "benchmarks.json"
OUT_PATH = REPO_ROOT / "docs" / "effort-tokens.json"
RUNS_PATH = Path.home() / ".cache" / "roadmodel" / "effort-token-runs.jsonl"
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"

SCHEMA_VERSION = 1
# The scorer's effort ladder (scoring.EFFORT_LADDER): the levels a pick runs at.
LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
REFERENCE_LEVEL = "high"
MIN_SUCCESS_SHARE = 0.75
CALL_TIMEOUT_S = 1200
# The GPT models a ChatGPT sign-in runs in Codex (Codex's own model list for
# the account, plus GPT-6.1 Sol, which needs Codex 0.162 or later).
CODEX_MODELS: frozenset[str] = frozenset(
    {
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-6-astra",
        "gpt-6-luna",
        "gpt-6-sol",
        "gpt-6.1-sol",
    }
)
# Models run on their subscription lane AND on OpenRouter, at these efforts,
# to measure how the lanes differ: the same model draws more tokens through
# OpenRouter's bare API than inside a coding agent (about 1.3x), and the
# OpenRouter-only models are scaled by that before they are compared.
CALIBRATION_MODELS: tuple[str, ...] = ("claude-sonnet-5-5", "gpt-5.5", "gpt-6-luna", "gpt-6.1-sol")
CALIBRATION_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh")
LANE_WORKERS: dict[str, int] = {"claude-code": 3, "codex": 4, "openrouter": 8}

PREAMBLE = "Be concise.\n\n"
# Codex is the one lane whose agent can run commands; the others run with no
# tools. (xAI refuses a prompt that carries this line, so it is Codex's only.)
CODEX_PREAMBLE = "Answer from your own reasoning: do not run commands or create files.\n"
_CONTRACT = """\
MASTER SERVICES AGREEMENT (excerpt)

1. Parties. This Agreement is made on 14 March 2026 between Halvorsen Freight AS, a company
registered in Norway ("Customer"), and Brightline Data Systems Ltd, a company registered in
Ireland ("Supplier").

2. Term. The Agreement starts on 1 April 2026 and runs for an initial term of thirty-six (36)
months. It renews automatically for successive twelve (12) month periods unless either party
gives written notice of non-renewal at least ninety (90) days before the end of the then-current
term.

3. Fees. Customer shall pay a platform fee of EUR 18,500 per month, invoiced quarterly in
advance. Usage above 40 million API calls in a calendar month is charged at EUR 0.12 per
thousand calls, invoiced monthly in arrears. Invoices are payable within forty-five (45) days.
Late amounts bear interest at 1.5% per month.

4. Service Levels. Supplier shall make the platform available 99.9% of each calendar month,
excluding scheduled maintenance notified at least five (5) business days in advance. For each
full 0.1% below that level, Customer receives a service credit of 5% of that month's platform
fee, capped at 30%. Service credits are Customer's sole remedy for availability failures, except
where availability falls below 97% in two consecutive months, in which case Customer may
terminate under clause 9.2.

5. Data Protection. Supplier processes personal data only on Customer's documented
instructions and shall notify Customer of a personal data breach without undue delay and in any
event within thirty-six (36) hours of becoming aware of it. Supplier shall not transfer personal
data outside the European Economic Area without Customer's prior written consent.

6. Liability. Each party's total liability under this Agreement in any contract year is limited to
the fees paid or payable in the twelve (12) months before the event giving rise to the claim. The
cap does not apply to breaches of clause 5, to either party's indemnity obligations, or to
liability that cannot be limited by law; for breaches of clause 5 the cap is three (3) times
that amount.

7. Governing Law. This Agreement is governed by the laws of England and Wales, and the courts of
London have exclusive jurisdiction.

9.2 Termination for Cause. Either party may terminate this Agreement with immediate effect by
written notice if the other party commits a material breach that is not remedied within thirty
(30) days of written notice of it.
"""

# id, task. Fixed: changing a probe changes ``probe_set_sha256`` and every
# saved run is then measured again.
PROBES: tuple[tuple[str, str], ...] = (
    (
        "dice",
        "A fair six-sided die is rolled repeatedly until the running total is at least 10. "
        "What is the probability that the final total is exactly 10? Give the exact fraction "
        "and one sentence of justification.",
    ),
    (
        "zeros",
        "What is the smallest positive integer n such that n! has at least 100 trailing zeros? "
        "Give n and a one-line check.",
    ),
    (
        "intervals",
        "Write a Python function `merge_intervals(intervals: list[tuple[int, int]]) -> "
        "list[tuple[int, int]]` that merges overlapping and touching closed intervals, plus "
        "three assert-based tests covering edge cases. Reply with the code only.",
    ),
    (
        "lru-bug",
        "This LRU cache has bugs. Name each bug in one line, then give the corrected class.\n\n"
        "```python\n"
        "class LRU:\n"
        "    def __init__(self, cap):\n"
        "        self.cap = cap\n"
        "        self.d = {}\n"
        "        self.order = []\n"
        "    def get(self, k):\n"
        "        if k in self.d:\n"
        "            self.order.append(k)\n"
        "            return self.d[k]\n"
        "        return -1\n"
        "    def put(self, k, v):\n"
        "        if len(self.d) > self.cap:\n"
        "            old = self.order.pop()\n"
        "            del self.d[old]\n"
        "        self.d[k] = v\n"
        "        self.order.append(k)\n"
        "```",
    ),
    (
        "migration",
        "Give a 6-step plan to migrate a Postgres-backed Django app from a single VM to "
        "Kubernetes with zero downtime, naming the main risk at each step.",
    ),
    (
        "tool-plan",
        "You are an agent with these tools: search_orders(customer_email) -> list of "
        "{order_id, status, total}; get_order(order_id) -> {items, shipped_at, carrier}; "
        "refund(order_id, amount, reason); send_email(to, subject, body). A customer, "
        "ana@example.com, writes that one of her two recent orders arrived damaged but does not "
        "say which. Give the ordered list of tool calls you would make, as a JSON array of "
        "{tool, args, why}, stopping where you would need her answer.",
    ),
    (
        "contract",
        _CONTRACT + "\nFrom the excerpt above, return JSON with these keys: initial_term_months, "
        "notice_days_for_non_renewal, monthly_platform_fee_eur, max_service_credit_pct, "
        "breach_notification_hours, liability_cap_for_data_breach (a short phrase), "
        "governing_law. Then list any clause that lets Customer terminate early, in one line.",
    ),
    (
        "latency",
        "Explain to a product manager the difference between p50 and p99 latency, and why p99 "
        "matters more for a service that fans one request out to 50 backends. Under 150 words.",
    ),
)


def probe_set_sha256() -> str:
    blob = json.dumps([PREAMBLE, CODEX_PREAMBLE, PROBES], sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class Job:
    model_id: str
    level: str
    lane: str
    target: str  # the lane's model id
    probe: str
    sample: int
    # A run of a subscription-lane model on OpenRouter, measuring the lane.
    calibration: bool = False

    @property
    def key(self) -> str:
        base = f"{self.model_id}|{self.level}|{self.probe}|{self.sample}"
        return f"{base}|calibration" if self.calibration else base


@dataclass(frozen=True)
class RunResult:
    output_tokens: int | None
    cost_usd: float = 0.0
    error: str | None = None
    truncated: bool = False


# --- planning -----------------------------------------------------------------


def measured_levels(row: dict[str, Any]) -> list[str]:
    """The ladder levels AA measured a model at: its headline row's effort and
    each ``effort_variants`` level, lowest first. Empty when AA names one or
    no effort (nothing to compare a multiplier across)."""
    levels = set(row.get("effort_variants") or {})
    if row.get("aa_effort"):
        levels.add(str(row["aa_effort"]))
    out = [lv for lv in LEVELS if lv in levels]
    return out if len(out) > 1 else []


def lane_for(model_id: str, creator: str) -> str:
    if creator.lower() == "anthropic" or model_id.startswith("claude-"):
        return "claude-code"
    if model_id in CODEX_MODELS:
        return "codex"
    return "openrouter"


def claude_code_id(model_id: str) -> str:
    """Claude Code's id for a catalog id: dots become dashes."""
    return model_id.replace(".", "-")


def openrouter_routes() -> dict[str, tuple[str, list[str]]]:
    """Catalog id -> (OpenRouter id, the efforts it accepts), for every
    catalogued model OpenRouter routes as text."""
    sys.path.insert(0, str(UPDATE_DIR))
    import extract_openrouter_models as orm  # noqa: PLC0415

    entries = orm.fetch_entries()
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    out: dict[str, tuple[str, list[str]]] = {}
    for mid, entry in orm.map_entries(entries, selector, orm.load_exceptions()):
        if mid in out:
            continue
        reasoning = entry.get("reasoning") or {}
        efforts = reasoning.get("supported_efforts") if isinstance(reasoning, dict) else None
        out[mid] = (str(entry["id"]).split(":", 1)[0], [str(e) for e in efforts or []])
    return out


def plan(
    bench: dict[str, Any],
    *,
    samples: int,
    models: set[str] | None,
    levels: set[str] | None,
    routes: dict[str, tuple[str, list[str]]],
) -> tuple[list[Job], dict[str, str]]:
    """Every run to make, and why each model with per-effort data left out is."""
    jobs: list[Job] = []
    skipped: dict[str, str] = {}
    for mid, row in sorted(bench.get("models", {}).items()):
        if models is not None and mid not in models:
            continue
        lvls = measured_levels(row)
        if not lvls:
            continue
        lane = lane_for(mid, str(row.get("aa_creator") or ""))
        target = mid
        if lane == "claude-code":
            target = claude_code_id(mid)
        elif lane == "openrouter":
            if mid not in routes:
                skipped[mid] = "no lane serves it (not on OpenRouter, no subscription lane)"
                continue
            target, accepted = routes[mid]
            settable = [lv for lv in lvls if lv in accepted]
            if len(settable) < 2:
                skipped[mid] = f"OpenRouter accepts {accepted or 'no'} efforts"
                continue
            for lv in lvls:
                if lv not in accepted:
                    skipped[f"{mid}@{lv}"] = "OpenRouter cannot set this effort"
            lvls = settable
        for lv in lvls:
            if levels is not None and lv not in levels:
                continue
            for probe, _ in PROBES:
                for s in range(samples):
                    jobs.append(Job(mid, lv, lane, target, probe, s))
    for mid in CALIBRATION_MODELS:
        row = bench.get("models", {}).get(mid)
        if row is None or mid not in routes or (models is not None and mid not in models):
            continue
        target, accepted = routes[mid]
        for lv in measured_levels(row):
            if lv in CALIBRATION_LEVELS and lv in accepted and (levels is None or lv in levels):
                for probe, _ in PROBES:
                    jobs.append(Job(mid, lv, "openrouter", target, probe, 0, calibration=True))
    # Every first sample before any second, so a spend cap that stops the
    # OpenRouter lane early still leaves each of its efforts measured once.
    jobs.sort(key=lambda j: j.sample)
    return jobs, skipped


# --- lanes ----------------------------------------------------------------------


def _prompt(probe: str, lane: str = "") -> str:
    return (CODEX_PREAMBLE if lane == "codex" else "") + PREAMBLE + dict(PROBES)[probe]


def run_claude_code(job: Job, claude_bin: str) -> RunResult:
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                claude_bin,
                "-p",
                "--model",
                job.target,
                "--effort",
                job.level,
                "--output-format",
                "json",
                "--setting-sources",
                "",
                "--strict-mcp-config",
                "--tools",
                "",
                "--no-session-persistence",
            ],
            input=_prompt(job.probe),
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=CALL_TIMEOUT_S,
            check=False,
        )
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), "")
    if not line:
        return RunResult(None, error=f"exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    data = json.loads(line)
    if data.get("is_error"):
        return RunResult(None, error=str(data.get("result"))[:200])
    # Claude Code also makes small Haiku side calls; count the model's own.
    usage = (data.get("modelUsage") or {}).get(job.target)
    if not isinstance(usage, dict):
        return RunResult(None, error=f"no usage for {job.target}")
    return RunResult(int(usage["outputTokens"]), truncated=data.get("stop_reason") == "max_tokens")


def run_codex(job: Job, codex_bin: str) -> RunResult:
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                codex_bin,
                "exec",
                "--json",
                "--skip-git-repo-check",
                "-s",
                "read-only",
                "-m",
                job.target,
                "-c",
                f"model_reasoning_effort={job.level}",
                _prompt(job.probe, "codex"),
            ],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=CALL_TIMEOUT_S,
            check=False,
        )
    total = 0
    turns = 0
    error = None
    for ln in proc.stdout.splitlines():
        try:
            event = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            # output_tokens already includes reasoning_output_tokens.
            total += int(event["usage"]["output_tokens"])
            turns += 1
        elif event.get("type") in ("turn.failed", "error"):
            error = str(event.get("error") or event.get("message"))[:200]
    if turns == 0:
        return RunResult(None, error=error or f"exit {proc.returncode}")
    return RunResult(total)


def run_openrouter(job: Job, key: str) -> RunResult:
    response = requests.post(
        OR_CHAT_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": USER_AGENT,
            "X-Title": "roadmodel effort-token measurement",
        },
        json={
            "model": job.target,
            "messages": [{"role": "user", "content": _prompt(job.probe)}],
            "reasoning": {"effort": job.level},
            "usage": {"include": True},
        },
        timeout=CALL_TIMEOUT_S,
    )
    data = response.json()
    if response.status_code != 200 or "error" in data:
        return RunResult(None, error=str(data.get("error") or response.status_code)[:200])
    usage = data.get("usage") or {}
    choice = (data.get("choices") or [{}])[0]
    return RunResult(
        int(usage["completion_tokens"]),
        cost_usd=float(usage.get("cost") or 0.0),
        truncated=choice.get("finish_reason") == "length",
    )


# --- execution ------------------------------------------------------------------


def load_runs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text().splitlines():
        if ln.strip():
            out.append(json.loads(ln))
    return out


def execute(
    jobs: list[Job],
    runners: dict[str, Callable[[Job], RunResult]],
    runs_path: Path,
    *,
    sha: str,
    max_usd: float,
    spent_usd: float,
) -> float:
    """Run every job, appending one line per run to ``runs_path``. OpenRouter
    jobs stop starting once their reported cost reaches ``max_usd``. Returns
    the OpenRouter spend, the saved runs' included."""
    lock = threading.Lock()
    spent = [spent_usd]
    runs_path.parent.mkdir(parents=True, exist_ok=True)

    def one(job: Job) -> None:
        if job.lane == "openrouter":
            with lock:
                if spent[0] >= max_usd:
                    return
        try:
            res = runners[job.lane](job)
        except Exception as exc:  # noqa: BLE001 - one failed run is recorded, not fatal
            res = RunResult(None, error=repr(exc)[:200])
        record = {
            "key": job.key,
            "model_id": job.model_id,
            "level": job.level,
            "lane": job.lane,
            "target": job.target,
            "probe": job.probe,
            "sample": job.sample,
            "calibration": job.calibration,
            "output_tokens": res.output_tokens,
            "cost_usd": res.cost_usd,
            "truncated": res.truncated,
            "error": res.error,
            "probe_set_sha256": sha,
            "at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with lock:
            spent[0] += res.cost_usd
            with runs_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
            status = res.output_tokens if res.error is None else f"ERROR {res.error[:80]}"
            print(f"{job.key} [{job.lane}] {status}  (OpenRouter ${spent[0]:.2f})", flush=True)

    pools = {lane: ThreadPoolExecutor(max_workers=n) for lane, n in LANE_WORKERS.items()}
    futures: list[Future[None]] = []
    for job in jobs:
        futures.append(pools[job.lane].submit(one, job))
    for f in futures:
        f.result()
    for p in pools.values():
        p.shutdown()
    return spent[0]


# --- summary --------------------------------------------------------------------


def _level_means(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Per (model, effort): the mean output tokens per probe, each probe
    weighing the same whatever its sample count; an effort with fewer than
    MIN_SUCCESS_SHARE of the probes measured is left out."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((r["model_id"], r["level"]), []).append(r)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, group in sorted(grouped.items()):
        ok = [r for r in group if r.get("error") is None and r.get("output_tokens") is not None]
        per_probe: dict[str, list[int]] = {}
        for r in ok:
            per_probe.setdefault(r["probe"], []).append(int(r["output_tokens"]))
        if len(per_probe) < MIN_SUCCESS_SHARE * len(PROBES):
            continue
        out[key] = {
            "mean_output_tokens": statistics.fmean(statistics.fmean(v) for v in per_probe.values()),
            "runs": len(ok),
            "truncated": sum(1 for r in ok if r.get("truncated")),
            "lane": str(group[0]["lane"]),
        }
    return out


def monotone(values: list[float]) -> list[float]:
    """The closest non-decreasing sequence to ``values`` (pool-adjacent-
    violators, equal weights): a higher effort never draws fewer tokens, so an
    inversion between neighbouring efforts is noise, and the pair reads its
    average."""
    blocks: list[list[float]] = []  # [sum, count]
    for v in values:
        blocks.append([v, 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            total, n = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += n
    out: list[float] = []
    for total, n in blocks:
        out.extend([total / n] * int(n))
    return out


def summarize(
    runs: Iterable[dict[str, Any]],
    *,
    sha: str,
    skipped: dict[str, str],
    generated_at: str,
    samples: int,
) -> dict[str, Any]:
    """docs/effort-tokens.json from the saved runs of the current probe set:
    per model and effort, the mean output tokens per probe and that mean over
    the reference (the median across models of their mean at ``high``).

    The same model draws more tokens through OpenRouter's bare API than in a
    coding agent, so an OpenRouter-measured model is scaled by the lane factor
    before it is compared: the median, over the calibration runs (a
    subscription-lane model also run on OpenRouter), of the subscription
    lane's mean over OpenRouter's. With no calibration runs the factor is 1.
    A model's multipliers never fall as its effort rises (:func:`monotone`);
    ``mean_output_tokens`` keeps the raw measurement."""
    current = [r for r in runs if r.get("probe_set_sha256") == sha]
    # The latest run of each key wins (a re-run replaces a failed one).
    latest: dict[str, dict[str, Any]] = {}
    for r in current:
        latest[r["key"]] = r
    primary = _level_means(r for r in latest.values() if not r.get("calibration"))
    calibration = _level_means(r for r in latest.values() if r.get("calibration"))
    ratios = [
        primary[key]["mean_output_tokens"] / v["mean_output_tokens"]
        for key, v in calibration.items()
        if key in primary and primary[key]["lane"] != "openrouter" and v["mean_output_tokens"] > 0
    ]
    factor = statistics.median(ratios) if ratios else 1.0

    def comparable(v: dict[str, Any]) -> float:
        mean = float(v["mean_output_tokens"])
        return mean * factor if v["lane"] == "openrouter" else mean

    by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for (mid, lv), v in primary.items():
        by_model.setdefault(mid, {})[lv] = v
    # A model needs two measured efforts for a ratio across them to mean anything.
    by_model = {mid: lv for mid, lv in by_model.items() if len(lv) > 1}
    fitted: dict[str, dict[str, float]] = {}
    for mid, lvs in by_model.items():
        order = sorted(lvs, key=LEVELS.index)
        fitted[mid] = dict(zip(order, monotone([comparable(lvs[lv]) for lv in order]), strict=True))
    at_ref = [f[REFERENCE_LEVEL] for f in fitted.values() if REFERENCE_LEVEL in f]
    if not at_ref:
        raise ValueError(f"no model measured at {REFERENCE_LEVEL!r}: no reference")
    reference = statistics.median(at_ref)
    models: dict[str, Any] = {}
    for mid in sorted(by_model):
        rows = sorted(by_model[mid].items(), key=lambda kv: LEVELS.index(kv[0]))
        models[mid] = {
            "lane": rows[0][1]["lane"],
            "levels": {
                lv: {
                    "mean_output_tokens": round(v["mean_output_tokens"], 1),
                    "runs": v["runs"],
                    "truncated": v["truncated"],
                    "multiplier": round(fitted[mid][lv] / reference, 3),
                }
                for lv, v in rows
            },
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "source": (
            "Measured by update/measure_effort_tokens.py: output tokens (reasoning included) "
            "per probe on a fixed set of short tasks, at each effort Artificial Analysis "
            "measured the model at."
        ),
        "probe_set_sha256": sha,
        "probes": len(PROBES),
        "samples_per_probe": samples,
        "reference": {
            "level": REFERENCE_LEVEL,
            "mean_output_tokens": round(reference, 1),
            "models": len(at_ref),
        },
        "lanes": {"openrouter": {"factor": round(factor, 3), "pairs": len(ratios)}},
        "models": models,
        "unmeasured": dict(sorted({**_failed(latest.values(), set(models)), **skipped}.items())),
    }


def _failed(runs: Iterable[dict[str, Any]], measured: set[str]) -> dict[str, str]:
    """Why each model that was run but not measured was not: its most
    common error (an account gate, a retired endpoint), else too few probes."""
    errors: dict[str, list[str]] = {}
    for r in runs:
        if r.get("calibration") or r["model_id"] in measured:
            continue
        errors.setdefault(r["model_id"], []).append(str(r.get("error") or ""))
    out = {}
    for mid, errs in errors.items():
        named = [e for e in errs if e]
        out[mid] = (
            f"runs failed: {max(set(named), key=named.count)[:160]}"
            if named
            else "too few probes measured"
        )
    return out


def unmeasured(bench: dict[str, Any], doc: dict[str, Any]) -> dict[str, list[str]]:
    """The efforts AA measured a model at that docs/effort-tokens.json has no
    figure for and no recorded reason to lack: a new model or effort since the
    last measurement. Such a pair reads the uniform table until it is measured."""
    known = doc.get("unmeasured") or {}
    measured = doc.get("models") or {}
    out: dict[str, list[str]] = {}
    for mid, row in sorted((bench.get("models") or {}).items()):
        if mid in known:
            continue
        have = (measured.get(mid) or {}).get("levels") or {}
        missing = [
            lv for lv in measured_levels(row) if lv not in have and f"{mid}@{lv}" not in known
        ]
        if missing:
            out[mid] = missing
    return out


def write_if_changed(path: Path, doc: dict[str, Any]) -> bool:
    """Write ``doc`` unless only its timestamp differs from what is there."""
    if path.exists():
        old = json.loads(path.read_text())
        if {**old, "generated_at_utc": None} == {**doc, "generated_at_utc": None}:
            return False
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return True


def _keychain(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["security", "find-generic-password", "-s", f"roadmodel/{name}", "-w"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--plan", action="store_true", help="print the runs and exit")
    parser.add_argument("--summarize", action="store_true", help="only rewrite the file")
    parser.add_argument(
        "--unmeasured",
        action="store_true",
        help="print each model's AA-measured efforts the file lacks (offline) and exit",
    )
    parser.add_argument("--models", help="comma-separated catalog ids (default: every one)")
    parser.add_argument("--levels", help="comma-separated efforts (default: every measured one)")
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--max-usd", type=float, default=15.0, help="OpenRouter spend cap")
    parser.add_argument("--runs", type=Path, default=RUNS_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--claude-bin", default=shutil.which("claude") or "claude")
    parser.add_argument("--codex-bin", default=shutil.which("codex") or "codex")
    args = parser.parse_args(argv)

    bench = json.loads(BENCH_PATH.read_text())
    if args.unmeasured:
        doc = json.loads(args.out.read_text()) if args.out.exists() else {}
        for mid, lvls in unmeasured(bench, doc).items():
            print(f"{mid}: {', '.join(lvls)}")
        return 0
    sha = probe_set_sha256()
    routes = openrouter_routes()
    jobs, skipped = plan(
        bench,
        samples=args.samples,
        models=set(args.models.split(",")) if args.models else None,
        levels=set(args.levels.split(",")) if args.levels else None,
        routes=routes,
    )
    saved = load_runs(args.runs)
    done = {r["key"] for r in saved if r.get("probe_set_sha256") == sha and r.get("error") is None}
    todo = [j for j in jobs if j.key not in done]
    by_lane: dict[str, int] = {}
    for j in todo:
        by_lane[j.lane] = by_lane.get(j.lane, 0) + 1
    print(
        f"measure_effort_tokens: {len(jobs)} runs planned, {len(todo)} to make {by_lane}; "
        f"skipped {skipped}",
        file=sys.stderr,
    )
    if args.plan:
        for j in todo:
            print(j.key, j.lane, j.target)
        return 0
    if not args.summarize and todo:
        key = _keychain("OPENROUTER_API_KEY") if "openrouter" in by_lane else None
        if "openrouter" in by_lane and not key:
            print("measure_effort_tokens: no OPENROUTER_API_KEY", file=sys.stderr)
            return 1
        runners: dict[str, Callable[[Job], RunResult]] = {
            "claude-code": lambda j: run_claude_code(j, args.claude_bin),
            "codex": lambda j: run_codex(j, args.codex_bin),
            "openrouter": lambda j: run_openrouter(j, key or ""),
        }
        spent = sum(float(r.get("cost_usd") or 0) for r in saved if r.get("lane") == "openrouter")
        spent = execute(todo, runners, args.runs, sha=sha, max_usd=args.max_usd, spent_usd=spent)
        print(f"measure_effort_tokens: OpenRouter spend ${spent:.2f}", file=sys.stderr)
    doc = summarize(
        load_runs(args.runs),
        sha=sha,
        # Every model's reason, not only the ones this run was narrowed to.
        skipped=plan(bench, samples=1, models=None, levels=None, routes=routes)[1],
        generated_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        samples=args.samples,
    )
    changed = write_if_changed(args.out, doc)
    print(
        f"measure_effort_tokens: {len(doc['models'])} models"
        f"{' written' if changed else ' unchanged'} to {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
