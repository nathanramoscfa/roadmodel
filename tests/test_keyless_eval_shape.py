# tests/test_keyless_eval_shape.py
"""docs/keyless-eval.json: the keyless agreement record and its bar.

scripts/eval_keyless_agreement.py writes the record: per probe of the 12-probe
battery, the engine ladder's modal model per rung and the scoring core's pick
for the probe's hand labels. Keyless picks go public only while the record
meets the bar (agree >= 27 of 36, no Quality rung under tier), so the bar is
pinned here, and every derived figure is recomputed from the rows it sums.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
RECORD = REPO / "docs" / "keyless-eval.json"
LABELS = REPO / "scripts" / "keyless_probe_labels.json"
BATTERY = REPO / "scripts" / "eval_recommend_engines.py"

BAR_AGREE = 27
STEP3_MINIMUM = {"low": "B", "medium": "A", "high": "S"}
LETTERS = "DCBAS"


def _record() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RECORD.read_text(encoding="utf-8"))
    return data


def _probes() -> list[dict[str, str]]:
    """PROBES from the battery's source, read without importing it."""
    tree = ast.parse(BATTERY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PROBES":
            assert node.value is not None
            value: list[dict[str, str]] = ast.literal_eval(node.value)
            return value
    raise AssertionError("PROBES not found in scripts/eval_recommend_engines.py")


def test_the_record_meets_the_bar() -> None:
    record = _record()
    assert record["total"] == 36
    assert record["agree"] >= BAR_AGREE
    assert record["under_tier"] == 0


def test_the_totals_are_the_rows() -> None:
    record = _record()
    rungs = [r for row in record["probes"] for r in row["rungs"]]
    assert record["total"] == len(rungs)
    assert record["agree"] == sum(1 for r in rungs if r["agree"])
    assert record["under_tier"] == sum(1 for row in record["probes"] if row["under_tier"])


def test_every_probe_is_scored_once_on_its_labels() -> None:
    record = _record()
    labels = {
        row["probe_id"]: {k: row[k] for k in ("category", "complexity", "novel")}
        for row in json.loads(LABELS.read_text(encoding="utf-8"))["labels"]
    }
    assert [row["probe_id"] for row in record["probes"]] == [p["id"] for p in _probes()]
    assert set(labels) == {p["id"] for p in _probes()}
    for row in record["probes"]:
        assert row["labels"] == labels[row["probe_id"]]
        assert [r["priority"] for r in row["rungs"]] == ["quality", "balanced", "cost"]


def _modal(values: list[str | None]) -> str | None:
    present = [v for v in values if v]
    if not present:
        return None
    counts = Counter(present)
    top = max(counts.values())
    return next(v for v in present if counts[v] == top)


def test_each_rung_is_the_modal_engine_pick_against_the_scorer() -> None:
    record = _record()
    for row in record["probes"]:
        for rung in row["rungs"]:
            assert len(rung["engine_runs"]) == record["runs_per_probe"]
            assert rung["engine_modal"] == _modal(rung["engine_runs"])
            agrees = rung["engine_modal"] is not None and (
                rung["engine_modal"].lower() == rung["scorer"].lower()
            )
            assert rung["agree"] is agrees


def test_under_tier_reads_the_step3_minimum() -> None:
    for row in _record()["probes"]:
        assert row["quality_minimum"] == STEP3_MINIMUM[row["labels"]["complexity"]]
        below = LETTERS.find(row["quality_rating"]) < LETTERS.find(row["quality_minimum"])
        assert row["under_tier"] is below


def test_the_record_carries_no_token_key_or_probe_text() -> None:
    text = RECORD.read_text(encoding="utf-8")
    for probe in _probes():
        if len(probe["task"]) > 8:
            assert probe["task"] not in text
            assert json.dumps(probe["task"])[1:-1] not in text
    assert "Bearer" not in text
    assert not re.search(r"sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}", text)
    assert "task_description" not in text
