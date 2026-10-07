"""Deterministic scoring core: rank (model, platform, effort) candidates in code.

This is the first slice of moving the selector's decision out of prose and into
a scoring function. The LLM's job shrinks to what only it can do — classify the
task (category, complexity, whether it is a novel / proof-like problem) and
write the rationale — while everything that is arithmetic over published data
and the operator's declared funding happens here, where it is testable,
explainable term by term, and cannot contradict itself.

Score, per candidate (model reached through a specific access method)::

    score = quality − requirement_penalty − λ · K · decades(effective cost)

- ``quality`` (0–100) is the model's standing in the task's category: the
  Artificial Analysis evidence figure for that category, min-max scaled across
  the measured catalog (by rank for coding and agentic, see ``RANK_SCALED``) and blended
  70/30 with the S→D letter, or the letter alone when AA has not measured the
  model (``quality_source`` says which).
- ``requirement_penalty`` is a steep linear penalty for falling short of the
  quality the task's complexity requires (Low → C, Medium → B, High → A, High
  plus a novel / multi-step-proof problem → S). Soft, not a hard filter, so a
  thin candidate set still ranks instead of returning nothing.
- ``effective cost`` is the blended list price (3 input : 1 output) scaled by a
  *scarcity* factor for the platform that would run it — 0 on a subscription
  pool the operator never exhausts, a fraction on a pool they can exhaust,
  full list price on pay-per-token or an exhausted pool (usage credits bill at
  list price) — and by the expected token multiplier of the chosen effort.
  ``decades`` is log10 of that cost above a floor, so a 10× price step costs
  the same points anywhere on the range and $0 is not infinitely good.
- ``K`` is the market exchange rate between price and quality: the slope of an
  OLS fit of the AA Intelligence Index on log10(price) over the catalog (≈ 16
  index points per decade today), recomputed from the bundled data. λ scales
  it by budget posture (``cheap`` values a decade of spend more than the market
  does, ``best`` much less, ``balanced`` sits near the market line) and by the
  stakes (a hard or novel task weighs cost less, because a failed attempt
  costs more than the price gap).

Hard filters run first: availability, supersession (a superseded model
leaves while its successor is available, as it leaves the recommender's),
allowed jurisdictions, the operator's platform allow / deny lists. Funding is read from the user-context exactly as
:mod:`roadmodel.cost` reads it (Active subscriptions / Active API keys / Local
models) plus the ``Consumption headroom`` line and the ``Usage-pool status``
table; an unfunded platform is never chosen while a funded one exists.

The BACKUP is the best candidate from a *different provider that the operator
can actually reach*; when no other provider is funded the result carries a
warning instead of an unreachable name (issue #642).

Every constant below is a PRIOR, named so a usage ledger can replace it with a
measured value later — the calibration path is the point of writing this in
code. Nothing here calls a model.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from importlib import resources
from typing import Any, Final

from roadmodel import cost as _cost

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

CATEGORIES: Final[tuple[str, ...]] = (
    "coding",
    "planning",
    "agentic",
    "multimodal",
    "long-context",
    "knowledge",
    "speed",
)
COMPLEXITIES: Final[tuple[str, ...]] = ("low", "medium", "high")
BUDGETS: Final[tuple[str, ...]] = ("cheap", "balanced", "best")
EFFORT_LADDER: Final[tuple[str, ...]] = ("low", "medium", "high", "xhigh", "max")
# Level names across every documented effort dial, lowest first: the scorer's
# five plus the words some surfaces add below or above them (Gemini's
# `minimal`, Codex's `ultra`). Orders and compares native levels; each
# surface's own list comes from the catalog's `effort_levels`, which
# update/build_catalog.py reads from the trackers' snapshots of its docs.
LEVEL_ORDER: Final[tuple[str, ...]] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)

# The Artificial Analysis evidence figure per category. For the five derived
# categories it is the evidence update/derive_ratings.py letters from, and the
# web catalog's too (tests/test_derived_ratings.py holds the three together).
# ``speed`` reads the top-level tokens/s field: it enters quality here, but
# its letter stays an estimate, since AA measures throughput on the maker's
# own endpoint at max effort. ``None`` = the letter only (multimodal: AA runs
# no multimodal evaluation). A ``COMPOSITES`` key is computed by
# ``with_composites``.
CATEGORY_EVIDENCE: Final[dict[str, str | None]] = {
    "coding": "coding_composite",
    "planning": "artificial_analysis_intelligence_index",
    "agentic": "terminalbench_v4_0",
    "multimodal": None,
    "long-context": "lcr",
    "knowledge": "hle",
    "speed": "median_output_tokens_per_second",
}

# Categories whose evidence enters quality by RANK among the measured catalog
# (0 = lowest, 100 = highest, ties share their mean rank) instead of min-max.
# Terminal-Bench 4.0 spreads the field over 0–64% with the leader far above
# the pack, so min-max would squash most models toward 0; update/
# derive_ratings.py letters agentic by rank for the same reason (#789).
RANK_SCALED: Final[frozenset[str]] = frozenset({"coding", "agentic"})

# Composite evidence: the mean of a model's mid-rank percentiles (0–1) on each
# part, among the models measured on every part. Coding pairs SciCode with
# Terminal-Bench 4.0, the evaluations AA's own Coding Index averaged, on the
# releases AA runs today (it publishes no Coding Index for new models).
# Mirrors update/derive_ratings.py COMPOSITES.
COMPOSITES: Final[dict[str, tuple[str, ...]]] = {
    "coding_composite": ("scicode", "terminalbench_v4_0"),
}
_RANK_SCALED_KEYS: Final[frozenset[str]] = frozenset(
    key for cat in RANK_SCALED if (key := CATEGORY_EVIDENCE[cat]) is not None
)

# --- Priors (calibration targets for the usage ledger) ----------------------

# Editorial letter → quality points. Midpoints of five equal bands.
LETTER_QUALITY: Final[dict[str, float]] = {"S": 90.0, "A": 70.0, "B": 50.0, "C": 30.0, "D": 10.0}
# When AA has measured the model: weight on the scaled evidence vs the letter.
EVIDENCE_WEIGHT: Final[float] = 0.7
# A letter with no AA measurement behind it is an editorial prior, not
# evidence: discount it so a measured model wins an otherwise-tied letter.
UNMEASURED_DISCOUNT: Final[float] = 5.0
# Quality a task requires by complexity (in the same 0–100 points); a novel /
# multi-step-proof High task raises the bar to the S band.
REQUIREMENT: Final[dict[str, float]] = {"low": 30.0, "medium": 50.0, "high": 70.0}
REQUIREMENT_NOVEL: Final[float] = 85.0
# Points lost per point of shortfall below the requirement (steep, but soft).
SHORTFALL_SLOPE: Final[float] = 1.5
# Benchmark differences within run-to-run noise, in the scaled evidence's
# points (0–100 across the measured catalog): two candidates this close in a
# category stand level there, and the general measure (the AA Index) decides
# between them. Measured from the cases where AA scores a model lower at a
# higher effort: on its long-context test (LCR) 90% of the 32 such drops fall
# within 5.6 points (about 3 points of LCR); on the other benchmarks they stay
# within about 4.
TIE_BAND: Final[dict[str, float]] = {"long-context": 6.0}
DEFAULT_TIE_BAND: Final[float] = 4.0
# λ: the share of the market's exchange rate K this operator applies to a
# decade of spend. λ = 1 ranks purely by value (the market-line residual, the
# same quantity the /models Score shows); λ → 0 ranks purely by quality. It is
# the product of a budget-posture factor and a stakes factor. With today's
# K ≈ 35 quality points per decade, `balanced` works out to roughly 30 / 18 /
# 10 / 5 points per decade of spend for Low / Medium / High / High+novel — a
# routine task is a value decision, a novel hard one is a quality decision.
BUDGET_LAMBDA: Final[dict[str, float]] = {"cheap": 0.9, "balanced": 0.5, "best": 0.1}
# The stakes scale the cost term: a failed attempt at a hard task costs far
# more (retries, rework, review) than the price gap between two models, so a
# decade of spend weighs less as complexity rises. Multiplies the budget λ.
COMPLEXITY_COST_WEIGHT: Final[dict[str, float]] = {"low": 1.6, "medium": 1.0, "high": 0.55}
NOVEL_COST_WEIGHT: Final[float] = 0.27
# Scarcity: the share of list price a token effectively costs on each funding
# path. Subscription pools: `uncapped` headroom is free; `capped` (default)
# draws a pool the operator can run out of; `tight` / `exhausted` per the
# Usage-pool status table (an exhausted pool's overflow bills at list price).
SCARCITY: Final[dict[str, float]] = {
    "local": 0.0,
    "subscription-uncapped": 0.0,
    "subscription-headroom": 0.35,
    "subscription-tight": 0.7,
    "subscription-exhausted": 1.0,
    "api-key": 1.0,
    "unfunded": 1.0,
}
# Expected output-token multiplier by effort level (Anthropic: higher effort
# "uses more tokens"; the exact ratios are unpublished — measure them).
EFFORT_TOKEN_MULTIPLIER: Final[dict[str, float]] = {
    "low": 0.6,
    "medium": 0.8,
    "high": 1.0,
    "xhigh": 1.6,
    "max": 2.5,
}
# Floor for the cost log so a $0 path is "free", not −∞ (USD per 1M blended).
COST_FLOOR_USD: Final[float] = 0.02
# Last-resort exchange rate when no market fit can be computed at all (quality
# points per decade); a category with no positive slope (speed) first falls
# back to the general-intelligence (planning) fit.
DEFAULT_K: Final[float] = 30.0
# Coding-agent surfaces get a nudge on coding / agentic / planning work (that
# is where roadmap steps run) when costs tie; chat apps and raw APIs do not.
AGENT_SURFACES: Final[frozenset[str]] = frozenset(
    {"claude-code", "codex-cli", "cursor", "gemini-cli", "antigravity"}
)
AGENT_CATEGORIES: Final[frozenset[str]] = frozenset({"coding", "agentic", "planning"})
# Platform tie-break when scores are equal: a paid-for subscription surface,
# then the operator's own hardware, then a pay-per-token key.
FUNDING_PREFERENCE: Final[dict[str, int]] = {
    "subscription": 0,
    "local": 1,
    "api-key": 2,
    "unfunded": 3,
}
# Baseline allowed jurisdictions when the user-context declares none.
BASELINE_JURISDICTIONS: Final[tuple[str, ...]] = ("us", "eu", "uk", "ca", "au", "jp", "kr")

BUNDLED_BENCHMARKS_PATH = resources.files("roadmodel.data") / "benchmarks.json"


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Task:
    category: str
    complexity: str
    novel: bool = False
    budget: str = "balanced"

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}; expected one of {CATEGORIES}")
        if self.complexity not in COMPLEXITIES:
            raise ValueError(
                f"unknown complexity {self.complexity!r}; expected one of {COMPLEXITIES}"
            )
        if self.budget not in BUDGETS:
            raise ValueError(f"unknown budget {self.budget!r}; expected one of {BUDGETS}")


@dataclass
class Candidate:
    model_id: str
    model_name: str
    provider: str
    platform_id: str
    platform_name: str
    funding: str  # local | subscription | api-key | unfunded
    pool_state: str  # uncapped | headroom | tight | exhausted | n/a
    quality: float
    quality_source: str  # "aa:<key>+letter" | "letter"
    letter: str
    requirement: float
    requirement_penalty: float
    blended_price_usd: float
    scarcity: float
    effort: str
    effort_multiplier: float
    effective_cost_usd: float
    cost_decades: float
    cost_penalty: float
    score: float
    notes: list[str] = field(default_factory=list)
    # The effort AA measured the quality evidence at; this candidate runs at
    # it. None: the model's headline figure, at the posture's effort.
    evidence_level: str | None = None
    # The category's evidence on its 0–100 scale (EvidenceScale.points), the
    # figure ties are judged on; None when AA has not measured it there or the
    # category has no evidence (multimodal).
    evidence_points: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Ranking:
    task: Task
    k_points_per_decade: float
    lam: float
    primary: Candidate | None
    backup: Candidate | None
    backup_warning: str | None
    candidates: list[Candidate]
    excluded: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": asdict(self.task),
            "k_points_per_decade": self.k_points_per_decade,
            "lambda": self.lam,
            "primary": self.primary.to_dict() if self.primary else None,
            "backup": self.backup.to_dict() if self.backup else None,
            "backup_warning": self.backup_warning,
            "candidates": [c.to_dict() for c in self.candidates],
            "excluded": self.excluded,
        }


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #


def _load_benchmarks() -> dict[str, Any]:
    try:
        raw = json.loads(BUNDLED_BENCHMARKS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    models = raw.get("models") if isinstance(raw, dict) else None
    return models if isinstance(models, dict) else {}


def with_composites(bench: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``bench`` with each ``COMPOSITES`` key added to the
    evaluations of every row measured on all its parts: the mean of the row's
    mid-rank percentiles on those parts, among those rows (0 = lowest). A
    model's rows at other efforts (``effort_variants``) get the composite too,
    their percentiles taken among the headline rows."""
    out: dict[str, Any] = {}
    for mid, row in bench.items():
        if isinstance(row, dict):
            evals = row.get("evaluations")
            out[mid] = {**row, "evaluations": dict(evals) if isinstance(evals, dict) else {}}
            variants = row.get("effort_variants")
            if isinstance(variants, dict):
                out[mid]["effort_variants"] = dict(variants)
        else:
            out[mid] = row
    for key, parts in COMPOSITES.items():
        rows: dict[str, list[float]] = {}
        for mid, row in out.items():
            if not isinstance(row, dict):
                continue
            vals = [row["evaluations"].get(p) for p in parts]
            if all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in vals):
                rows[mid] = [float(v) for v in vals]
        if not rows:
            continue
        columns = list(zip(*rows.values(), strict=True))
        n = len(rows)
        for mid, values in rows.items():
            # A lone measured model leads its own composite.
            pcts = [
                (sum(1 for x in col if x < v) + (sum(1 for x in col if x == v) - 1) / 2) / (n - 1)
                if n > 1
                else 1.0
                for v, col in zip(values, columns, strict=True)
            ]
            out[mid]["evaluations"][key] = sum(pcts) / len(pcts)
        # A model's row at another effort is placed among the headline rows,
        # so its composite reads on the same scale.
        for row in out.values():
            variants = row.get("effort_variants") if isinstance(row, dict) else None
            if not isinstance(variants, dict):
                continue
            for level, vrow in list(variants.items()):
                if not isinstance(vrow, dict):
                    continue
                evals = dict(vrow.get("evaluations") or {})
                vals = [evals.get(p) for p in parts]
                if not all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in vals):
                    continue
                pcts = [
                    (sum(1 for x in col if x < float(v)) + sum(1 for x in col if x == float(v)) / 2)
                    / len(col)
                    for v, col in zip(vals, columns, strict=True)
                ]
                evals[key] = sum(pcts) / len(pcts)
                variants[level] = {**vrow, "evaluations": evals}
    return out


