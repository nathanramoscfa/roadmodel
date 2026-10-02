"""The request's declared access in the format the package's scorer reads.

build_user_context writes a user's plans and API keys as prose for the engine;
the scorer (roadmodel.scoring) reads the user-context.md tables instead, so the
service renders a table-format twin for the frontier ladder table. These tests
read it back through the scorer itself.
"""

from __future__ import annotations

from roadmodel import scoring  # type: ignore[import-untyped]

from app.funding import scoring_context_from_request

MAX_AND_PRO = {
    "subscriptions": ["claude-max", "chatgpt-pro"],
    "api_providers": ["openai"],
    "allowed_jurisdictions": ["us", "eu"],
}


def _funding(text: str) -> dict[str, str]:
    """The scorer's funding class per model, for a planning task."""
    ranking = scoring.rank(scoring.Task("planning", "medium"), text)
    return {c.model_id: c.funding for c in ranking.candidates}


def test_no_declared_access_means_no_scoring_context() -> None:
    assert scoring_context_from_request(None) is None
    assert scoring_context_from_request({}) is None
    assert scoring_context_from_request({"budget_priority": "best"}) is None


def test_declared_plans_and_keys_are_funded_for_the_scorer() -> None:
    text = scoring_context_from_request(MAX_AND_PRO)
    assert text is not None
    assert "| claude.ai Max ($200) | $200 | Anthropic |" in text
    assert "| openai | Yes | |" in text
    funding = _funding(text)
    assert funding["claude-opus-5-5"] == "subscription"
    assert funding["gpt-6-luna"] == "subscription"
    # Nothing the request did not declare is funded.
    assert all(f == "unfunded" for m, f in funding.items() if m.startswith("gemini"))


def test_the_prose_context_alone_funds_nothing_for_the_scorer() -> None:
    # Why the twin exists: the engine's prose context does not parse as tables.
    from app.funding import user_context_from_request

    prose = user_context_from_request(MAX_AND_PRO)
    assert prose is not None
    assert set(_funding(prose).values()) == {"unfunded"}


def test_headroom_jurisdictions_and_platform_lists_carry_over() -> None:
    text = scoring_context_from_request(
        {
            **MAX_AND_PRO,
            "consumption_headroom": "uncapped",
            "allowed_jurisdictions": ["us", "cn"],
            "platforms_excluded": ["claude-web", "not-a-platform"],
        }
    )
    assert text is not None
    assert scoring.consumption_headroom(text) == "uncapped"
    assert scoring.allowed_jurisdictions(text) == {"us", "cn"}
    assert scoring.platform_filters(text) == (set(), {"claude-web"})


def test_auto_headroom_is_capped() -> None:
    text = scoring_context_from_request({**MAX_AND_PRO, "consumption_headroom": "auto"})
    assert text is not None
    assert scoring.consumption_headroom(text) == "capped"


def test_the_ladder_table_reads_off_the_declared_models() -> None:
    text = scoring_context_from_request({"subscriptions": ["claude-max"]})
    assert text is not None
    table = scoring.ladder_table(text)
    assert table
    for lad in table.values():
        assert all(
            r.candidate.platform_id in {"claude-code", "claude-web"} for r in lad.rungs.values()
        )
