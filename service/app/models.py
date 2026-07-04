# service/app/models.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecommendRequest(BaseModel):
    # Cap raised 20k -> 50k chars (issue #142) so realistic large-context
    # prompts aren't rejected. The web edge mirrors this bound
    # (web/app/api/recommend/route.ts) to reject oversized input cheaply
    # before it reaches the service. Literal ingestion of arbitrarily large
    # inputs stays gated to a future paid tier (see #142) — at ~$0.31/call
    # for a 1M-token context it is a founder-paid free-tier abuse risk.
    task_description: str = Field(min_length=1, max_length=50000)
    context: dict[str, Any] | None = None

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
    # The fallback model (Step 7 of the selection algorithm), surfaced so the web
    # "Backup" line can show an alternative if the primary is unavailable to the
    # user. Optional in recommend_structured (absent when the LLM emits no BACKUP
    # or "None") — same service-boundary carry-through as rationale (#173) and
    # conversation (#190); empty -> None for a clean web fallback.
    backup: str | None = None
    session_cost_estimate: dict[str, Any] | None = None
    comparison_table: list[dict[str, Any]] = Field(default_factory=list)

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

    model_config = ConfigDict(extra="forbid")