def measured_levels(bench: dict[str, Any], model_id: str) -> dict[str, dict[str, Any]]:
    """The effort levels AA has measured ``model_id`` at, each with its row:
    the headline row at its own level (``aa_effort``) and every
    ``effort_variants`` row. Empty when AA names no level for the model (the
    row then stands for the model at whatever effort it runs)."""
    row = bench.get(model_id)
    if not isinstance(row, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    variants = row.get("effort_variants")
    if isinstance(variants, dict):
        out.update(
            {str(k): v for k, v in variants.items() if k in EFFORT_LADDER and isinstance(v, dict)}
        )
    level = row.get("aa_effort")
    if isinstance(level, str) and level in EFFORT_LADDER:
        out[level] = row
    return out


def _evidence(
    bench: dict[str, Any], model_id: str, key: str | None, level: str | None = None
) -> float | None:
    """AA's figure ``key`` for ``model_id``: its headline row's, or with
    ``level`` its row at that effort (None when AA has not measured it there)."""
    if key is None:
        return None
    row = bench.get(model_id)
    if not isinstance(row, dict):
        return None
    if level is not None:
        row = measured_levels(bench, model_id).get(level)
        if row is None:
            return None
    if key == "median_output_tokens_per_second":
        v = row.get(key)
    else:
        evals = row.get("evaluations")
        v = evals.get(key) if isinstance(evals, dict) else None
    if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return None
    if key == "median_output_tokens_per_second":
        # AA reports 0 tokens/s for endpoints it has not throughput-tested:
        # "not measured", not a speed (mirrors web/lib/catalog-models.ts).
        return float(v) if float(v) > 0 else None
    # An evaluation's 0 is a measurement: Terminal-Bench 4.0 scores models at
    # 0% of its tasks.
    return float(v)


def blended_price(model: dict[str, Any]) -> float:
    inp = float(model.get("input_price_per_1m") or 0.0)
    out = float(model.get("output_price_per_1m") or 0.0)
    return (3.0 * inp + out) / 4.0


def market_exchange_rate(
    catalog: dict[str, Any],
    bench: dict[str, Any],
    task: Task | None = None,
    scale: EvidenceScale | None = None,
) -> float:
    """K: the market's exchange rate between price and quality, in the SCORE'S
    OWN quality units — the OLS slope of this category's blended quality (the
    same ``_quality`` the score uses) on log10(blended price) over every
    measured catalog model. Fitting on raw AA-index units and applying it to a
    min-max-stretched quality would understate the market line by the stretch
    factor (2× and more), so the fit is done on the stretched values. Falls
    back to ``DEFAULT_K`` when fewer than three models are measured or the
    slope is not positive (speed: faster models are cheaper, so there is no
    market line to anchor on)."""
    if task is None:
        task = Task("planning", "medium")
    bench = with_composites(bench)
    if scale is None:
        scale = _evidence_scale(catalog, bench, CATEGORY_EVIDENCE[task.category])
    xs: list[float] = []
    ys: list[float] = []
    for m in catalog.get("models", []):
        if not isinstance(m, dict):
            continue
        price = blended_price(m)
        if price <= 0:
            continue
        q, source, _letter = _quality(m, task, bench, scale)
        if source == "letter":
            continue
        xs.append(math.log10(price))
        ys.append(q)
    n = len(xs)
    slope: float | None = None
    if n >= 3:
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
        if sxx > 0:
            slope = sxy / sxx
    if slope is not None and slope > 0:
        return slope
    if task.category != "planning":
        # No usable market line in this category (too few measured models, or
        # price and quality anti-correlate as they do for speed): anchor on the
        # general-intelligence fit instead of a raw constant.
        return market_exchange_rate(catalog, bench, Task("planning", task.complexity))
    return DEFAULT_K


# --------------------------------------------------------------------------- #
# User-context readers (bounded regexes over Markdown; the text is untrusted)
# --------------------------------------------------------------------------- #

_HEADROOM_RE: Final = re.compile(
    r"\*\*Consumption headroom:\*\*\s*`?(uncapped|capped)`?", re.IGNORECASE
)
# Both documented forms: the template's fenced ``platforms.allowed:   a, b``
# and the bold ``**platforms.allowed:** `a`, `b```. Values must look like
# access-method ids; prose such as ``(none declared)`` is dropped.
_PLATFORMS_RE: Final = re.compile(
    r"^[ \t]*(?:\*\*)?platforms\.(allowed|excluded)(?:\*\*)?[ \t]*:(?:\*\*)?[ \t]*(.+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_PLATFORM_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# The list may sit on the heading's own line or on the next non-blank line,
# backticked or bare.
_JURIS_RE: Final = re.compile(
    r"\*\*Allowed jurisdictions[^*\n]*\*\*[ \t]*:?[ \t]*\n*[ \t]*`?([a-z]{2,7}(?:[ \t]*,[ \t]*[a-z]{2,7})*)`?",
    re.IGNORECASE,
)
_POOL_STATE_RE: Final = re.compile(r"\b(headroom|tight|exhausted)\b", re.IGNORECASE)
_BUDGET_RE: Final = re.compile(
    r"\*\*Budget priority:\*\*\s*`?(cheap|cost|balanced|best|quality)`?", re.IGNORECASE
)
_BUDGET_ALIASES: Final[dict[str, str]] = {"cost": "cheap", "quality": "best"}


def consumption_headroom(text: str) -> str:
    m = _HEADROOM_RE.search(text)
    return m.group(1).lower() if m else "capped"


def declared_budget(text: str) -> str:
    """The user-context's ``Budget priority`` (cheap / balanced / best), with
    the selector's Cost / Quality labels accepted as aliases; ``balanced`` when
    absent."""
    m = _BUDGET_RE.search(text or "")
    if not m:
        return "balanced"
    value = m.group(1).lower()
    return _BUDGET_ALIASES.get(value, value)


def platform_filters(text: str) -> tuple[set[str], set[str]]:
    allowed: set[str] = set()
    excluded: set[str] = set()
    for kind, rest in _PLATFORMS_RE.findall(text):
        ids = {
            t.strip().strip("`").lower()
            for t in re.split(r"[,\s]+", rest)
            if _PLATFORM_ID_RE.match(t.strip().strip("`").lower())
        }
        (allowed if kind.lower() == "allowed" else excluded).update(ids)
    return allowed, excluded


def allowed_jurisdictions(text: str) -> set[str]:
    m = _JURIS_RE.search(text)
    if not m:
        return set(BASELINE_JURISDICTIONS)
    codes = {c.strip().lower() for c in re.split(r"[,\s]+", m.group(1)) if c.strip()}
    return codes or set(BASELINE_JURISDICTIONS)


# The Resets cell of a Usage-pool row: "Tue 2026-09-22 20:00 EDT", "2026-09-22",
# or free text such as "rolling". Only a dated cell can expire a row.
_RESET_RE: Final = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T]+(\d{1,2}):(\d{2}))?(?:\s*([A-Z]{2,4}))?")
# The zones an operator writes by hand. An unlisted one is NOT guessed at.
_TZ_OFFSETS: Final[dict[str, int]] = {
    "UTC": 0,
    "GMT": 0,
    "Z": 0,
    "EDT": -4,
    "EST": -5,
    "CDT": -5,
    "CST": -6,
    "MDT": -6,
    "MST": -7,
    "PDT": -7,
    "PST": -8,
    "BST": 1,
    "CET": 1,
    "CEST": 2,
}


