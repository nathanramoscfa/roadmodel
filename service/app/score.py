# service/app/score.py
"""Keyless picks: the Cost / Balanced / Quality ladder from the scoring core.

``POST /v1/score`` takes a task already classified (category, complexity,
novel) and the same structured funding fields the ladder endpoint reads from
``context``, and returns the three picks ``roadmodel.scoring.ladder`` reads off
the caller's own cost/quality frontier. It is arithmetic over the bundled
catalog and benchmarks: no engine runs, no provider key is read, and the
answer costs ``cost_usd: 0``.

An empty profile ranks the whole catalog. ``scoring_context_from_request``
returns None for a request that declares no subscription and no API key, and
``scoring.ladder`` would read None as "use the bundled operator-like template";
this endpoint passes a context that declares only the visitor's jurisdictions
and platform lists (or "" when they declare none), so every catalog model is in
the pool and none is presented as funded.

Each rung carries its score terms (quality, requirement shortfall, cost) and
one plain sentence per term, so the page can say why the pick is the pick.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from roadmodel import scoring  # type: ignore[import-untyped]

from .auth import require_bearer
from .funding import resolve_allowed_jurisdictions, scoring_context_from_request

Category = Literal[
    "coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed"
]
Complexity = Literal["low", "medium", "high"]
Budget = Literal["cheap", "balanced", "best"]

# Every list field: at most 64 items of at most 64 characters each, each an
# id-shaped token (catalog ids, provider ids, jurisdiction codes, access-method
# ids). Items are written into the Markdown the scorer parses, so a space,
# backtick, pipe or newline could otherwise add a line of its own.
MAX_ITEMS: Final = 64
Item = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    ),
]
ItemList = Annotated[list[Item], Field(max_length=MAX_ITEMS)]

# The request fields the funding helpers read, under the names they read them by.
FUNDING_FIELDS: Final = (
    "subscriptions",
    "api_providers",
    "consumption_headroom",
    "allowed_jurisdictions",
    "platforms_allowed",
    "platforms_excluded",
)

# Rungs from the top pick down, the order /recommend shows them in.
RUNG_ORDER: Final = ("quality", "balanced", "cost")


class ScoreRequest(BaseModel):
    category: Category
    complexity: Complexity
    novel: bool = False
    budget_priority: Budget = "balanced"
    subscriptions: ItemList = Field(default_factory=list)
    api_providers: ItemList = Field(default_factory=list)
    consumption_headroom: Literal["auto", "capped", "uncapped"] | None = None
    allowed_jurisdictions: ItemList = Field(default_factory=list)
    platforms_allowed: ItemList = Field(default_factory=list)
    platforms_excluded: ItemList = Field(default_factory=list)
    unavailable_models: ItemList = Field(default_factory=list)
    # The web edge forwards this beside unavailable_models on every lane. The
    # scorer's availability is the forwarded list alone (as the engine's
    # frontier table's is), so the flag is accepted and has no further effect.
    availability_authoritative: bool = False

    model_config = ConfigDict(extra="forbid")


class Terms(BaseModel):
    quality: float
    requirement_shortfall: float
    cost: float


class Why(BaseModel):
    quality: str
    requirement_shortfall: str
    cost: str


class ScoreBackup(BaseModel):
    model_id: str
    model_name: str
    platform_id: str
    platform_name: str
    effort: str


class ScoreRung(BaseModel):
    priority: str
    model_id: str
    model_name: str
    platform_id: str
    platform_name: str
    effort: str
    specialist: bool = False
    backup: ScoreBackup | None = None
    terms: Terms
    why: Why


class ScoreResponse(BaseModel):
    rungs: list[ScoreRung]
    task: dict[str, Any]
    backup_warning: str | None = None
    engine: Literal["scoring-core"] = "scoring-core"
    cost_usd: float = 0.0

    model_config = ConfigDict(extra="forbid")


def scoring_text(req: ScoreRequest) -> str:
    """The user-context the scorer reads for this request: the declared
    funding as tables when there is any, else only the declared jurisdictions
    and platform lists, else "" (the scorer's baseline jurisdictions, every
    platform). Never None: None would make the scorer fall back to the bundled
    template."""
    ctx = req.model_dump(include=set(FUNDING_FIELDS), exclude_none=True)
    text = scoring_context_from_request(ctx)
    if text is not None:
        return text
    lines: list[str] = []
    if req.allowed_jurisdictions:
        lines.append(
            f"**Allowed jurisdictions:** `{', '.join(resolve_allowed_jurisdictions(ctx))}`"
        )
    # The scorer reports an unknown platform id and ignores it.
    if req.platforms_allowed:
        lines.append(f"platforms.allowed: {', '.join(p.lower() for p in req.platforms_allowed)}")
    if req.platforms_excluded:
        lines.append(f"platforms.excluded: {', '.join(p.lower() for p in req.platforms_excluded)}")
    return "\n\n".join(lines) + "\n" if lines else ""


def _why(c: Any, task: scoring.Task) -> Why:
    """One plain sentence per score term, from the candidate's own figures."""
    label = f"{task.category} work"
    if c.quality_source == "letter":
        quality = (
            f"{c.model_name} rates {c.quality:.0f} of 100 for {label}, from its {c.letter} rating."
        )
    else:
        quality = (
            f"{c.model_name} rates {c.quality:.0f} of 100 for {label}: Artificial Analysis "
            f"measurements weighted 70/30 with its {c.letter} rating."
        )
    bar = f"the {c.requirement:.0f}-point bar a {task.complexity}-complexity task sets"
    if task.novel and task.complexity == "high":
        bar = f"the {c.requirement:.0f}-point bar a novel high-complexity task sets"
    if c.requirement_penalty > 0:
        shortfall = (
            f"It sits {c.requirement - c.quality:.0f} points under {bar}, "
            f"which takes {c.requirement_penalty:.0f} points off its score."
        )
    else:
        shortfall = f"It clears {bar}."
    if c.cost_penalty > 0 and c.effective_cost_usd < c.blended_price_usd:
        cost = (
            f"On {c.platform_name} it draws an effective ${c.effective_cost_usd:.2f} per 1M "
            f"tokens (list ${c.blended_price_usd:.2f}), which takes {c.cost_penalty:.0f} points "
            "off its score."
        )
    elif c.cost_penalty > 0:
        cost = (
            f"Its spend, about ${c.effective_cost_usd:.2f} per 1M tokens at list price, takes "
            f"{c.cost_penalty:.0f} points off its score."
        )
    else:
        cost = f"It runs free of charge on {c.platform_name}, so spend takes no points off."
    return Why(quality=quality, requirement_shortfall=shortfall, cost=cost)


