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
    mid-rank percentiles on those parts, among those rows (0 = lowest)."""
    out: dict[str, Any] = {}
    for mid, row in bench.items():
        if isinstance(row, dict):
            evals = row.get("evaluations")
            out[mid] = {**row, "evaluations": dict(evals) if isinstance(evals, dict) else {}}
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
    return out


def _evidence(bench: dict[str, Any], model_id: str, key: str | None) -> float | None:
    if key is None:
        return None
    row = bench.get(model_id)
    if not isinstance(row, dict):
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
) -> tuple[float, str, str]:
    raw_tiers = model.get("tiers")
    tiers: dict[str, Any] = raw_tiers if isinstance(raw_tiers, dict) else {}
    letter = str(tiers.get(task.category, "C")).upper()
    letter_q = LETTER_QUALITY.get(letter, 30.0)
    key = CATEGORY_EVIDENCE[task.category]
    v = _evidence(bench, str(model.get("id", "")), key)
    if scale is None:
        # No evidence exists for this category at all (multimodal): every model
        # is on its letter, so there is nothing to discount against.
        return letter_q, "letter", letter
    if v is None:
        return max(0.0, letter_q - UNMEASURED_DISCOUNT), "letter", letter
    q = EVIDENCE_WEIGHT * scale.points(v) + (1.0 - EVIDENCE_WEIGHT) * letter_q
    return q, f"aa:{key}+letter", letter


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
    aa_index: float
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
    frontier: list[FrontierPoint]
    # Frontier points whose quality in the task's category meets the
    # complexity's requirement, cheapest first.
    adequate: list[FrontierPoint]
    rungs: dict[str, Rung]
    # Why a rung has no backup: the pool holds no other maker's model.
    backup_warning: str | None = None

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
            }

        return {
            "task": asdict(self.task),
            "frontier": [point(p) for p in self.frontier],
            "adequate": [p.candidate.model_id for p in self.adequate],
            "rungs": {
                t: {
                    **point(r.point),
                    "effort": r.effort,
                    "native_effort": r.native,
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


def frontier(candidates: list[Candidate], bench: dict[str, Any]) -> list[FrontierPoint]:
    """The cost/quality frontier over ``candidates``, cheapest first: every
    model that scores higher on the AA Intelligence Index than every candidate
    at its price or less. The rule web/lib/benchmark-grid.ts paretoFrontier
    draws on /models: a tie on price goes to the higher index, a tie on index to
    the cheaper price. Unmeasured models have no place on it."""
    points = [
        FrontierPoint(c, aa, c.blended_price_usd)
        for c in candidates
        for aa in [_evidence(bench, c.model_id, FRONTIER_INDEX)]
        if aa is not None
    ]
    points.sort(key=lambda p: (p.price_usd, -p.aa_index, p.candidate.model_id))
    out: list[FrontierPoint] = []
    for p in points:
        if not out or p.aa_index > out[-1].aa_index:
            out.append(p)
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
    - Frontier: :func:`frontier` over the pool, at list price.
    - Adequate: frontier points whose quality in the task's category meets the
      complexity's requirement; when none does, the frontier's best for the
      category stands alone.
    - QUALITY is the adequate point that scores highest in the category (then
      the higher AA Index, then the cheaper). COST is the cheapest adequate
      point. BALANCED is the point strictly between them with the best score
      at the balanced posture; with none between, the COST or QUALITY model at
      the balanced posture's effort, whichever differs from both other rungs.
    - Each rung runs at :func:`effort_for` its posture (cheap / balanced /
      best), set on its platform's own dial (:func:`native_level`) where the
      catalog documents one. A lower rung on the same model and platform as
      the rung above runs at least one effort level below it
      (:func:`_below`), so the three picks stay distinct; at the dial's lowest
      level they may converge. On an `uncapped` pool every free rung runs at
      the top effort and two rungs on one model converge: a lower effort saves
      that operator nothing.
    - Each rung carries a BACKUP from another maker (:func:`_backup_for`):
      the best adequate point on the other makers' frontier at no higher list
      price. ``backup_warning`` says why a rung has none.

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
    front = frontier(funded or ranking.candidates, bench)
    if not front:
        return None

    def strength(p: FrontierPoint) -> tuple[float, float, float]:
        return (p.candidate.quality, p.aa_index, -p.price_usd)

    adequate = [p for p in front if p.candidate.requirement_penalty == 0]
    if not adequate:
        adequate = [max(front, key=strength)]
    top = max(adequate, key=strength)
    span = adequate[: adequate.index(top) + 1]
    headroom = consumption_headroom(user_context_text or "")

    def rung(tier: str, p: FrontierPoint) -> Rung:
        t = Task(task.category, task.complexity, task.novel, TIER_BUDGET[tier])
        effort = effort_for(t, headroom, p.candidate.scarcity)
        c = p.candidate
        return Rung(tier, p, effort, native_level(c.platform_id, c.model_id, effort, catalog=cat))

    def same(a: Rung, b: Rung) -> bool:
        return a.candidate.model_id == b.candidate.model_id and a.level == b.level

    cost_rung = rung("cost", span[0])
    quality_rung = rung("quality", top)
    between = span[1:-1]
    if between:
        balanced_rung = rung(
            "balanced", max(between, key=lambda p: (p.candidate.score, -p.price_usd))
        )
    else:
        # Two adequate points or one: BALANCED runs one of them at the balanced
        # posture, whichever differs from both other rungs; it converges only
        # when neither does.
        options = [rung("balanced", span[0]), rung("balanced", top)]
        balanced_rung = next(
            (r for r in options if not same(r, cost_rung) and not same(r, quality_rung)),
            options[0],
        )
    balanced_rung = _below(balanced_rung, quality_rung, cat)
    cost_rung = _below(cost_rung, balanced_rung, cat)
    pool = funded or ranking.candidates
    rungs = {
        r.tier: replace(r, backup=_backup_for(r, pool, task, headroom, bench, cat))
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
    return Ladder(task=base, frontier=front, adequate=adequate, rungs=rungs, backup_warning=warning)


def _backup_for(
    rung: Rung,
    pool: list[Candidate],
    task: Task,
    headroom: str,
    bench: dict[str, Any],
    catalog: dict[str, Any],
) -> Backup | None:
    """The rung's backup: the best substitute from another maker the operator
    can run, at no higher list price.

    Over the pool's models from a maker other than the rung model's, draw the
    frontier and keep its adequate points. The backup is the adequate point
    with the highest list price at or below the rung's; else the cheapest
    adequate point above it; else, with no adequate point, the frontier's
    strongest for the category. It runs at the rung's posture's effort on its
    own platform. None when the pool holds no other maker's model."""
    front = frontier([c for c in pool if c.provider != rung.candidate.provider], bench)
    if not front:
        return None
    adequate = [p for p in front if p.candidate.requirement_penalty == 0]
    if adequate:
        within = [p for p in adequate if p.price_usd <= rung.point.price_usd]
        chosen = within[-1] if within else adequate[0]
    else:
        chosen = max(front, key=lambda p: (p.candidate.quality, p.aa_index, -p.price_usd))
    t = Task(task.category, task.complexity, task.novel, TIER_BUDGET[rung.tier])
    c = chosen.candidate
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
            f"{p.candidate.model_name} (AA {p.aa_index:g}, ${p.candidate.blended_price_usd:.2f}/1M list)"
            for p in any_ladder.frontier
        ),
        "Rows: <category>/<complexity>[/novel]: COST | BALANCED | QUALITY, each "
        "<model> @ <platform> · <effort>, the effort in the platform's own level words, "
        "then `backup <model> @ <platform>`: that pick's BACKUP.",
    ]

    def cell(t: str, r: Rung) -> str:
        text = f"{t.upper()} = {r.candidate.model_name} @ {r.candidate.platform_name} · {r.level}"
        if r.backup is not None:
            b = r.backup.candidate
            text += f", backup {b.model_name} @ {b.platform_name}"
        return text

    for key, lad in table.items():
        cells = " | ".join(cell(t, lad.rungs[t]) for t in LADDER_TIERS)
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