def _reset_passed(cell: str, now: datetime) -> bool:
    """True only when the Resets cell names a moment that is CERTAINLY past.

    The asymmetry is the point. Keeping a stale `exhausted` row costs
    quality — the selector routes work off a pool that has in fact reset
    (seen 2026-09-22: every coding step went to Codex a day after Claude's
    weekly pool rolled). Wrongly expiring a LIVE row costs money — an
    exhausted pool's overflow bills at list price, the failure that burned
    ~$500 in a day. So anything unreadable keeps its declared state, and a
    time in an unrecognised zone must be a full day past before it counts."""
    m = _RESET_RE.search(cell or "")
    if not m:
        return False
    try:
        day = datetime.strptime(m.group(1), "%Y-%m-%d")
    except ValueError:
        return False
    hour, minute, zone = m.group(2), m.group(3), (m.group(4) or "").upper()
    if hour is None:
        # A bare date: the reset is at some point that day, in some zone.
        return now >= day.replace(tzinfo=timezone.utc) + timedelta(days=2)
    local = day.replace(hour=int(hour), minute=int(minute))
    if zone in _TZ_OFFSETS:
        at = local.replace(tzinfo=timezone(timedelta(hours=_TZ_OFFSETS[zone])))
        return now >= at
    return now >= local.replace(tzinfo=timezone.utc) + timedelta(days=1)


def pool_states(text: str, *, now: datetime | None = None) -> list[tuple[str, str, str]]:
    """Rows of the ``Usage-pool status`` table as (pool name, state, notes).
    The State cell may be decorated (backticks, bold, a trailing note); the
    first headroom / tight / exhausted word wins.

    A `tight` / `exhausted` row whose Resets time has passed reads as
    `headroom`: the operator writes the row when a cap binds and cannot be
    relied on to flip it back when the window rolls, so the table must not
    outlive its own reset. The note records why, for the audit line."""
    now = now or datetime.now(timezone.utc)
    section = _cost._extract_section(text, "Usage-pool status")
    rows: list[tuple[str, str, str]] = []
    for row in _cost._parse_markdown_table(section):
        if len(row) < 3:
            continue
        name = row[0].strip()
        m = _POOL_STATE_RE.search(row[2])
        notes = row[4].strip() if len(row) > 4 else ""
        if not m or name.lower() == "pool":
            continue
        state = m.group(1).lower()
        reset = row[3].strip() if len(row) > 3 else ""
        if state in ("tight", "exhausted") and _reset_passed(reset, now):
            notes = f"declared {state}, but its reset ({reset}) has passed"
            state = "headroom"
        rows.append((name, state, notes))
    return rows


_PLAN_WORDS: Final[frozenset[str]] = frozenset(
    {"max", "pro", "plus", "ultra", "go", "team", "premium"}
)


def _family_words(catalog: dict[str, Any]) -> set[str]:
    """Lower-case first words of catalog model names ("fable", "opus", "gpt-5.6",
    …) — the vocabulary a pool row uses to scope itself to one model family."""
    words: set[str] = set()
    for m in catalog.get("models", []):
        if not isinstance(m, dict):
            continue
        first = str(m.get("name", "")).split(" ")[0].strip().lower()
        if len(first) >= 3:
            words.add(first)
    return words


def _pool_state_for(
    tier: dict[str, Any] | None,
    pools: list[tuple[str, str, str]],
    *,
    model_name: str = "",
    family_words: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, str]:
    """Worst declared state among pool rows that belong to this subscription
    tier, and that row's notes. A row belongs to the tier when its name
    contains the tier's name minus its price tag (a "claude.ai Max — weekly"
    row matches "claude.ai Max ($200)"), or names the provider together with a
    plan word ("Anthropic Max weekly"). A row that names a model family ("…
    Fable 50% sub-cap") applies only to models of that family. Unknown →
    headroom."""
    if tier is None or not pools:
        return "headroom", ""
    tier_name = str(tier.get("tier", "")).lower()
    provider = str(tier.get("provider", "")).lower()
    stem = _cost._canonical_tier_name(tier_name)
    order = {"headroom": 0, "tight": 1, "exhausted": 2}
    model_low = model_name.lower()
    worst, worst_notes = "headroom", ""
    for name, state, notes in pools:
        low = name.lower()
        tokens = set(re.split(r"[^a-z0-9.]+", low))
        by_stem = bool(stem) and stem in low
        by_provider = bool(provider) and provider in tokens and bool(tokens & _PLAN_WORDS)
        if not (by_stem or by_provider):
            continue
        scoped = tokens & set(family_words)
        if scoped and not any(w in model_low for w in scoped):
            continue  # a row about another model family on the same tier
        if order[state] > order[worst]:
            worst, worst_notes = state, notes
    return worst, worst_notes


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def effort_for(task: Task, headroom: str, scarcity: float) -> str:
    """The complexity ladder (the selector's <thinking-context> rule), with
    the same adjustments the prose makes: cross-cutting planning / knowledge
    bump one rung; `best` bumps one rung; `cheap` on a path that costs
    something drops one; `uncapped` headroom on a free path raises to max."""
    rung = {"low": 0, "medium": 1, "high": 2}[task.complexity]
    if task.complexity == "high" and task.novel:
        rung = 3
    if task.category in {"planning", "knowledge"} and task.complexity != "low":
        rung += 1
    if task.budget == "best":
        rung += 1
    if task.budget == "cheap" and scarcity > 0:
        rung -= 1
    free = headroom == "uncapped" and scarcity == 0
    if free:
        rung = 4
    rung = max(0, min(4 if free else 3, rung))
    return EFFORT_LADDER[rung]


def normalize_level(value: str) -> str:
    """An effort level name compared case- and spacing-free: "XHigh",
    "x-high" and "Extra high" are all ``xhigh``."""
    level = re.sub(r"[\s_-]+", "", value.strip().lower())
    return {"extrahigh": "xhigh"}.get(level, level)