def _rung(tier: str, r: Any, task: scoring.Task) -> ScoreRung:
    c = r.candidate
    b = r.backup
    return ScoreRung(
        priority=tier,
        model_id=c.model_id,
        model_name=c.model_name,
        platform_id=c.platform_id,
        platform_name=c.platform_name,
        effort=r.level,
        specialist=bool(getattr(r, "specialist", False)),
        backup=(
            ScoreBackup(
                model_id=b.candidate.model_id,
                model_name=b.candidate.model_name,
                platform_id=b.candidate.platform_id,
                platform_name=b.candidate.platform_name,
                effort=b.level,
            )
            if b is not None
            else None
        ),
        terms=Terms(
            quality=c.quality,
            requirement_shortfall=c.requirement_penalty,
            cost=c.cost_penalty,
        ),
        why=_why(c, task),
    )


router = APIRouter()


@router.post("/v1/score", response_model=ScoreResponse, dependencies=[Depends(require_bearer)])
def score_endpoint(req: ScoreRequest) -> ScoreResponse:
    task = scoring.Task(req.category, req.complexity, req.novel, req.budget_priority)
    lad = scoring.ladder(
        task, scoring_text(req), unavailable_models=list(req.unavailable_models) or None
    )
    if lad is None:
        # The declared filters leave no model with an AA Index: no frontier.
        raise HTTPException(status_code=422, detail="no_frontier")
    return ScoreResponse(
        rungs=[_rung(t, lad.rungs[t], task) for t in RUNG_ORDER],
        task={
            "category": task.category,
            "complexity": task.complexity,
            "novel": task.novel,
            "budget_priority": task.budget,
        },
        backup_warning=lad.backup_warning,
    )
