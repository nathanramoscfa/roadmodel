"""Closed, bounded structured context shared by the two funded lanes."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from .pools import POOLS, normalize

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
]
Platform = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._+-]*$")
]
ModelID = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class PoolObservation(BaseModel):
    pool: Literal[
        "claude:weekly",
        "claude:5h",
        "codex:weekly",
        "codex:5h",
        "antigravity:all",
        "openrouter:credits",
    ]
    state: Literal["headroom", "tight", "exhausted"]
    observed_at: Annotated[Number, Field(gt=0)]
    resets_at: Annotated[Number, Field(gt=0)] | None
    used_percent: Annotated[Number, Field(ge=0, le=100)]
    window_minutes: Annotated[Number, Field(ge=0, le=10080)]
    source: Identifier | None = None
    platform_id: Identifier | None = None
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def consistent(self) -> Self:
        source, platform, _ = POOLS[self.pool]
        if ("source" in self.model_fields_set and self.source != source) or (
            "platform_id" in self.model_fields_set and self.platform_id != platform
        ):
            raise ValueError("invalid pool origin")
        if not normalize([self.model_dump(exclude_unset=True)]):
            raise ValueError("invalid pool observation")
        return self


def validate_pools(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [PoolObservation.model_validate(row).model_dump(exclude_unset=True) for row in rows]


class RecommendContext(BaseModel):
    subscriptions: list[Identifier] = Field(default_factory=list, max_length=64)
    api_providers: list[Identifier] = Field(default_factory=list, max_length=64)
    allowed_jurisdictions: list[
        Literal["us", "eu", "uk", "ca", "au", "jp", "kr", "cn", "ru", "unknown"]
    ] = Field(default_factory=list, max_length=64)
    platforms_allowed: list[Platform] = Field(default_factory=list, max_length=64)
    platforms_excluded: list[Platform] = Field(default_factory=list, max_length=64)
    unavailable_models: list[ModelID] = Field(default_factory=list, max_length=256)
    availability_authoritative: StrictBool = False
    budget_priority: Literal["cheap", "balanced", "best"] | None = None
    consumption_headroom: Literal["auto", "capped", "uncapped"] | None = None
    force_provider: (
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
            ),
        ]
        | None
    ) = None
    classification: (
        Annotated[
            str,
            StringConstraints(
                max_length=64,
                pattern=(
                    r"^(coding|planning|agentic|multimodal|long-context|knowledge|speed)/(low|medium|high)(/novel)?$"
                ),
            ),
        ]
        | None
    ) = None
    pool_states: list[PoolObservation] = Field(default_factory=list, max_length=6)
    model_config = ConfigDict(extra="forbid")
