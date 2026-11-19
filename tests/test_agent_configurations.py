"""Agent configurations are ranked with their own evidence and controls."""

import json
from pathlib import Path
from typing import Any

import pytest

from roadmodel import agent_configurations, scoring

DOCS = Path(__file__).resolve().parents[1] / "docs"
PRESET = "antigravity-orchestrator-neon"
ULTRACODE = "claude-code-opus-5-5-high-ultracode"
TASK = scoring.Task("agentic", "high")
ULTRA = "| Google AI Ultra ($200) | $200 | Google | Antigravity |"
PRO = "| Google AI Pro | $20 | Google | Antigravity |"
CLAUDE_MAX = "| claude.ai Max ($200) | $200 | Anthropic | Claude Code |"


def context(*plans: str) -> str:
    return (
        "## Active subscriptions\n\n| Subscription | Monthly | Provider | Coverage |\n"
        + "\n".join(plans)
    )


@pytest.fixture
def configurations(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    entries = json.loads((DOCS / "agent-configurations.json").read_text())["configurations"]
    monkeypatch.setattr(agent_configurations, "configurations", lambda: entries)
    return entries


@pytest.fixture
def catalog() -> dict[str, Any]:
    return json.loads((DOCS / "catalog.json").read_text())  # type: ignore[no-any-return]


@pytest.fixture
def benchmarks() -> dict[str, Any]:
    return json.loads((DOCS / "benchmarks.json").read_text())["models"]  # type: ignore[no-any-return]


def add_evidence(entry: dict[str, Any], configuration_id: str | None = None) -> None:
    entry["evidence"] = {
        "configuration_id": configuration_id or entry["id"],
        "source": "https://evaluation.example/eval",
        "aa_index": {"kind": "estimated", "value": 90, "band": 4},
        "price": {"input_per_1m": 0.2, "output_per_1m": 1.0},
        "grades": dict.fromkeys(scoring.CATEGORIES, "S"),
    }


def test_index_or_grades_from_another_configuration_cannot_rank(
    configurations: list[dict[str, Any]], catalog: dict[str, Any], benchmarks: dict[str, Any]
) -> None:
    preset = next(c for c in configurations if c["id"] == PRESET)
    add_evidence(preset, "gemini-4-neon")
    result = scoring.rank(TASK, context(ULTRA, CLAUDE_MAX), catalog=catalog, benchmarks=benchmarks)
    assert not any(c.configuration_index is not None for c in result.candidates)


@pytest.mark.parametrize("planner, available_on_pro", [("carbon", False), ("argon", True)])
def test_orchestrator_plan_eligibility_when_evidence_is_available(
    configurations: list[dict[str, Any]],
    catalog: dict[str, Any],
    benchmarks: dict[str, Any],
    planner: str,
    available_on_pro: bool,
) -> None:
    preset_id = f"antigravity-orchestrator-{planner}"
    preset = next(c for c in configurations if c["id"] == preset_id)
    add_evidence(preset)
    for plan, available in ((ULTRA, True), (PRO, available_on_pro)):
        result = scoring.rank(TASK, context(plan), catalog=catalog, benchmarks=benchmarks)
        assert (preset_id in {c.model_id for c in result.candidates}) is available


def test_preset_requires_an_eligible_plan_and_has_one_fixed_level(
    configurations: list[dict[str, Any]], catalog: dict[str, Any], benchmarks: dict[str, Any]
) -> None:
    preset = next(c for c in configurations if c["id"] == PRESET)
    add_evidence(preset)
    for text in ("", context("| Google AI Plus | $5 | Google | Antigravity |")):
        result = scoring.rank(TASK, text, catalog=catalog, benchmarks=benchmarks)
        assert PRESET not in {c.model_id for c in result.candidates}
    result = scoring.rank(TASK, context(ULTRA), catalog=catalog, benchmarks=benchmarks)
    candidate = next(c for c in result.candidates if c.model_id == PRESET)
    assert candidate.effort == "fixed"
    assert candidate.blended_price_usd == pytest.approx(0.4)
    assert candidate.effort_multiplier == 1
    assert candidate.aa_estimated

    ladder = scoring.settings_ladder(TASK, context(ULTRA), catalog=catalog, benchmarks=benchmarks)
    assert ladder is not None
    pick = ladder["columns"]["cost"]
    assert pick["model"] == "Orchestrator (Neon)"
    assert pick["level_cell"] == "Fixed"
    assert pick["aa_index"] == 90
    assert pick["value_score"] is not None
    assert pick["task_grade"] == "S"
    assert "Task grade" in ladder["markdown"]
    assert "≈90" in ladder["markdown"]


def test_ultracode_preserves_the_picker_model_effort_and_switch(
    configurations: list[dict[str, Any]], catalog: dict[str, Any], benchmarks: dict[str, Any]
) -> None:
    ultracode = next(c for c in configurations if c["id"] == ULTRACODE)
    add_evidence(ultracode)
    ladder = scoring.settings_ladder(
        TASK, context(CLAUDE_MAX), phase=True, catalog=catalog, benchmarks=benchmarks
    )
    assert ladder is not None
    pick = ladder["columns"]["quality"]
    assert pick["model_id"] == ULTRACODE
    assert pick["model"] == "Opus 5.5"
    assert pick["level_cell"] == "High"
    assert pick["ultracode"] == "On"
    assert "Ultracode" in ladder["markdown"]
