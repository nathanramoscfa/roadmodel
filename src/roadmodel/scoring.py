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
  the measured catalog and blended 70/30 with the editorial S→D letter, or the
  letter alone when AA has not measured the model (``quality_source`` says
  which).
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

Hard filters run first: availability, allowed jurisdictions, the operator's
platform allow / deny lists. Funding is read from the user-context exactly as
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
from dataclasses import asdict, dataclass, field
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

# The Artificial Analysis evidence figure per category (the same mapping the
# web catalog uses for its derived letters). ``None`` = editorial letter only.
# ``speed`` reads the top-level tokens/s field rather than an evaluation.
CATEGORY_EVIDENCE: Final[dict[str, str | None]] = {
    "coding": "artificial_analysis_coding_index",
    "planning": "artificial_analysis_intelligence_index",
    "agentic": "terminalbench_v2_1",
    "multimodal": None,
    "long-context": "lcr",
    "knowledge": "hle",
    "speed": "median_output_tokens_per_second",
}

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
    {"claude-code", "codex-cli", "cursor", "gemini-cli"}
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
    # AA reports 0 tokens/s for endpoints it has not throughput-tested, and no
    # evaluation legitimately scores exactly 0: treat 0 as "not measured"
    # (mirrors web/lib/catalog-models.ts).
    return float(v) if float(v) > 0 else None


def blended_price(model: dict[str, Any]) -> float:
    inp = float(model.get("input_price_per_1m") or 0.0)
    out = float(model.get("output_price_per_1m") or 0.0)
    return (3.0 * inp + out) / 4.0


def market_exchange_rate(
    catalog: dict[str, Any],
    bench: dict[str, Any],
    task: Task | None = None,
    scale: tuple[float, float] | None = None,
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


def pool_states(text: str) -> list[tuple[str, str, str]]:
    """Rows of the ``Usage-pool status`` table as (pool name, state, notes).
    The State cell may be decorated (backticks, bold, a trailing note); the
    first headroom / tight / exhausted word wins."""
    section = _cost._extract_section(text, "Usage-pool status")
    rows: list[tuple[str, str, str]] = []
    for row in _cost._parse_markdown_table(section):
        if len(row) < 3:
            continue
        name = row[0].strip()
        m = _POOL_STATE_RE.search(row[2])
        notes = row[4].strip() if len(row) > 4 else ""
        if m and name.lower() != "pool":
            rows.append((name, m.group(1).lower(), notes))
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


def _quality(
    model: dict[str, Any],
    task: Task,
    bench: dict[str, Any],
    scale: tuple[float, float] | None,
) -> tuple[float, str, str]:
    raw_tiers = model.get("tiers")
    tiers: dict[str, Any] = raw_tiers if isinstance(raw_tiers, dict) else {}
    letter = str(tiers.get(task.category, "C")).upper()
    letter_q = LETTER_QUALITY.get(letter, 30.0)
    key = CATEGORY_EVIDENCE[task.category]
    v = _evidence(bench, str(model.get("id", "")), key)
    if scale is None or scale[1] <= scale[0]:
        # No evidence exists for this category at all (multimodal): every model
        # is on its letter, so there is nothing to discount against.
        return letter_q, "letter", letter
    if v is None:
        return max(0.0, letter_q - UNMEASURED_DISCOUNT), "letter", letter
    scaled = 100.0 * (v - scale[0]) / (scale[1] - scale[0])
    scaled = max(0.0, min(100.0, scaled))
    q = EVIDENCE_WEIGHT * scaled + (1.0 - EVIDENCE_WEIGHT) * letter_q
    return q, f"aa:{key}+letter", letter


def _evidence_scale(
    catalog: dict[str, Any], bench: dict[str, Any], key: str | None
) -> tuple[float, float] | None:
    if key is None:
        return None
    vals = [
        v
        for m in catalog.get("models", [])
        if isinstance(m, dict)
        for v in [_evidence(bench, str(m.get("id", "")), key)]
        if v is not None
    ]
    if len(vals) < 3:
        return None
    return min(vals), max(vals)


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
    bench = benchmarks if benchmarks is not None else _load_benchmarks()
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