def native_levels(
    platform: str, model: str, *, catalog: dict[str, Any] | None = None
) -> list[str] | None:
    """The levels ``platform``'s effort dial offers for ``model``, lowest
    first, as the catalog records them from that surface's own docs: the
    method's ``effort_levels_by_model`` entry where its docs distinguish
    models (a model they leave out has no documented dial), else its
    ``effort_levels``. None when the catalog documents no dial; the engine
    then maps the scorer's level to the surface itself."""
    cat = catalog if catalog is not None else _cost._load_catalog()
    for method in cat.get("access_methods", []):
        if not isinstance(method, dict) or method.get("id") != platform:
            continue
        by_model = method.get("effort_levels_by_model")
        levels = by_model.get(model) if isinstance(by_model, dict) else method.get("effort_levels")
        if isinstance(levels, list) and levels and all(isinstance(x, str) for x in levels):
            return list(levels)
        return None
    return None


def native_level(
    platform: str, model: str, scorer_level: str, *, catalog: dict[str, Any] | None = None
) -> str | None:
    """The level to set on ``platform``'s dial for ``model`` when the scorer
    says ``scorer_level``: the native level of that name, else the highest
    native level below it, else the dial's lowest. None when the catalog
    documents no dial for the pair."""
    levels = native_levels(platform, model, catalog=catalog)
    if not levels:
        return None
    want = normalize_level(scorer_level)
    for level in levels:
        if normalize_level(level) == want:
            return level
    order = {name: i for i, name in enumerate(LEVEL_ORDER)}
    if want in order:
        below = [lv for lv in levels if order.get(normalize_level(lv), len(order)) < order[want]]
        if below:
            return max(below, key=lambda lv: order[normalize_level(lv)])
    return levels[0]


def _scorer_level(native: str) -> str:
    """The scorer level a native level stands for: the highest of
    EFFORT_LADDER at or below it, floored at ``low`` (Gemini's ``minimal``)
    and capped at ``max`` (Codex's ``ultra``)."""
    level = normalize_level(native)
    if level in EFFORT_LADDER:
        return level
    order = {name: i for i, name in enumerate(LEVEL_ORDER)}
    rank = order.get(level)
    if rank is None:
        return EFFORT_LADDER[0]
    at_or_below = [e for e in EFFORT_LADDER if order[e] <= rank]
    return at_or_below[-1] if at_or_below else EFFORT_LADDER[0]


def _quality(
    model: dict[str, Any],
    task: Task,
    bench: dict[str, Any],
    scale: EvidenceScale | None,
    level: str | None = None,
) -> tuple[float, str, str]:
    """The model's quality for the task's category: its headline evidence, or
    with ``level`` its evidence at that effort, blended with its letter."""
    raw_tiers = model.get("tiers")
    tiers: dict[str, Any] = raw_tiers if isinstance(raw_tiers, dict) else {}
    letter = str(tiers.get(task.category, "C")).upper()
    letter_q = LETTER_QUALITY.get(letter, 30.0)
    if scale is None:
        # No evidence exists for this category at all (multimodal): every model
        # is on its letter, so there is nothing to discount against.
        return letter_q, "letter", letter
    points = _evidence_points(str(model.get("id", "")), task, bench, scale, level)
    if points is None:
        return max(0.0, letter_q - UNMEASURED_DISCOUNT), "letter", letter
    q = EVIDENCE_WEIGHT * points + (1.0 - EVIDENCE_WEIGHT) * letter_q
    return q, f"aa:{CATEGORY_EVIDENCE[task.category]}+letter", letter


def _evidence_points(
    model_id: str,
    task: Task,
    bench: dict[str, Any],
    scale: EvidenceScale | None,
    level: str | None = None,
) -> float | None:
    """The category's evidence for ``model_id`` (at ``level`` when given) on
    its 0–100 scale, or None when unmeasured or the category has none."""
    if scale is None:
        return None
    key = CATEGORY_EVIDENCE[task.category]
    # Throughput is the endpoint's at any effort (AA leaves it unmeasured on
    # most of a model's other-effort rows, and its figures there are noise):
    # speed reads the headline row's.
    at = None if key == "median_output_tokens_per_second" else level
    v = _evidence(bench, model_id, key, at)
    return None if v is None else scale.points(v)


@dataclass(frozen=True)
class EvidenceScale:
    """Maps a raw AA figure onto 0–100 quality points across the measured
    catalog: min-max between ``lo`` and ``hi``, or, for a ``RANK_SCALED``
    category, the figure's mean rank among ``ranked`` (sorted ascending; ties
    share their mean rank), from 0 for the lowest to 100 for the highest."""

    lo: float
    hi: float
    ranked: tuple[float, ...] = ()

    def points(self, v: float) -> float:
        if self.ranked:
            below = sum(1 for x in self.ranked if x < v)
            tied = sum(1 for x in self.ranked if x == v)
            return 100.0 * (below + (tied - 1) / 2) / (len(self.ranked) - 1)
        return max(0.0, min(100.0, 100.0 * (v - self.lo) / (self.hi - self.lo)))


def _evidence_scale(
    catalog: dict[str, Any], bench: dict[str, Any], key: str | None
) -> EvidenceScale | None:
    """None when fewer than three catalog models are measured or they all score
    the same: every model then stands on its letter."""
    if key is None:
        return None
    vals = [
        v
        for m in catalog.get("models", [])
        if isinstance(m, dict)
        for v in [_evidence(bench, str(m.get("id", "")), key)]
        if v is not None
    ]
    if len(vals) < 3 or max(vals) <= min(vals):
        return None
    ranked = tuple(sorted(vals)) if key in _RANK_SCALED_KEYS else ()
    return EvidenceScale(min(vals), max(vals), ranked)


def _funding_for(
    method: dict[str, Any],
    catalog: dict[str, Any],
    text: str,
    headroom: str,
    pools: list[tuple[str, str, str]],
    *,
    model_name: str = "",
    family_words: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, str, float, str]:
    """(funding class, pool state, scarcity, note) for one access method."""
    kind, tier = _cost._resolve_funding(method, catalog, text)
    if kind == _cost.FUNDING_LOCAL:
        return "local", "n/a", SCARCITY["local"], ""
    if kind == _cost.FUNDING_UNFUNDED_LOCAL:
        return "unfunded", "n/a", SCARCITY["unfunded"], "local runtime or model not declared"
    if kind == "per-token":
        # `_resolve_funding` says per-token both for a real per-token method and
        # for a subscription surface the user holds no plan/key for; tell them
        # apart by the method's own billing.
        if str(method.get("billing", "")) == "per-token":
            api_keys = _cost._parse_active_api_keys(text)
            if api_keys.get(str(method.get("provider", "")).lower(), False):
                return "api-key", "n/a", SCARCITY["api-key"], ""
            return "unfunded", "n/a", SCARCITY["unfunded"], "no API key declared"
        return "unfunded", "n/a", SCARCITY["unfunded"], "no subscription or key declared"
    if tier is None:
        # subscription-or-key satisfied by an API key.
        return "api-key", "n/a", SCARCITY["api-key"], ""
    state, notes = _pool_state_for(tier, pools, model_name=model_name, family_words=family_words)
    if state == "exhausted" and "overflow off" in notes.lower():
        api_keys = _cost._parse_active_api_keys(text)
        if str(method.get("billing", "")) == "subscription-or-key" and api_keys.get(
            str(method.get("provider", "")).lower(), False
        ):
            return (
                "api-key",
                "exhausted",
                SCARCITY["api-key"],
                "pool exhausted (overflow off): running on the declared key at list price",
            )
        return "unfunded", "exhausted", SCARCITY["unfunded"], "pool exhausted, overflow off"
    if state == "exhausted":
        return (
            "subscription",
            "exhausted",
            SCARCITY["subscription-exhausted"],
            "pool exhausted: overflow bills at list price",
        )
    if state == "tight":
        return "subscription", "tight", SCARCITY["subscription-tight"], "pool tight"
    if headroom == "uncapped":
        return "subscription", "uncapped", SCARCITY["subscription-uncapped"], ""
    return "subscription", "headroom", SCARCITY["subscription-headroom"], ""


def _platform_key(c: Candidate) -> tuple[bool, float, int, int, str]:
    return (
        c.funding == "unfunded",
        -c.score,
        FUNDING_PREFERENCE.get(c.funding, 3),
        0 if c.platform_id in AGENT_SURFACES else 1,
        c.platform_id,
    )


