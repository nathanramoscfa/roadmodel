"""scripts/eval_classification.py: how the engine classifies the soak probes.

The engine's classification picks the ladder-table row, so it is what B2 (the
picks against gold) and B7 (determinism) hinge on. The eval scores each probe's
runs: agreement of the modal row with the label or an alternative reading, an
under-read below every accepted complexity, and run-to-run stability.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "eval_classification", REPO / "scripts" / "eval_classification.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_classification"] = mod
    spec.loader.exec_module(mod)
    return mod


ec = _load()

PROBE = {
    "id": "p",
    "category": "coding",
    "complexity": "medium",
    "novel": False,
    "alternatives": [{"category": "agentic", "complexity": "high", "novel": False}],
}


def test_a_stable_agreeing_probe() -> None:
    row = ec.score_probe(PROBE, ["coding/medium"] * 3)
    assert row["agrees"] and row["stable"] and not row["under"]


def test_an_alternative_reading_agrees() -> None:
    assert ec.score_probe(PROBE, ["agentic/high"] * 3)["agrees"]


def test_one_low_run_is_an_under_read_and_unstable() -> None:
    row = ec.score_probe(PROBE, ["coding/low", "coding/medium", "coding/medium"])
    assert row["agrees"]  # the modal row is still the label's
    assert row["under"] and not row["stable"]


def test_a_failed_run_is_never_stable() -> None:
    row = ec.score_probe(PROBE, ["coding/medium", None, "coding/medium"])
    assert row["agrees"] and not row["stable"]


def test_the_default_engine_is_the_registrys() -> None:
    engine = ec.default_engine()
    assert {"hint", "provider", "model", "thinking_budget", "ladder_max_output_tokens"} <= set(
        engine
    )
