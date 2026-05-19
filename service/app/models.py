# service/app/models.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecommendRequest(BaseModel):
    task_description: str = Field(min_length=1, max_length=20000)

    model_config = ConfigDict(extra="forbid")


class RecommendResponse(BaseModel):
    model: str
    platform: str
    settings: dict[str, Any]
    session_cost_estimate: dict[str, Any] | None = None
    comparison_table: list[dict[str, Any]] = Field(default_factory=list)
    free_tier_label: str | None = None

    model_config = ConfigDict(extra="forbid")