def rank(
    task: Task,
    user_context_text: str,
    *,
    unavailable_models: list[str] | None = None,
    catalog: dict[str, Any] | None = None,
    benchmarks: dict[str, Any] | None = None,
    top: int | None = None,
) -> Ranking:
    """Rank every reachable (model, platform) pair for ``task``."""
    cat = catalog if catalog is not None else _cost._load_catalog()
    bench = with_composites(benchmarks if benchmarks is not None else _load_benchmarks())
    text = user_context_text or ""
    headroom = consumption_headroom(text)
    pools = pool_states(text)
    allowed_p, excluded_p = platform_filters(text)
    juris = allowed_jurisdictions(text)
    unavailable = {m.strip() for m in (unavailable_models or [])}
    scale = _evidence_scale(cat, bench, CATEGORY_EVIDENCE[task.category])
    k = market_exchange_rate(cat, bench, task, scale)
    lam = BUDGET_LAMBDA[task.budget] * (
        NOVEL_COST_WEIGHT
        if (task.novel and task.complexity == "high")
        else COMPLEXITY_COST_WEIGHT[task.complexity]
    )
    requirement = (
        REQUIREMENT_NOVEL
        if (task.novel and task.complexity == "high")
        else REQUIREMENT[task.complexity]
    )

    methods = [m for m in cat.get("access_methods", []) if isinstance(m, dict)]
    method_ids = {str(m.get("id", "")) for m in methods}
    families = frozenset(_family_words(cat))
    catalog_ids = {str(m.get("id", "")) for m in cat.get("models", []) if isinstance(m, dict)}
    candidates: list[Candidate] = []
    excluded: list[dict[str, str]] = []
    # A platform list is only as good as its ids: unknown tokens are reported
    # and ignored, and a list with no known id is treated as undeclared rather
    # than as "allow nothing".
    for label, ids in (("platforms.allowed", allowed_p), ("platforms.excluded", excluded_p)):
        for unknown in sorted(ids - method_ids):
            excluded.append(
                {"model": "", "reason": f"unknown access-method id in {label}: {unknown}"}
            )
    allowed_p &= method_ids
    excluded_p &= method_ids

    for model in cat.get("models", []):
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", ""))
        if not model_id:
            continue
        if model_id in unavailable:
            excluded.append({"model": model_id, "reason": "unavailable"})
            continue
        # The successor is the same maker's, no dearer, and rated at least as
        # high everywhere; a benched successor keeps the older model in play.
        successor = str(model.get("superseded_by") or "")
        if successor and successor in catalog_ids and successor not in unavailable:
            excluded.append({"model": model_id, "reason": f"superseded by {successor}"})
            continue
        if str(model.get("jurisdiction", "")).lower() not in juris:
            excluded.append({"model": model_id, "reason": "jurisdiction"})
            continue
        provider = _cost.model_provider(model_id) or str(model.get("provider", "unknown"))
        quality, source, letter = _quality(model, task, bench, scale)
        points = _evidence_points(model_id, task, bench, scale)
        shortfall = max(0.0, requirement - quality)
        penalty = SHORTFALL_SLOPE * shortfall
        price = blended_price(model)

        best_for_model: Candidate | None = None
        for method in methods:
            supports = method.get("supports_models") or method.get("supports-models") or []
            if model_id not in supports:
                continue
            pid = str(method.get("id", ""))
            if allowed_p and pid not in allowed_p:
                continue
            if pid in excluded_p:
                continue
            pj = str(method.get("provider_jurisdiction", "us")).lower()
            if pj != "local" and pj not in juris:
                continue  # `local` runs on the operator's hardware: passes every list
            if task.category == "speed" and str(method.get("billing", "")) == "local":
                # Speed evidence is the hosted providers' measured throughput;
                # the operator's own hardware runs at its own, unmeasured pace.
                continue
            funding, state, scarcity, note = _funding_for(
                _cost._with_model(method, model_id),
                cat,
                text,
                headroom,
                pools,
                model_name=str(model.get("name", model_id)),
                family_words=families,
            )
            effort = effort_for(task, headroom, scarcity)
            mult = EFFORT_TOKEN_MULTIPLIER[effort]
            eff_cost = price * scarcity * mult
            decades = math.log10(max(eff_cost, COST_FLOOR_USD) / COST_FLOOR_USD)
            cost_pen = lam * k * decades
            score = quality - penalty - cost_pen
            notes = [n for n in [note] if n]
            if funding == "unfunded":
                notes.append("UNFUNDED: not reachable with the declared subscriptions / keys")
            if task.category in AGENT_CATEGORIES and pid in AGENT_SURFACES:
                score += 0.5  # coding-agent surface nudge on an otherwise-tied cost
                notes.append("coding-agent surface")
            c = Candidate(
                model_id=model_id,
                model_name=str(model.get("name", model_id)),
                provider=provider,
                platform_id=pid,
                platform_name=str(method.get("name", pid)),
                funding=funding,
                pool_state=state,
                quality=round(quality, 2),
                quality_source=source,
                letter=letter,
                requirement=requirement,
                requirement_penalty=round(penalty, 2),
                blended_price_usd=round(price, 4),
                scarcity=scarcity,
                effort=effort,
                effort_multiplier=mult,
                effective_cost_usd=round(eff_cost, 4),
                cost_decades=round(decades, 3),
                cost_penalty=round(cost_pen, 2),
                score=round(score, 2),
                notes=notes,
                evidence_points=None if points is None else round(points, 2),
            )
            # One row per model: its best reachable platform. A funded platform
            # always beats an unfunded one regardless of score; equal scores go
            # to the subscription surface over a key, then to the agent surface.
            if best_for_model is None or _platform_key(c) < _platform_key(best_for_model):
                best_for_model = c
        if best_for_model is None:
            excluded.append(
                {"model": model_id, "reason": "no platform reaches it under the filters"}
            )
            continue
        candidates.append(best_for_model)

    # Funded first, then score, then cheaper, then id — deterministic.
    candidates.sort(
        key=lambda c: (c.funding == "unfunded", -c.score, c.effective_cost_usd, c.model_id)
    )
    primary = candidates[0] if candidates else None
    backup: Candidate | None = None
    warning: str | None = None
    if primary is not None:
        for c in candidates[1:]:
            if c.provider != primary.provider and c.funding != "unfunded":
                backup = c
                break
        if backup is None:
            funded_providers = sorted({c.provider for c in candidates if c.funding != "unfunded"})
            warning = (
                "No cross-provider backup: the user-context funds only "
                f"{', '.join(funded_providers) or 'nothing'}. Add a second subscription or "
                "API key so an outage or an exhausted pool has somewhere to go."
            )
    if top is not None:
        candidates = candidates[: max(0, top)]
    return Ranking(
        task=task,
        k_points_per_decade=round(k, 2),
        lam=lam,
        primary=primary,
        backup=backup,
        backup_warning=warning,
        candidates=candidates,
        excluded=excluded,
    )


# --------------------------------------------------------------------------- #
# The Cost / Balanced / Quality ladder, read off the operator's own frontier
# --------------------------------------------------------------------------- #

LADDER_TIERS: Final[tuple[str, ...]] = ("cost", "balanced", "quality")
# The posture each rung's effort follows (effort_for).
TIER_BUDGET: Final[dict[str, str]] = {"cost": "cheap", "balanced": "balanced", "quality": "best"}
# The frontier's quality axis: the figure /models and /recommend plot.
FRONTIER_INDEX: Final[str] = "artificial_analysis_intelligence_index"


@dataclass(frozen=True)
class FrontierPoint:
    candidate: Candidate
    # The AA Intelligence Index; every frontier point has one, and only a
    # category specialist (off the frontier) may be unmeasured.
    aa_index: float | None
    # Blended list $/1M, the price /models plots. List price, not what the
    # operator pays: on a subscription every covered model costs them $0, which
    # would collapse the frontier to its top model; list price is what a pick
    # draws from a capped pool, and where the steps in capability are.
    price_usd: float


@dataclass(frozen=True)
class Backup:
    """A rung's cross-maker substitute, read off the frontier of the other
    makers' models (see :func:`ladder`)."""

    point: FrontierPoint
    effort: str
    native: str | None = None

    @property
    def candidate(self) -> Candidate:
        return self.point.candidate

    @property
    def level(self) -> str:
        return self.native or self.effort


@dataclass(frozen=True)
class Rung:
    tier: str
    point: FrontierPoint
    # The scorer's level (EFFORT_LADDER) this rung runs at.
    effort: str
    # The same level as the platform's own dial names it (native_level), or
    # None when the catalog documents no dial for the platform and model.
    native: str | None = None
    # The best cross-maker substitute at no higher list price; None when the
    # pool holds no other maker's model.
    backup: Backup | None = None
    # True for a QUALITY rung held by a category specialist off the frontier.
    specialist: bool = False

    @property
    def candidate(self) -> Candidate:
        return self.point.candidate

    @property
    def level(self) -> str:
        """The level the operator sets: the native word, else the scorer's."""
        return self.native or self.effort


