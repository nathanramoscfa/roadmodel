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
