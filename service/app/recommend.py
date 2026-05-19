# service/app/recommend.py
from __future__ import annotations

from roadmodel.config import load_config  # type: ignore[import-untyped]
from roadmodel.recommend import recommend_structured  # type: ignore[import-untyped]

from .models import RecommendRequest, RecommendResponse


def recommend(req: RecommendRequest) -> RecommendResponse:
    config = load_config(cli_provider=None, cli_model=None, cli_user_context=None)
    result = recommend_structured(req.task_description, config)
    return RecommendResponse(
        model=result["model"],
        platform=result["platform"],
        settings=result["settings"],
        session_cost_estimate=result.get("session_cost_estimate"),
        comparison_table=result.get("comparison_table") or [],
    )