@dataclass
class Ladder:
    task: Task
    # The operator's frontier over their models, as /models draws it: each at
    # its headline AA Index and list price.
    frontier: list[FrontierPoint]
    # Points whose quality in the task's category meets the complexity's
    # requirement, cheapest first, from ``points``.
    adequate: list[FrontierPoint]
    rungs: dict[str, Rung]
    # Why a rung has no backup: the pool holds no other maker's model.
    backup_warning: str | None = None
    # The frontier the rungs are read from: each model at every effort AA
    # measured it at (:func:`effort_settings`). Equals ``frontier`` when no
    # model carries per-effort figures.
    points: list[FrontierPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def point(p: FrontierPoint) -> dict[str, Any]:
            c = p.candidate
            return {
                "model_id": c.model_id,
                "model_name": c.model_name,
                "platform_id": c.platform_id,
                "platform_name": c.platform_name,
                "aa_index": p.aa_index,
                "price_usd": p.price_usd,
                "list_price_usd": c.blended_price_usd,
                "quality": c.quality,
                "evidence_level": c.evidence_level,
            }

        return {
            "task": asdict(self.task),
            "frontier": [point(p) for p in self.frontier],
            "points": [point(p) for p in self.points],
            "adequate": list(dict.fromkeys(p.candidate.model_id for p in self.adequate)),
            "rungs": {
                t: {
                    **point(r.point),
                    "effort": r.effort,
                    "native_effort": r.native,
                    "specialist": r.specialist,
                    "backup": (
                        {
                            **point(r.backup.point),
                            "effort": r.backup.effort,
                            "native_effort": r.backup.native,
                        }
                        if r.backup is not None
                        else None
                    ),
                }
                for t, r in self.rungs.items()
            },
            "backup_warning": self.backup_warning,
        }


def frontier_price(c: Candidate) -> float:
    """Where ``c`` sits on the frontier's price axis: the blended list price,
    times its effort's token multiplier when it runs at a measured effort (a
    higher effort draws more tokens of the same model)."""
    if c.evidence_level is None:
        return c.blended_price_usd
    return round(c.blended_price_usd * EFFORT_TOKEN_MULTIPLIER[c.evidence_level], 4)


def frontier(candidates: list[Candidate], bench: dict[str, Any]) -> list[FrontierPoint]:
    """The cost/quality frontier over ``candidates``, cheapest first: every
    candidate that scores higher on the AA Intelligence Index than every one
    at its price or less. The rule web/lib/benchmark-grid.ts paretoFrontier
    draws on /models: a tie on price goes to the higher index, a tie on index to
    the cheaper price. Unmeasured models have no place on it.

    A candidate at a measured effort (``evidence_level``) is placed by its
    index at that effort and its :func:`frontier_price`, so one model can
    hold several points, one per effort worth its price."""
    measured = [
        (c, aa)
        for c in candidates
        for aa in [_evidence(bench, c.model_id, FRONTIER_INDEX, c.evidence_level)]
        if aa is not None
    ]
    measured.sort(key=lambda m: (frontier_price(m[0]), -m[1], m[0].model_id))
    out: list[FrontierPoint] = []
    best = -math.inf
    for c, aa in measured:
        if aa > best:
            out.append(FrontierPoint(c, aa, frontier_price(c)))
            best = aa
    return out


def _strength(p: FrontierPoint) -> tuple[float, float, float]:
    """A point's standing for the task's category: its category quality, then
    the AA Index, then the cheaper price."""
    return (p.candidate.quality, -1.0 if p.aa_index is None else p.aa_index, -p.price_usd)


def _nearest(p: FrontierPoint) -> tuple[float, float, float, float]:
    """With no point meeting the task's bar: the one that falls shortest of
    it (in its category or in general capability), then the strongest."""
    return (-p.candidate.requirement_penalty, *_strength(p))


def _level_with(a: Candidate, b: Candidate, category: str) -> bool:
    """Whether ``a`` stands at least level with ``b`` in the category: its
    evidence no more than the noise band (``TIE_BAND``) below ``b``'s, or,
    where either is unmeasured there, its quality no lower."""
    if a.evidence_points is None or b.evidence_points is None:
        return a.quality >= b.quality
    return a.evidence_points >= b.evidence_points - TIE_BAND.get(category, DEFAULT_TIE_BAND)


def _tie_break(p: FrontierPoint, category: str) -> tuple[float, float, float]:
    """Between points level in the category: the higher AA Index, then the
    cheaper. On speed work the lower effort comes first: throughput is the
    same at every effort, and more reasoning only delays the answer."""
    slower = 0.0
    if category == "speed":
        level = p.candidate.evidence_level or p.candidate.effort
        slower = -float(EFFORT_LADDER.index(level)) if level in EFFORT_LADDER else 0.0
    return (slower, -1.0 if p.aa_index is None else p.aa_index, -p.price_usd)


def _top(points: list[FrontierPoint], category: str) -> FrontierPoint:
    """The strongest point for the category: of those level with its leader
    there (:func:`_level_with`), the one ahead on :func:`_tie_break`. A
    difference within run-to-run noise does not decide it."""
    leader = max(points, key=_strength)
    level = [p for p in points if _level_with(p.candidate, leader.candidate, category)]
    return max(level, key=lambda p: _tie_break(p, category))


# Letters from weakest to strongest.
LETTER_ORDER: Final[str] = "DCBAS"
# Categories whose evidence is something other than the AA Intelligence Index,
# the frontier's own axis: there a model off the frontier can be clearly
# stronger for the category (every category but planning).
SPECIALIST_CATEGORIES: Final[frozenset[str]] = frozenset(
    cat for cat, key in CATEGORY_EVIDENCE.items() if key != FRONTIER_INDEX
)


def _specialist(
    task: Task,
    pool: list[Candidate],
    front: list[FrontierPoint],
    top: FrontierPoint,
    bench: dict[str, Any],
) -> FrontierPoint | None:
    """A category specialist for QUALITY: the pool model off the frontier
    whose letter in the task's category is strictly above that of ``top``
    (the strongest adequate frontier point) and whose category quality is
    strictly above it too, and that meets the task's bar itself; the
    strongest such model, else None. Only for SPECIALIST_CATEGORIES."""
    if task.category not in SPECIALIST_CATEGORIES:
        return None
    on_front = {p.candidate.model_id for p in front}
    rank = LETTER_ORDER.find
    t = top.candidate
    stronger = [
        c
        for c in pool
        if c.model_id not in on_front
        and c.requirement_penalty == 0
        and rank(c.letter) > rank(t.letter)
        and c.quality > t.quality
        and not _level_with(t, c, task.category)
    ]
    if not stronger:
        return None

    def aa(c: Candidate) -> float:
        v = _evidence(bench, c.model_id, FRONTIER_INDEX, c.evidence_level)
        return -1.0 if v is None else v

    # A category with no AA evidence (multimodal) rates a model's every effort
    # alike there; the stronger effort overall then takes QUALITY.
    best = max(
        stronger, key=lambda c: (c.quality, rank(c.letter), aa(c), -frontier_price(c), c.model_id)
    )
    return FrontierPoint(best, aa(best) if aa(best) >= 0 else None, frontier_price(best))


def _allowed_levels(c: Candidate, task: Task, headroom: str, catalog: dict[str, Any]) -> list[str]:
    """The scorer levels a pick on ``c``'s path may run at, lowest first: its
    platform's dial (every scorer level where the catalog documents none), up
    to the effort the best posture would run (:func:`effort_for`), which keeps
    a capped pool below max. A free path runs at the top only."""
    ceiling = EFFORT_LADDER.index(effort_for(replace(task, budget="best"), headroom, c.scarcity))
    dial = native_levels(c.platform_id, c.model_id, catalog=catalog)
    levels = dict.fromkeys(_scorer_level(n) for n in dial) if dial else dict.fromkeys(EFFORT_LADDER)
    return [lv for lv in levels if EFFORT_LADDER.index(lv) <= ceiling]


def _at_level(
    c: Candidate,
    level: str | None,
    model: dict[str, Any],
    task: Task,
    bench: dict[str, Any],
    scales: tuple[EvidenceScale | None, EvidenceScale | None],
    ranking: Ranking,
) -> Candidate:
    """``c`` run at ``level`` (None: its headline row, at the posture's
    effort): quality from AA's row at that effort, and the requirement
    penalty, effective cost and balanced-posture score that follow from it.

    The complexity's bar applies twice, in the task's category and in general
    capability (the AA Intelligence Index, the planning measure): a hard task
    needs a capable model as well as one that does its kind of work. A
    category benchmark can saturate (on AA's long-context test most current
    models score 74–85%, and an A-rated model clears the bar for hard work
    from about 72%), and only the general figure then says a low-effort small
    model is not up to it.
    ``scales`` are the category's evidence scale and the planning one."""
    quality, source, letter = _quality(model, task, bench, scales[0], level)
    points = _evidence_points(c.model_id, task, bench, scales[0], level)
    general, _, _ = _quality(model, replace(task, category="planning"), bench, scales[1], level)
    penalty = SHORTFALL_SLOPE * max(0.0, c.requirement - min(quality, general))
    if level is None:
        # The headline row: only the general bar can change the candidate.
        if round(penalty, 2) == c.requirement_penalty:
            return c
        return replace(
            c,
            requirement_penalty=round(penalty, 2),
            score=round(c.score + c.requirement_penalty - penalty, 2),
        )
    mult = EFFORT_TOKEN_MULTIPLIER[level]
    eff_cost = c.blended_price_usd * c.scarcity * mult
    decades = math.log10(max(eff_cost, COST_FLOOR_USD) / COST_FLOOR_USD)
    cost_pen = ranking.lam * ranking.k_points_per_decade * decades
    nudge = 0.5 if task.category in AGENT_CATEGORIES and c.platform_id in AGENT_SURFACES else 0.0
    return replace(
        c,
        quality=round(quality, 2),
        quality_source=f"{source}@{level}",
        letter=letter,
        requirement_penalty=round(penalty, 2),
        effort=level,
        effort_multiplier=mult,
        effective_cost_usd=round(eff_cost, 4),
        cost_decades=round(decades, 3),
        cost_penalty=round(cost_pen, 2),
        score=round(quality - penalty - cost_pen + nudge, 2),
        evidence_level=level,
        evidence_points=None if points is None else round(points, 2),
    )


def effort_settings(
    pool: list[Candidate],
    task: Task,
    headroom: str,
    ranking: Ranking,
    *,
    catalog: dict[str, Any],
    benchmarks: dict[str, Any],
) -> list[Candidate]:
    """Every pool model at each effort it may run at (:func:`_allowed_levels`)
    that AA has measured it at, its quality and score read at that effort
    (:func:`_at_level`). A model's benchmark figures move with its effort
    (GPT-6 Luna reads 21.5 on the AA Index at low and 38.1 at max), so a pick
    is credited with what it scores at the effort it runs. A model AA names
    no effort for keeps its headline row and the posture's effort; one AA
    measured only at other efforts is left out."""
    models = {str(m.get("id", "")): m for m in catalog.get("models", []) if isinstance(m, dict)}
    bench = with_composites(benchmarks)
    scales = (
        _evidence_scale(catalog, bench, CATEGORY_EVIDENCE[task.category]),
        _evidence_scale(catalog, bench, CATEGORY_EVIDENCE["planning"]),
    )
    out: list[Candidate] = []
    for c in pool:
        model = models.get(c.model_id)
        if model is None:
            out.append(c)
            continue
        measured = measured_levels(benchmarks, c.model_id)
        levels: list[str | None] = [
            lv for lv in _allowed_levels(c, task, headroom, catalog) if lv in measured
        ]
        if measured and not levels:
            # Measured only at efforts this task does not run (Muse Spark 1.3
            # at xhigh and max, on a row capped at medium): nothing says how it
            # does at the ones it would.
            continue
        if headroom == "uncapped" and c.scarcity == 0:
            levels = levels[-1:]  # a free path runs at its top effort
        out.extend(
            _at_level(c, lv, model, task, bench, scales, ranking) for lv in (levels or [None])
        )
    return out


def ladder(
    task: Task,
    user_context_text: str,
    *,
    unavailable_models: list[str] | None = None,
    catalog: dict[str, Any] | None = None,
    benchmarks: dict[str, Any] | None = None,
) -> Ladder | None:
    """The Cost / Balanced / Quality picks for ``task``, read off the
    operator's own cost/quality frontier.

    - Pool: :func:`rank`'s candidates, every hard filter applied, one per model
      on its best platform; the funded ones, or all of them when the
      user-context funds nothing (an anonymous caller sees the whole catalog).
    - Frontier: :func:`frontier` over the pool, at list price (``frontier``,
      as /models draws it), and over each pool model at every effort it may
      run that AA measured (:func:`effort_settings`, ``points``): the picks
      are read off the latter.
    - Adequate: points that meet the complexity's requirement in the task's
      category and in general capability (:func:`_at_level`); when none does,
      the one that falls shortest of it stands alone.
    - QUALITY is the adequate point that scores highest in the category (then
      the higher AA Index, then the cheaper). COST is the cheapest adequate
      point the operator has already paid for (a subscription with headroom,
      or local weights); a per-token point takes COST only when no prepaid
      point is adequate. BALANCED is the point strictly between them, stronger
      than COST in the task's category, with the best score at the balanced
      posture, a prepaid point ahead of any per-token one; with none, the COST
      or QUALITY model at the balanced posture's effort, whichever differs
      from both other rungs.
    - Each rung runs at its point's measured effort, else at
      :func:`effort_for` its posture (cheap / balanced / best), set on its
      platform's own dial (:func:`native_level`) where the catalog documents
      one. A lower rung on the same model and platform as
      the rung above runs at least one effort level below it
      (:func:`_below`), so the three picks stay distinct; at the dial's lowest
      level they may converge. On an `uncapped` pool every free rung runs at
      the top effort and two rungs on one model converge: a lower effort saves
      that operator nothing.
    - A category specialist (:func:`_specialist`) may take QUALITY in a
      category whose evidence is not the AA Index: a pool model off the
      frontier whose letter and category quality are both strictly above
      the strongest adequate frontier point's and that meets the bar itself.
      COST and BALANCED stay on the frontier, BALANCED then spanning every
      adequate point above COST.
    - Each rung carries a BACKUP from another maker (:func:`_backup_for`):
      the cheapest point on the other makers' frontier that does the job as
      well as the rung, else the nearest below it. ``backup_warning`` says why
      a rung has none.

    None when no pool model carries an AA Index (no frontier to read)."""
    cat = catalog if catalog is not None else _cost._load_catalog()
    bench = benchmarks if benchmarks is not None else _load_benchmarks()
    base = Task(task.category, task.complexity, task.novel, "balanced")
    ranking = rank(
        base,
        user_context_text,
        unavailable_models=unavailable_models,
        catalog=cat,
        benchmarks=bench,
    )
    funded = [c for c in ranking.candidates if c.funding != "unfunded"]
    pool = funded or ranking.candidates
    front = frontier(pool, bench)
    if not front:
        return None
    headroom = consumption_headroom(user_context_text or "")
    # The picks are read off the same frontier drawn over each model at every
    # effort AA measured it at, so an effort is part of the pick it prices.
    settings = effort_settings(pool, base, headroom, ranking, catalog=cat, benchmarks=bench)
    # Every model AA measured only at efforts this task does not run leaves
    # none: the picks then fall back to the models' frontier.
    points = frontier(settings, bench) or front

    adequate = [p for p in points if p.candidate.requirement_penalty == 0]
    if not adequate:
        adequate = [max(points, key=_nearest)]
    top = _top(adequate, task.category)
    span = adequate[: adequate.index(top) + 1]
    specialist = _specialist(task, settings, points, top, bench)
    by_level = {(c.model_id, c.evidence_level): c for c in settings if c.evidence_level}

    def rung(tier: str, p: FrontierPoint) -> Rung:
        c = p.candidate
        if c.evidence_level is not None:
            effort = c.evidence_level
        else:
            t = Task(task.category, task.complexity, task.novel, TIER_BUDGET[tier])
            effort = effort_for(t, headroom, c.scarcity)
        return Rung(tier, p, effort, native_level(c.platform_id, c.model_id, effort, catalog=cat))

    def same(a: Rung, b: Rung) -> bool:
        return a.candidate.model_id == b.candidate.model_id and a.level == b.level

    def step(p: FrontierPoint, by: int) -> FrontierPoint | None:
        """``p``'s model on its platform at its next measured effort up
        (``by`` 1) or down (-1) that meets the task's bar, else None."""
        c = p.candidate
        if c.evidence_level is None:
            return None
        here = EFFORT_LADDER.index(c.evidence_level)
        near = [
            s
            for s in settings
            if s.model_id == c.model_id
            and s.platform_id == c.platform_id
            and s.evidence_level is not None
            and s.requirement_penalty == 0
            and (EFFORT_LADDER.index(s.evidence_level) - here) * by > 0
        ]
        if not near:
            return None
        s = min(near, key=lambda s: abs(EFFORT_LADDER.index(s.evidence_level or "low") - here))
        return FrontierPoint(
            s, _evidence(bench, s.model_id, FRONTIER_INDEX, s.evidence_level), frontier_price(s)
        )

    def settle(r: Rung) -> Rung:
        """A rung :func:`_below` moved to another effort reads AA's row at that
        effort, where AA measured one."""
        c = r.candidate
        moved = by_level.get((c.model_id, r.effort))
        if c.evidence_level is None or r.effort == c.evidence_level or moved is None:
            return r
        aa = _evidence(bench, moved.model_id, FRONTIER_INDEX, moved.evidence_level)
        return replace(r, point=FrontierPoint(moved, aa, frontier_price(moved)))

    # COST is the cheapest adequate point already paid for: a subscription pool
    # with headroom or local weights (scarcity below list price) costs the
    # operator nothing new, while a per-token call is fresh spend.
    cost_point = next((p for p in span if p.candidate.scarcity < 1.0), span[0])
    lo = span.index(cost_point)
    cost_rung = rung("cost", cost_point)
    quality_rung = (
        replace(rung("quality", specialist), specialist=True)
        if specialist is not None
        else rung("quality", top)
    )
    # With a specialist on QUALITY, BALANCED spans every adequate frontier point
    # above COST, the frontier's strongest included. A BALANCED point earns its
    # higher price only by standing at least level with COST in the task's own
    # category: the frontier is drawn on the AA Index, and a point above COST
    # on that axis can still trail it in the category the task needs. A gap
    # within run-to-run noise is level, and the AA Index then decides.
    between = span[lo + 1 :] if specialist is not None else span[lo + 1 : -1]
    between = [p for p in between if _level_with(p.candidate, cost_point.candidate, task.category)]
    # Like COST, BALANCED draws on what is already paid for first: a per-token
    # point stands between only when no prepaid one out-scores COST there.
    between = [p for p in between if p.candidate.scarcity < 1.0] or between
    if between:
        balanced_rung = rung(
            "balanced", max(between, key=lambda p: (p.candidate.score, -p.price_usd))
        )
    else:
        # No point between COST and QUALITY beats COST in the category:
        # BALANCED runs one of those two at the balanced posture, whichever
        # differs from both other rungs; it converges only when neither does.
        # A model run at its measured efforts moves to its next one that
        # still meets the bar instead (COST's up, QUALITY's down), so COST is
        # never pushed below the bar to stay distinct. Beside a specialist it
        # stays on the frontier.
        options = [rung("balanced", cost_point)]
        if (up := step(cost_point, 1)) is not None:
            options.append(rung("balanced", up))
        if specialist is None:
            options.append(rung("balanced", top))
            if (down := step(top, -1)) is not None:
                options.append(rung("balanced", down))
        balanced_rung = next(
            (r for r in options if not same(r, cost_rung) and not same(r, quality_rung)),
            options[0],
        )
    balanced_rung = settle(_below(balanced_rung, quality_rung, cat))
    cost_rung = settle(_below(cost_rung, balanced_rung, cat))
    # General capability is level within the same noise band, read on the
    # AA Index's own 0–100 scale (the planning evidence).
    gscale = _evidence_scale(cat, bench, FRONTIER_INDEX)
    aa_band = 0.0 if gscale is None else DEFAULT_TIE_BAND * (gscale.hi - gscale.lo) / 100.0
    rungs = {
        r.tier: replace(r, backup=_backup_for(r, settings, task, headroom, bench, cat, aa_band))
        for r in (cost_rung, balanced_rung, quality_rung)
    }
    warning: str | None = None
    if any(r.backup is None for r in rungs.values()):
        makers = sorted({c.provider for c in pool})
        warning = (
            f"No cross-provider backup: the models this user can run come from "
            f"{', '.join(makers) or 'no maker'} only. Add a second maker's subscription or "
            "API key so an outage or an exhausted pool has somewhere to go."
        )
    return Ladder(
        task=base,
        frontier=front,
        adequate=adequate,
        rungs=rungs,
        backup_warning=warning,
        points=points,
    )


def _backup_for(
    rung: Rung,
    pool: list[Candidate],
    task: Task,
    headroom: str,
    bench: dict[str, Any],
    catalog: dict[str, Any],
    aa_band: float = 0.0,
) -> Backup | None:
    """The rung's backup: the substitute from another maker that does the job
    as well as the rung, for the least.

    Over the pool's models from a maker other than the rung model's, each at
    its measured efforts, draw the frontier and keep its adequate points,
    those already paid for ahead of per-token ones. A point matches the rung
    when it stands level with it in the task's category
    (:func:`_level_with`) and in general capability (an AA Index no more than
    ``aa_band`` below). The backup is the cheapest match; with none, the
    substitute the QUALITY rule would pick (:func:`_top`: strongest in the
    category, a near tie going to the higher AA Index); with no adequate
    point, the one that falls shortest of the bar. It runs at its
    point's measured effort, else at the rung's posture's effort, on its own
    platform. None when the pool holds no other
    maker's model."""
    front = frontier([c for c in pool if c.provider != rung.candidate.provider], bench)
    if not front:
        return None
    adequate = [p for p in front if p.candidate.requirement_penalty == 0]
    r = rung.point

    def paid_first(points: list[FrontierPoint]) -> list[FrontierPoint]:
        return [p for p in points if p.candidate.scarcity < 1.0] or points

    def aa(p: FrontierPoint) -> float:
        return -1.0 if p.aa_index is None else p.aa_index

    if adequate:
        # The cheapest substitute level with the rung in the category and in
        # general capability; with none, the one the QUALITY rule would pick
        # among the substitutes (:func:`_top`).
        near = paid_first(adequate)
        matches = [
            p
            for p in near
            if _level_with(p.candidate, r.candidate, task.category)
            and (r.aa_index is None or aa(p) >= r.aa_index - aa_band)
        ]
        chosen = (
            min(matches, key=lambda p: (p.price_usd, -aa(p)))
            if matches
            else _top(near, task.category)
        )
    else:
        chosen = max(front, key=_nearest)
    c = chosen.candidate
    if c.evidence_level is not None:
        effort = c.evidence_level
    else:
        t = Task(task.category, task.complexity, task.novel, TIER_BUDGET[rung.tier])
        effort = effort_for(t, headroom, c.scarcity)
    return Backup(chosen, effort, native_level(c.platform_id, c.model_id, effort, catalog=catalog))


def _below(lower: Rung, upper: Rung, catalog: dict[str, Any]) -> Rung:
    """``lower`` run at least one effort level below ``upper`` when both name
    the same model on the same platform and that path costs something
    (scarcity > 0); floored at the dial's lowest level, where the two may
    converge. Three columns that read the same offer no choice, and on a
    capped pool a lower effort is a real, cheaper option. On a free path
    (`uncapped`) a lower effort saves nothing, so the rungs keep their
    posture's effort and converge.

    Levels are compared on the platform's own dial where the catalog
    documents one, since two scorer levels can land on one native level
    (Gemini's dial tops out at high, where the scorer's xhigh and max land
    too); elsewhere on the scorer's ladder."""
    lc, uc = lower.candidate, upper.candidate
    if (lc.model_id, lc.platform_id) != (uc.model_id, uc.platform_id) or lc.scarcity == 0:
        return lower
    levels = native_levels(lc.platform_id, lc.model_id, catalog=catalog)
    if levels and lower.native in levels and upper.native in levels:
        cap = max(0, levels.index(upper.native) - 1)
        if levels.index(lower.native) <= cap:
            return lower
        return Rung(lower.tier, lower.point, _scorer_level(levels[cap]), levels[cap])
    cap = max(0, EFFORT_LADDER.index(upper.effort) - 1)
    if EFFORT_LADDER.index(lower.effort) <= cap:
        return lower
    return Rung(lower.tier, lower.point, EFFORT_LADDER[cap])


def table_keys() -> list[tuple[str, str, bool]]:
    """Every task classification the ladder table covers: each category at each
    complexity, plus the novel variant of a high-complexity task."""
    return [
        (cat, cx, novel)
        for cat in CATEGORIES
        for cx in COMPLEXITIES
        for novel in ((False, True) if cx == "high" else (False,))
    ]


def table_key(category: str, complexity: str, novel: bool) -> str:
    return f"{category}/{complexity}" + ("/novel" if novel and complexity == "high" else "")


def ladder_table(
    user_context_text: str,
    *,
    unavailable_models: list[str] | None = None,
    catalog: dict[str, Any] | None = None,
    benchmarks: dict[str, Any] | None = None,
) -> dict[str, Ladder]:
    """The ladder for every classification in :func:`table_keys`, keyed by
    :func:`table_key`; a classification with no frontier is left out."""
    cat = catalog if catalog is not None else _cost._load_catalog()
    bench = benchmarks if benchmarks is not None else _load_benchmarks()
    out: dict[str, Ladder] = {}
    for category, complexity, novel in table_keys():
        lad = ladder(
            Task(category, complexity, novel),
            user_context_text,
            unavailable_models=unavailable_models,
            catalog=cat,
            benchmarks=bench,
        )
        if lad is not None:
            out[table_key(category, complexity, novel)] = lad
    return out


def _aa_text(p: FrontierPoint) -> str:
    return "not measured" if p.aa_index is None else f"{p.aa_index:g}"


def render_ladder_table(table: dict[str, Ladder]) -> str:
    """The table as the engine reads it: one row per classification, each rung
    as model, platform and effort, under the frontier it was read from."""
    if not table:
        return ""
    any_ladder = next(iter(table.values()))
    lines = [
        "<ladder-table>",
        "This user's cost/quality frontier (the models they can run that score higher on "
        "the AA Intelligence Index than any they can run for less), cheapest first:",
        "  "
        + " < ".join(
            f"{p.candidate.model_name} (AA {_aa_text(p)}, ${p.candidate.blended_price_usd:.2f}/1M list)"
            for p in any_ladder.frontier
        ),
        "Rows: <category>/<complexity>[/novel]: COST | BALANCED | QUALITY, each "
        "<model> @ <platform> · <effort>, the effort in the platform's own level words, "
        "then `backup <model> @ <platform>`: that pick's BACKUP. A QUALITY cell marked "
        "`(top for <category> work)` names a model off the frontier whose rating for that "
        "category is above every frontier model's.",
    ]

    def cell(t: str, r: Rung, category: str) -> str:
        text = f"{t.upper()} = {r.candidate.model_name} @ {r.candidate.platform_name} · {r.level}"
        if r.specialist:
            text += f" (top for {category} work)"
        if r.backup is not None:
            b = r.backup.candidate
            text += f", backup {b.model_name} @ {b.platform_name}"
        return text

    for key, lad in table.items():
        cells = " | ".join(cell(t, lad.rungs[t], lad.task.category) for t in LADDER_TIERS)
        lines.append(f"{key}: {cells}")
    lines.append("</ladder-table>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_text(ranking: Ranking, *, limit: int = 12) -> str:
    t = ranking.task
    head = (
        f"task: {t.category} / {t.complexity}{' / novel' if t.novel else ''} · budget {t.budget}"
        f" · K {ranking.k_points_per_decade:.1f} pts/decade · λ {ranking.lam}"
    )
    lines = [head, ""]
    if ranking.primary:
        p = ranking.primary
        lines.append(
            f"PRIMARY  {p.model_name} — {p.platform_name} · effort {p.effort} · score {p.score:+.1f}"
        )
    if ranking.backup:
        b = ranking.backup
        lines.append(
            f"BACKUP   {b.model_name} — {b.platform_name} · effort {b.effort} · score {b.score:+.1f}"
        )
    elif ranking.backup_warning:
        lines.append(f"BACKUP   none — {ranking.backup_warning}")
    lines.append("")
    lines.append(
        f"{'model':22} {'platform':18} {'fund':12} {'pool':9} {'qual':>6} {'req-pen':>7} "
        f"{'$/1M eff':>9} {'cost-pen':>8} {'effort':>6} {'score':>7}"
    )
    for c in ranking.candidates[:limit]:
        lines.append(
            f"{c.model_name[:22]:22} {c.platform_name[:18]:18} {c.funding:12} {c.pool_state:9} "
            f"{c.quality:6.1f} {c.requirement_penalty:7.1f} {c.effective_cost_usd:9.2f} "
            f"{c.cost_penalty:8.1f} {c.effort:>6} {c.score:7.1f}"
        )
    if len(ranking.candidates) > limit:
        lines.append(f"… {len(ranking.candidates) - limit} more")
    return "\n".join(lines)
