# tests/test_engine_eval_mirror.py
"""The service reads the engine eval from a copy beside its registry
(service/app/engine-eval.json), because it deploys from service/ and cannot
read docs/. The copy gates which engines a visitor's own key may run
(service/app/engines.py EVALUATED), so it must say exactly what
docs/engine-eval.json says. scripts/eval_recommend_engines.py --summary-json
writes both; a hand edit to one of them fails here."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def test_the_service_copy_of_the_engine_eval_matches_docs() -> None:
    docs = (_REPO / "docs" / "engine-eval.json").read_text(encoding="utf-8")
    mirror = (_REPO / "service" / "app" / "engine-eval.json").read_text(encoding="utf-8")
    assert mirror == docs, (
        "service/app/engine-eval.json differs from docs/engine-eval.json: "
        "copy docs/engine-eval.json over it (the eval script writes both)"
    )


def test_the_package_google_default_is_the_evaluated_visitor_engine() -> None:
    """A bare `roadmodel recommend` or the MCP server with only a Google key
    runs google.DEFAULT_MODEL. It stayed on gemini-2.5-pro after the service
    moved on, and on 2026-10-21 a newer key got 404 NOT_FOUND for it. Hold it
    to the engine the service runs on a visitor's own Google key, which the
    eval measured through this package."""
    import json

    from roadmodel.providers import google

    registry = json.loads((_REPO / "service" / "app" / "engines.json").read_text("utf-8"))
    hint = registry["visitor_defaults"]["google"]
    engine = next(e for e in registry["engines"] if e["hint"] == hint)
    evaluated = json.loads((_REPO / "docs" / "engine-eval.json").read_text("utf-8"))["engines"]
    assert google.DEFAULT_MODEL == engine["model"]
    assert evaluated[hint]["passed"] == evaluated[hint]["probes"]
