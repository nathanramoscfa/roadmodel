"""scripts/judge_recommend.py: B2 (picks against gold labels) and B6 (the judge).

B2 recomputes each probe's gold ladder-table row and fails a probe whose
PRIMARY or QUALITY rung is weaker there. B6 asks a judge whether a selector user
would accept each ladder; it only counts when the judge's maker differs from
the engine's, every row was judged, and every seeded control was graded as
expected. The judge runs `claude -p` on the subscription token and never reads
an API key.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "judge_recommend", REPO / "scripts" / "judge_recommend.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["judge_recommend"] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


jr = _load()


@pytest.fixture(scope="module")
def world() -> dict[str, Any]:
    from roadmodel import cost

    context = jr.bundled_context()
    return {
        "context": context,
        "table": jr.scoring.ladder_table(context),
        "catalog": cost._load_catalog(),
        "probes": jr.load_probes(),
    }


def _gold(world: dict[str, Any], probe_id: str) -> Any:
    probe = next(p for p in world["probes"] if p["id"] == probe_id)
    return probe, world["table"][jr.gold_key(probe)]


def _row(probe_id: str, ladder: list[dict[str, Any]], maker: str = "OpenAI") -> dict[str, Any]:
    return {
        "id": probe_id,
        "mode": "anon",
        "iter": 1,
        "status": 200,
        "ladder": ladder,
        "engine": {"maker": maker},
    }


# --------------------------------------------------------------------------- B2


def test_the_gold_row_passes_b2(world: dict[str, Any]) -> None:
    probe, gold = _gold(world, "legacy-refactor")
    row = _row(probe["id"], jr.gold_ladder_rows(gold, world["catalog"]))
    quality = jr.headline_quality(gold.task, world["context"], [])
    assert jr.b2_problems(jr.app_picks(row), gold, quality) == []


def test_a_quality_rung_demoted_to_the_cheapest_model_fails_b2(world: dict[str, Any]) -> None:
    probe, gold = _gold(world, "legacy-refactor")
    ladder = jr.gold_ladder_rows(gold, world["catalog"])
    cheapest = gold.frontier[0].candidate
    assert cheapest.model_name != gold.rungs["quality"].candidate.model_name
    best = next(p for p in ladder if p["priority"] == "best")
    best.update(model=cheapest.model_name, platform=cheapest.platform_name)
    quality = jr.headline_quality(gold.task, world["context"], [])
    problems = jr.b2_problems(jr.app_picks(_row(probe["id"], ladder)), gold, quality)
    assert len(problems) == 1 and problems[0].startswith("quality:")


def test_the_same_model_at_a_lower_effort_fails_and_a_stronger_one_passes(
    world: dict[str, Any],
) -> None:
    probe, gold = _gold(world, "legacy-refactor")
    quality = jr.headline_quality(gold.task, world["context"], [])
    picks = jr.app_picks(_row(probe["id"], jr.gold_ladder_rows(gold, world["catalog"])))
    q = picks["quality"]
    lower = jr.Pick(q.model, q.platform, "low")
    if jr.level_rank("low") < jr.level_rank(q.level):
        assert jr.b2_problems({**picks, "quality": lower}, gold, quality)
    strongest = max(quality, key=lambda m: quality[m])
    assert jr.b2_problems({**picks, "quality": jr.Pick(strongest, None, None)}, gold, quality) == []


def test_a_model_outside_the_pool_fails_b2(world: dict[str, Any]) -> None:
    _, gold = _gold(world, "coding-cli")
    quality = jr.headline_quality(gold.task, world["context"], [])
    picks = {t: jr.Pick("Not A Model", None, None) for t in ("cost", "balanced", "quality")}
    assert len(jr.b2_problems(picks, gold, quality)) == 2


def test_a_defensible_alternative_reading_passes_b2(world: dict[str, Any]) -> None:
    probe = {
        "id": "x",
        "category": "coding",
        "complexity": "high",
        "novel": False,
        "alternatives": [{"category": "coding", "complexity": "low", "novel": False}],
    }
    low = world["table"]["coding/low"]
    picks = jr.app_picks(_row("x", jr.gold_ladder_rows(low, world["catalog"])))
    assert jr.b2_probe(picks, probe, world["table"], world["context"], []) == []
    strict = {k: v for k, v in probe.items() if k != "alternatives"}
    assert jr.b2_probe(picks, strict, world["table"], world["context"], [])


def test_b2_holds_at_90_percent_with_every_probe_answered() -> None:
    ten = {f"p{i}": [] for i in range(10)}
    assert jr.b2_check(ten, 10).passed
    assert jr.b2_check({**ten, "p0": ["quality: x"]}, 10).passed  # 9/10
    assert not jr.b2_check({**ten, "p0": ["x"], "p1": ["x"]}, 10).passed  # 8/10
    assert not jr.b2_check({k: v for k, v in ten.items() if k != "p9"}, 10).passed


def test_only_full_anonymous_first_pass_rows_are_scored() -> None:
    full = [{"priority": p, "model": "M"} for p in ("cheap", "balanced", "best")]
    rows = [
        {**_row("a", full), "iter": 2},
        {**_row("b", full), "mode": "authed"},
        {**_row("c", full), "status": 500},
        _row("d", full[:2]),
        _row("e", full),
    ]
    assert list(jr.judged_rows(rows)) == ["e"]


def test_level_rank_reads_every_dials_words() -> None:
    assert jr.level_rank("XHigh") == jr.level_rank("xhigh") > jr.level_rank("High")
    assert jr.level_rank("Ultracode") == jr.level_rank("max")
    assert jr.level_rank(None) is None


# --------------------------------------------------------------------------- B6


def _graded(*fails: tuple[str, str]) -> dict[str, Any]:
    failing = dict(fails)
    return {
        "structured_output": {
            "criteria": [
                {
                    "id": c,
                    "evidence": "a fact from the fact sheet",
                    "pass": c not in failing,
                    "severity": failing.get(c, "minor"),
                }
                for c in jr.CRITERIA
            ],
            "summary": "s",
            "accept": not any(sev == "blocker" for sev in failing.values()),
        },
        "total_cost_usd": 0.02,
    }


def test_a_verdict_accepts_unless_a_criterion_fails_as_a_blocker() -> None:
    assert jr.verdict_from("k", _graded()).accepted is True
    assert jr.verdict_from("k", _graded(("J5", "minor"))).accepted is True
    v = jr.verdict_from("k", _graded(("J2", "blocker")))
    assert v.accepted is False and v.blockers[0].startswith("J2")
    bad = _graded()
    bad["structured_output"]["criteria"].pop()
    assert jr.verdict_from("k", bad).accepted is None


def test_a_placeholder_or_self_contradicting_verdict_is_no_verdict() -> None:
    # 2026-10-08: the judge passed J6 with evidence "placeholder" while its own
    # summary said the rationale wrote the story.
    thin = _graded()
    thin["structured_output"]["criteria"][5]["evidence"] = "placeholder"
    assert jr.verdict_from("k", thin).accepted is None
    contradicts = _graded(("J6", "blocker"))
    contradicts["structured_output"]["accept"] = True
    assert jr.verdict_from("k", contradicts).accepted is None


def test_reasoning_comes_before_every_grade_in_the_schema() -> None:
    assert list(jr.JUDGE_SCHEMA["properties"]) == ["summary", "criteria", "accept"]
    item = jr.JUDGE_SCHEMA["properties"]["criteria"]["items"]["properties"]
    assert list(item) == ["id", "evidence", "pass", "severity"]


def _items(n_rows: int) -> list[Any]:
    rows = [jr.Item(f"p{i}", "t", [{}]) for i in range(n_rows)]
    return rows + [jr.Item("c-bad", "t", [{}], False), jr.Item("c-good", "t", [{}], True)]


def _verdicts(items: list[Any], rejected: set[str] = frozenset()) -> dict[str, Any]:
    out = {}
    for i in items:
        accept = i.expect if i.expect is not None else i.key not in rejected
        out[i.key] = jr.Verdict(i.key, accept, [] if accept else ["J2: x"])
    return out


def test_b6_holds_at_95_percent_with_valid_controls() -> None:
    items = _items(20)
    assert jr.b6_check(_verdicts(items, {"p0"}), items, {"OpenAI"}).passed  # 19/20
    assert not jr.b6_check(_verdicts(items, {"p0", "p1"}), items, {"OpenAI"}).passed


def test_a_misgraded_control_invalidates_the_judge() -> None:
    items = _items(20)
    verdicts = _verdicts(items)
    verdicts["c-bad"] = jr.Verdict("c-bad", True)
    check = jr.b6_check(verdicts, items, {"OpenAI"})
    assert not check.passed and "JUDGE INVALID" in check.detail


def test_the_judge_never_grades_its_own_makers_engine() -> None:
    items = _items(20)
    check = jr.b6_check(_verdicts(items), items, {"OpenAI", jr.JUDGE_MAKER})
    assert not check.passed and "self-judging" in check.detail


def test_an_unjudged_row_fails_b6() -> None:
    items = _items(20)
    verdicts = _verdicts(items)
    verdicts["p3"] = jr.Verdict("p3", None, error="timeout")
    assert not jr.b6_check(verdicts, items, {"OpenAI"}).passed


def test_the_controls_cover_both_directions(world: dict[str, Any]) -> None:
    items = jr.controls(world["probes"], world["table"], world["context"], [], world["catalog"])
    kinds = {i.key.split(":")[1]: i.expect for i in items}
    assert kinds["demote"] is False and kinds["leak"] is False and kinds["maker"] is False
    assert kinds["gold"] is True
    maker = next(i for i in items if i.key.startswith("control:maker"))
    cost = next(p for p in maker.ladder if p["priority"] == "cheap")
    assert cost["model"] in {
        c.model_name
        for c in jr.scoring.rank(jr.scoring.Task("coding", "high"), world["context"]).candidates
        if c.provider == "anthropic"
    }


def test_the_fact_sheet_and_prompt_carry_no_engine_name(world: dict[str, Any]) -> None:
    system = jr.system_prompt(world["context"], [])
    assert "<fact-sheet>" in system and "AA Intelligence Index" in system
    _, gold = _gold(world, "coding-cli")
    message = jr.render_ladder("task", jr.gold_ladder_rows(gold, world["catalog"]))
    assert "engine" not in message.lower()
    assert message.count("backup") == 3


def test_judge_all_caps_calls_and_never_raises() -> None:
    real = jr.claude_judge("/dev/null", "m")
    calls: list[str] = []

    def fake(system: str, message: str) -> dict[str, Any]:
        calls.append(message)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return _graded()

    # The fake must stand in for the real judge's call shape.
    assert list(inspect.signature(fake).parameters) == ["system", "message"]
    assert len(inspect.signature(real).parameters) == 2
    items = [jr.Item(f"p{i}", "t", [{"priority": "cheap"}]) for i in range(4)]
    # p1's first call raises and is retried: five calls for four items, cap 4.
    verdicts = jr.judge_all(items, fake, "sys", max_calls=4, concurrency=1)
    assert len(calls) == 4
    assert [v.accepted for v in verdicts.values()].count(True) == 3
    assert "cap" in verdicts["p3"].error


def test_the_judge_runs_claude_with_no_tools_and_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"], seen["env"] = cmd, kw["env"]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(_graded()), "")

    # The keywords the real call passes are subprocess.run's own.
    assert {"input", "capture_output", "timeout"} <= set(
        inspect.signature(subprocess.run).parameters
    )
    monkeypatch.setattr(jr.subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-pass")
    out = jr.claude_judge("/tmp/sys.md", "claude-opus-5-5")("sys", "msg")
    assert out["structured_output"]["criteria"]
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == jr.JUDGE_SCHEMA
    assert "ANTHROPIC_API_KEY" not in seen["env"]


# --------------------------------------------------------------------- workflow


def _steps() -> dict[str, dict[str, Any]]:
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "recommend-soak.yml").read_text())
    return {s["name"]: s for s in wf["jobs"]["soak"]["steps"] if "name" in s}


def test_the_soak_workflow_runs_the_judge_on_the_subscription_token() -> None:
    steps = _steps()
    install = steps["Install the roadmodel production runs"]["run"]
    assert "healthz" in install and "roadmodel==" in install
    judge = steps["Score B2 and B6 (judge)"]
    token = judge["env"]["CLAUDE_CODE_OAUTH_TOKEN"]
    assert token == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"  # noqa: S105 - a secret reference
    assert "ANTHROPIC_API_KEY" not in json.dumps(judge)
    assert "scripts/judge_recommend.py" in judge["run"]
    # The judge's step never sees the soak's database key.
    assert "SUPABASE_SERVICE_ROLE_KEY" not in json.dumps(judge)
    track = steps["Track regression in a single issue"]
    assert "steps.judge.outputs.exit" in track["if"]
    assert "JUDGE SCORECARD" in track["with"]["script"]
