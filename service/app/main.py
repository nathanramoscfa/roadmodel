# service/app/main.py
from __future__ import annotations

import os
import time

from fastapi import Depends, FastAPI, Response

from .auth import require_bearer
from .models import LadderResponse, RecommendRequest, RecommendResponse
from .recommend import recommend, recommend_ladder
from .score import router as score_router
from .visitor import router as visitor_router

# Disable the interactive docs + OpenAPI schema on deployed runtimes
# (audit M4). They are served unauthenticated on the same host and would
# advertise the exact request schema — including `context.force_provider`
# — to anyone probing the API, lowering the bar for abuse. Vercel sets
# VERCEL=1 in every deployment runtime; keep the docs on locally (uvicorn,
# tests) for development convenience. Mirrors the VERCEL-detection used by
# the web tier's e2e-mode gate.
_DOCS_ENABLED = os.environ.get("VERCEL") != "1"

app = FastAPI(
    title="roadmodel-service",
    version="0.4.0",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)


# What this deployment can do beyond /v1/recommend, so the web edge and the
# operator's probes can tell an older service from a newer one: "visitor-key"
# is the visitor lane (POST /v1/visitor/recommend/ladder, app/visitor.py);
# "score" is the keyless ladder from the scoring core (POST /v1/score,
# app/score.py).
CAPABILITIES: list[str] = ["visitor-key", "score"]


@app.get("/healthz")
def healthz() -> dict[str, str | list[str]]:
    from importlib.metadata import version

    return {
        "status": "ok",
        "roadmodel_version": version("roadmodel"),
        "capabilities": CAPABILITIES,
    }


# Phase 4 Step 7 — the web tier decomposes its opaque provider_ms
# span via this header rather than treating the entire upstream
# fetch as a single black box. Header format is the same
# semicolon-separated key=value form web/lib/latency.ts parses:
#
#     service_scoring_ms=<int>;service_provider_ms=<int>
#
# service_provider_ms is the time spent inside
# roadmodel.recommend.recommend_structured (which holds the Gemini
# generate_content call); service_scoring_ms is everything else
# this endpoint does — request validation, fallback chain
# walking, response model assembly. Together they sum to the
# wall-clock time the web tier observes in its provider span.
# Authenticated edge-only endpoint. `require_bearer` validates an
# `Authorization: Bearer <ROADMODEL_INTERNAL_TOKEN>` header in constant
# time against the shared secret the Next.js edge carries. This is the
# spend boundary: without it the service is world-callable and every
# request is a paid Gemini call (the web gate + Upstash rate limit only
# front the web project, not this one). Fail-closed by construction — a
# missing/unconfigured token yields 401/503, never a free upstream call.
@app.post(
    "/v1/recommend",
    response_model=RecommendResponse,
    dependencies=[Depends(require_bearer)],
)
def recommend_endpoint(req: RecommendRequest, response: Response) -> RecommendResponse:
    overall_start = time.perf_counter()
    provider_elapsed_ms = 0
    try:
        provider_start = time.perf_counter()
        result = recommend(req)
        provider_elapsed_ms = int((time.perf_counter() - provider_start) * 1000)
        return result
    finally:
        total_elapsed_ms = int((time.perf_counter() - overall_start) * 1000)
        scoring_ms = max(0, total_elapsed_ms - provider_elapsed_ms)
        response.headers["X-Roadmodel-Timing"] = (
            f"service_scoring_ms={scoring_ms};service_provider_ms={provider_elapsed_ms}"
        )


# Tasks #1/#3 — the single-call Cost/Balanced/Quality ladder. The web edge calls
# this (behind its LADDER_ENABLED flag) instead of fanning out three separate
# priority calls, so the three picks are anchored + tier-laddered by construction
# (Quality first, Balanced/Cost strictly lower) rather than three independent
# calls that can collapse onto the same model. Same auth boundary + timing header
# as /v1/recommend; on any provider/parse failure it raises (mapped to 5xx) and
# the edge falls back to its fan-out path.
@app.post(
    "/v1/recommend/ladder",
    response_model=LadderResponse,
    dependencies=[Depends(require_bearer)],
)
def recommend_ladder_endpoint(req: RecommendRequest, response: Response) -> LadderResponse:
    overall_start = time.perf_counter()
    provider_elapsed_ms = 0
    try:
        provider_start = time.perf_counter()
        result = recommend_ladder(req)
        provider_elapsed_ms = int((time.perf_counter() - provider_start) * 1000)
        return result
    finally:
        total_elapsed_ms = int((time.perf_counter() - overall_start) * 1000)
        scoring_ms = max(0, total_elapsed_ms - provider_elapsed_ms)
        response.headers["X-Roadmodel-Timing"] = (
            f"service_scoring_ms={scoring_ms};service_provider_ms={provider_elapsed_ms}"
        )


# Phase 4.11 Step 2 — the visitor lane: one ladder call on the visitor's own
# key, no fallback chain (app/visitor.py). Same bearer boundary as above.
app.include_router(visitor_router)

# Phase 4.11 Step 4 — keyless picks: the scoring core's ladder for a classified
# task, no engine and no provider key (app/score.py). Same bearer boundary.
app.include_router(score_router)
