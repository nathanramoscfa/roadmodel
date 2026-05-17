# service/app/main.py
from fastapi import Depends, FastAPI

from .auth import require_bearer
from .models import RecommendRequest, RecommendResponse
from .recommend import recommend

app = FastAPI(
    title="roadmodel-service",
    version="0.3.0",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    from importlib.metadata import version

    return {
        "status": "ok",
        "roadmodel_version": version("roadmodel"),
    }


@app.post(
    "/v1/recommend",
    response_model=RecommendResponse,
    dependencies=[Depends(require_bearer)],
)
def recommend_endpoint(req: RecommendRequest) -> RecommendResponse:
    return recommend(req)
