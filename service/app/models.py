# service/app/models.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .context import RecommendContext


class RecommendRequest(BaseModel):
    # Cap raised 20k -> 50k chars (issue #142) so realistic large-context
    # prompts aren't rejected. The web edge mirrors this bound
    # (web/app/api/recommend/route.ts) to reject oversized input cheaply
    # before it reaches the service. Literal ingestion of arbitrarily large
    # inputs stays gated to a future paid tier (see #142) — at ~$0.31/call
    # for a 1M-token context it is a founder-paid free-tier abuse risk.
    task_description: str = Field(min_length=1, max_length=50000)
    context: dict[str, Any] | None = None

    @field_validator("context")
    @classmethod
    def _context(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return RecommendContext.model_validate(value).model_dump(exclude_unset=True)

    @field_validator("task_description")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        # min_length=1 counts characters, not stripped content, so "   " /
        # tabs / newlines slip through and reach a paid LLM call. Reject
        # blank / whitespace-only input (#175). The web edge returns 400 for
        # the same case before the upstream fetch; this is the service guard.
        if not value.strip():
            raise ValueError("task_description must not be blank or whitespace-only")
        return value

    model_config = ConfigDict(extra="forbid")


class BackupPick(BaseModel):
    """The Step 7 fallback model, enriched so it ADHERES to the user's settings
    like the primary pick: the surface the user runs it on (`platform`) and its
    per-surface `settings` at the same reasoning posture as the pick. Both are
    best-effort — `platform` is None / `settings` is empty when they can't be
    resolved (e.g. an anonymous request with no declared funding), and the client
    then shows just the model name (the pre-enrichment behavior). `model` is the
    catalog display name, already cross-provider + access/jurisdiction-checked by
    the AccessGuard before it reaches here."""

    model: str
    platform: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RankedOption(BaseModel):
    """One ranked option of a ladder column (app/ranks.py): a model on a
    platform at a level, with the figures a roadmap's Settings print for it."""

    model: str
    model_id: str
    platform: str
    platform_id: str
    # The scorer's level (low / medium / high / xhigh / max), or `fixed` for a
    # configuration whose level is not set.
    effort: str
    # The level as the ladder table words it (`XHigh`); `—` where the surface
    # has no reasoning dial.
    level: str
    # The AA Intelligence Index at that level: AA's own row there, else
    # roadmodel's estimate from the levels AA did measure (`aa_estimated`).
    aa_index: float | None = None
    aa_estimated: bool = False
    # USD per 1M blended tokens at that level's token use; `price_measured`
    # says whether that token use was measured or derived.
    price_usd_per_1m: float | None = None
    price_measured: bool | None = None
    # The Pick's own model one or two levels lower, filling a rank no other
    # maker could.
    stepped_down: bool = False
    ultracode: bool = False

    model_config = ConfigDict(extra="forbid")


class Ranks(BaseModel):
    """A pick ranked three deep, each rank from another maker: the Pick, the
    Runner-up with the Pick's maker off the table, and the Backup with both
    makers above off it. A rank the caller's models cannot fill is None."""

    pick: RankedOption
    runner_up: RankedOption | None = None
    backup: RankedOption | None = None

    model_config = ConfigDict(extra="forbid")


class LadderTask(BaseModel):
    """What the task was read as: the category and complexity the picks were
    ranked for, and whether it is a new kind of problem."""

    category: str
    complexity: str
    novel: bool = False

    model_config = ConfigDict(extra="forbid")


class LadderPoint(BaseModel):
    """One setting the ladder weighed (app/ranks.py): a model the caller can
    run at an effort the task may run. The cost/quality frontier the picks
    are read from is drawn over these, so a page that plots them shows a pick
    where the ladder found it."""

    model_id: str
    platform_id: str = ""
    # The scorer's level; None for a model AA names no effort for, at its
    # headline figure.
    effort: str | None = None
    # The AA Intelligence Index there, as a ladder prints it, and how far
    # below it the scorer ranks it (an estimate's uncertainty; 0 for AA's own
    # measurement): the frontier stands on `aa_index - margin`.
    aa_index: float
    margin: float = 0.0
    # USD per 1M blended tokens at that effort's token use.
    price_usd_per_1m: float
    # Meets the task's bar: Cost is the cheapest setting that does.
    adequate: bool = True
    # The index is roadmodel's estimate (AA has not measured the model).
    estimated: bool = False

    model_config = ConfigDict(extra="forbid")


class RecommendResponse(BaseModel):
    model: str
    platform: str
    settings: dict[str, Any]
    # The model's own reasoning for the pick. recommend_structured emits this
    # as a top-level key; the service must carry it through or the web "Why
    # this model?" panel is empty for every user (issue #173 — the same
    # service-boundary drop class as the #164 cost/comparison_table fix).
    rationale: str | None = None
    # Structured rationale sections (task / pick / run) parsed best-effort from
    # the labelled RATIONALE, so the web "Why this model?" panel can render
    # sub-headed segments instead of splitting one prose string. Present only
    # when the model followed the labelled format; absent -> None and the web
    # edge falls back to the single `rationale` string above. Same
    # service-boundary carry-through discipline as rationale (#173). Using
    # ``.get`` on the selector payload keeps the service deployable against an
    # older roadmodel that never emits this key.
    rationale_sections: dict[str, str] | None = None
    # The model's conversation-handling decision (New/Continue). recommend_structured
    # emits this as a top-level key; like rationale (#173) it was dropped at the
    # service boundary (extra="forbid" + never passed through) — issue #190. Carry
    # it so the field survives end-to-end; empty -> None for a clean web fallback.
    conversation: str | None = None
    # The fallback model (Step 7), enriched into a BackupPick — model + its own
    # funded platform + per-surface settings — so the backup adheres to the user's
    # settings like the primary (not just a bare name). Absent when the LLM emits
    # no BACKUP / "None"; platform + settings are best-effort within it (None / {}
    # when unresolvable), so the client degrades to showing just the model name.
    backup: BackupPick | None = None
    # True when this pick is a category specialist: a model off the user's
    # cost/quality frontier whose rating for the task's category
    # (``specialist_category``) is above every frontier model's, which the
    # frontier ladder puts on QUALITY (roadmodel >= 0.2.64). The web shows "Top
    # for <category> work" in place of the frontier mark.
    specialist: bool = False
    specialist_category: str | None = None
    # The pick ranked three deep, as a roadmap's Settings rank it: this pick,
    # a Runner-up and a Backup from other makers, each with its level, AA
    # Index and price there (app/ranks.py). Present on a ladder pick the
    # frontier table placed; None on the single-pick path, on a pick a guard
    # replaced, and whenever the ranks cannot be read.
    ranks: Ranks | None = None
    session_cost_estimate: dict[str, Any] | None = None
    comparison_table: list[dict[str, Any]] = Field(default_factory=list)
    # The engine that produced this answer (an engines.json hint). It differs
    # from the requested engine when that one failed and the fallback chain
    # answered, so the web can say which model actually wrote the picks.
    engine: str | None = None
    # The engine call's provider-reported token counts (roadmodel.usage):
    # input_tokens, cached_input_tokens, cache_write_tokens, output_tokens,
    # reasoning_tokens. The web meters the call from these. None when the
    # provider reported none.
    usage: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class LadderResponse(BaseModel):
    """The whole Cost/Balanced/Quality ladder from ONE call (tasks #1/#3).

    ``picks`` is keyed by tier (``quality`` / ``balanced`` / ``cost``), each the
    same shape as a single :class:`RecommendResponse`, so the web edge can map
    them straight into its existing per-priority ``recommendations[]`` payload
    with no frontend change. ``guard`` is the deterministic tier-distinctness
    report (models, resolved tiers, duplicate_models, misordered, distinct_tiers,
    healthy) — the edge falls back to the per-priority fan-out when the ladder is
    not healthy.
    """

    picks: dict[str, RecommendResponse]
    guard: dict[str, Any] = Field(default_factory=dict)
    # What the engine read the task as (the frontier table's row the picks
    # were copied from); None when the response matched no row.
    task: LadderTask | None = None
    # Every setting that row's ladder weighed, for the page's chart; None
    # when the response matched no row or they could not be read.
    points: list[LadderPoint] | None = None
    # The engine that answered and its token counts, for the whole ladder (one
    # call); see RecommendResponse.engine / .usage.
    engine: str | None = None
    usage: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")
