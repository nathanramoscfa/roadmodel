# service/app/main.py
from fastapi import FastAPI

from .models import RecommendRequest, RecommendResponse
from .recommend import recommend

app = FastAPI(
    title="roadmodel-service",
    version="0.4.0",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    from importlib.metadata import version

    return {
        "status": "ok",
        "roadmodel_version": version("roadmodel"),
    }


@app.post("/v1/recommend", response_model=RecommendResponse)
def recommend_endpoint(req: RecommendRequest) -> RecommendResponse:
    return recommend(req)
