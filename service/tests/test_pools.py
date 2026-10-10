"""The actual package scorer must consume the saved profile's metered states."""

import time
from typing import Any

import pytest
from roadmodel import scoring  # type: ignore[import-untyped]

from app.funding import (
    _tier_id,
    funding_guard_from_request,
    load_catalog,
    scoring_context_from_request,
    user_context_from_request,
)
from app.score import ScoreRequest, scoring_text


def meter(pool: str, state: str, age: float = 0, reset: float | None = None) -> dict[str, Any]:
    now = time.time()
    minutes = 0 if pool.startswith("openrouter") else 10080
    return dict(
        pool=pool,
        state=state,
        used_percent=98 if state == "exhausted" else 42,
        observed_at=now - age,
        resets_at=reset if reset else (None if minutes == 0 else now + 3600),
        window_minutes=minutes,
    )


@pytest.mark.parametrize(
    "platform,pool",
    [
        ("claude-code", "claude:weekly"),
        ("codex-cli", "codex:weekly"),
        ("antigravity", "antigravity:all"),
    ],
)
@pytest.mark.parametrize("state,scarcity", [("headroom", 0.35), ("tight", 0.7), ("exhausted", 1)])
def test_profile_state_is_the_scorers_real_scarcity(
    platform: str, pool: str, state: str, scarcity: float
) -> None:
    catalog = load_catalog()
    tier = next(t for t in catalog["subscription_tiers"] if platform in t.get("surface_funded", []))
    context: dict[str, Any] = {
        "subscriptions": [_tier_id(tier["provider"], tier["tier"])],
        "pool_states": [meter(pool, state)],
        "platforms_allowed": [platform],
    }
    text = scoring_context_from_request(context)
    ranking = scoring.rank(scoring.Task("coding", "medium"), text)
    assert ranking.candidates
    assert all(c.pool_state == state and c.scarcity == scarcity for c in ranking.candidates)
    prose = user_context_from_request(context)
    assert prose is not None and "## Usage-pool status" in prose


@pytest.mark.parametrize(
    "state,funded", [("headroom", "api-key"), ("tight", "api-key"), ("exhausted", "unfunded")]
)
def test_keyless_score_and_prompt_honor_fixed_reserve(state: str, funded: str) -> None:
    request = ScoreRequest(
        category="coding",
        complexity="low",
        api_providers=["openrouter"],
        platforms_allowed=["openrouter"],
        pool_states=[meter("openrouter:credits", state, age=100000)],
    )
    text = scoring_text(request)
    ranking = scoring.rank(scoring.Task("coding", "low"), text)
    assert ranking.candidates and all(c.funding == funded for c in ranking.candidates)


def test_stale_exhaustion_retained_but_known_passed_reset_clears() -> None:
    context: dict[str, Any] = {
        "subscriptions": ["claude-max"],
        "platforms_allowed": ["claude-code"],
        "pool_states": [meter("claude:weekly", "exhausted", age=86400)],
    }
    text = scoring_context_from_request(context)
    assert all(
        c.scarcity == 1 for c in scoring.rank(scoring.Task("coding", "low"), text).candidates
    )
    context["pool_states"][0]["resets_at"] = time.time() - 60
    text = scoring_context_from_request(context)
    assert all(
        c.scarcity == 0.35 for c in scoring.rank(scoring.Task("coding", "low"), text).candidates
    )


def test_funding_guard_corrects_exhausted_subscription_claims() -> None:
    context: dict[str, Any] = {
        "subscriptions": ["claude-max"],
        "pool_states": [meter("claude:weekly", "exhausted")],
    }
    guard = funding_guard_from_request(context)
    assert guard is not None
    rationale, _ = guard.sanitize("Claude Code", "Your subscription funds this at $0.", None)
    assert rationale is not None and "usage credits at list price" in rationale
