"""scripts/soak_probes.json: the soak's probe battery and its gold labels.

The Phase 4.5 quality bar is measured on at least 30 prompts spanning all seven
task categories plus edge cases. The soak (scripts/soak-recommend.ts) sends the
tasks and the judge (scripts/judge_recommend.py) scores B2 against the labels,
so both read this one file. Its first twelve probes are the engine-eval battery
with the keyless eval's hand labels; they must not drift apart.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from roadmodel import scoring

REPO = Path(__file__).resolve().parent.parent
PROBES = REPO / "scripts" / "soak_probes.json"
KEYLESS_LABELS = REPO / "scripts" / "keyless_probe_labels.json"
ENGINE_BATTERY = REPO / "scripts" / "eval_recommend_engines.py"


def _probes() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = json.loads(PROBES.read_text(encoding="utf-8"))["probes"]
    return probes


def _engine_battery() -> list[dict[str, str]]:
    tree = ast.parse(ENGINE_BATTERY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PROBES":
            assert node.value is not None
            battery: list[dict[str, str]] = ast.literal_eval(node.value)
            return battery
    raise AssertionError("PROBES not found in scripts/eval_recommend_engines.py")


def test_the_battery_meets_the_bars_size_and_spread() -> None:
    probes = _probes()
    assert len(probes) >= 30
    assert len({p["id"] for p in probes}) == len(probes)
    assert {p["category"] for p in probes} == set(scoring.CATEGORIES)
    assert {p["complexity"] for p in probes} == set(scoring.COMPLEXITIES)
    assert any(p["novel"] for p in probes)
    assert any(p["id"].startswith("edge-") for p in probes)


def test_every_label_is_one_the_scorer_reads() -> None:
    for p in _probes():
        assert p["category"] in scoring.CATEGORIES, p["id"]
        assert p["complexity"] in scoring.COMPLEXITIES, p["id"]
        assert isinstance(p["novel"], bool), p["id"]
        # Novel only exists at High (scoring.table_keys).
        assert not p["novel"] or p["complexity"] == "high", p["id"]
        assert p["task"].strip() and len(p["task"]) <= 50_000, p["id"]
        assert p["reason"].strip(), p["id"]
        for alt in p.get("alternatives", []):
            assert alt["category"] in scoring.CATEGORIES, p["id"]
            assert alt["complexity"] in scoring.COMPLEXITIES, p["id"]
            assert not alt["novel"] or alt["complexity"] == "high", p["id"]
            assert alt["reason"].strip(), p["id"]


def test_the_first_twelve_match_the_engine_battery_and_the_keyless_labels() -> None:
    probes = _probes()
    battery = _engine_battery()
    labels = {
        lab["probe_id"]: lab
        for lab in json.loads(KEYLESS_LABELS.read_text(encoding="utf-8"))["labels"]
    }
    assert [p["id"] for p in probes[: len(battery)]] == [b["id"] for b in battery]
    for p, b in zip(probes, battery, strict=False):
        assert p["task"] == b["task"], p["id"]
        lab = labels[p["id"]]
        assert (p["category"], p["complexity"], p["novel"]) == (
            lab["category"],
            lab["complexity"],
            lab["novel"],
        ), p["id"]


def test_the_soak_sends_this_battery_and_records_the_ladder() -> None:
    soak = (REPO / "scripts" / "soak-recommend.ts").read_text(encoding="utf-8")
    assert 'join(here, "soak_probes.json")' in soak
    # The judge reads the whole ladder and the engine from every row.
    assert "ladder: ladderOf(payload)" in soak
    assert "engine: (payload.engine ?? null)" in soak
    assert "process.env.SOAK_OUT" in soak
