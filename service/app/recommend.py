# service/app/recommend.py
from roadmodel.recommend import recommend_structured  # type: ignore[import-untyped]

from .models import RecommendRequest, RecommendResponse


def recommend(req: RecommendRequest) -> RecommendResponse:
    rec = recommend_structured(
        req.task_description,
        context=req.context,
    )
    return RecommendResponse(
        model=rec.model,
        platform=rec.platform,
        settings=rec.settings,
        session_cost_estimate=rec.session_cost_estimate.model_dump(),
        comparison_table=[c.model_dump() for c in rec.comparison_table],
    )
