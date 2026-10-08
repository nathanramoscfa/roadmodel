"""The ladder call holds a pinned classification and votes on a new one.

The web edge caches the ladder-table row each task landed on and sends it back
as context.classification; the service forwards it (when shaped like a table
key) with CLASSIFICATION_VOTES, which the package uses only when nothing is
pinned (Phase 4.5, maintainer decision 2026-10-08).
"""

from __future__ import annotations

import inspect

import pytest
from roadmodel.recommend import recommend_structured_ladder  # type: ignore[import-untyped]

from app import recommend as svc
from app.models import RecommendRequest


def test_the_installed_package_takes_the_classification_arguments() -> None:
    params = inspect.signature(recommend_structured_ladder).parameters
    assert {"classification", "classification_votes"} <= set(params)
    assert svc._LADDER_TAKES_CLASSIFICATION is True


@pytest.mark.parametrize(
    ("value", "pinned"),
    [
        ("coding/medium", "coding/medium"),
        ("long-context/high/novel", "long-context/high/novel"),
        ("coding/extreme", None),
        ("Coding/Medium", None),
        ("coding/medium; drop table", None),
        (42, None),
        (None, None),
    ],
)
def test_only_a_table_key_is_forwarded(value: object, pinned: str | None) -> None:
    assert svc._pinned_classification({"classification": value}) == pinned


def test_the_ladder_inputs_carry_the_pin_and_the_votes() -> None:
    req = RecommendRequest(
        task_description="plan a release", context={"classification": "planning/high"}
    )
    kwargs = svc._ladder_inputs(req).scoring_kwargs
    assert kwargs["classification"] == "planning/high"
    assert kwargs["classification_votes"] == svc.CLASSIFICATION_VOTES == 2
    bare = svc._ladder_inputs(RecommendRequest(task_description="plan a release"))
    assert bare.scoring_kwargs["classification"] is None


def test_the_visitor_path_runs_no_votes() -> None:
    # The visitor pays for exactly the one call they asked for (Phase 4.11).
    import app.visitor as visitor

    source = inspect.getsource(visitor)
    assert "ladder_once(req, spec.hint, config, votes=False)" in source
