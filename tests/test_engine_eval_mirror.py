# tests/test_engine_eval_mirror.py
"""The service reads the engine eval from a copy beside its registry
(service/app/engine-eval.json), because it deploys from service/ and cannot
read docs/. The copy gates which engines a visitor's own key may run
(service/app/engines.py EVALUATED), so it must say exactly what
docs/engine-eval.json says. scripts/eval_recommend_engines.py --summary-json
writes both; a hand edit to one of them fails here."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def test_the_service_copy_of_the_engine_eval_matches_docs() -> None:
    docs = (_REPO / "docs" / "engine-eval.json").read_text(encoding="utf-8")
    mirror = (_REPO / "service" / "app" / "engine-eval.json").read_text(encoding="utf-8")
    assert mirror == docs, (
        "service/app/engine-eval.json differs from docs/engine-eval.json: "
        "copy docs/engine-eval.json over it (the eval script writes both)"
    )


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google"])
def test_the_package_default_engine_is_an_evaluated_one(provider: str) -> None:
    """A bare `roadmodel recommend` or the MCP server with only this provider's
    key runs the adapter's DEFAULT_MODEL with its default settings. They rotted
    once: gemini-2.5-pro got 404 for a newer key (2026-10-21), and the Claude and
    OpenAI defaults were a generation behind. Each must be a registry engine, at
    the settings it was evaluated with, that passed every eval probe."""
    adapter = importlib.import_module(f"roadmodel.providers.{provider}")
    registry = json.loads((_REPO / "service" / "app" / "engines.json").read_text("utf-8"))
    evaluated = json.loads((_REPO / "docs" / "engine-eval.json").read_text("utf-8"))["engines"]
    engine = next(
        (
            e
            for e in registry["engines"]
            if e["provider"] == provider and e["model"] == adapter.DEFAULT_MODEL
        ),
        None,
    )
    assert engine is not None, f"{adapter.DEFAULT_MODEL} is not a registry engine"
    assert adapter.DEFAULT_THINKING_BUDGET == engine.get("thinking_budget")
    assert adapter.DEFAULT_TEMPERATURE == engine.get("temperature")
    result = evaluated[engine["hint"]]
    assert result["passed"] == result["probes"]
