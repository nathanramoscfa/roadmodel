# service/tests/test_ranks.py
"""Each pick ranked three deep (app/ranks.py).

The guarantees under test:

- the ranks and the weighed settings the service reads are the package's
  (``scoring.ranked_columns``);
- a ladder pick the frontier table placed carries its three ranks, and the
  response says what the task was read as and carries the settings its ladder
  weighed, each pick among them; a pick a guard replaced, a response the
  table did not place and a single pick carry none;
- Quick pick's answer carries the same ranks and settings;
- none of it ever costs an answer: a failure reading them leaves the picks as
  they were.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from roadmodel import scoring  # type: ignore[import-untyped]

_TOKEN = "test-internal-token"
_MODULES = ("app.main", "app.recommend", "app.visitor", "app.score", "app.ranks")
_TIERS = ("cost", "balanced", "quality")
# A profile two makers fund, so every column has a Runner-up from the other.
_CONTEXT = {"subscriptions": ["claude-max", "chatgpt-pro"], "consumption_headroom": "capped"}
_TASKS = (
    scoring.Task("coding", "high"),
    scoring.Task("planning", "high", True),
    scoring.Task("speed", "low"),
    scoring.Task("long-context", "medium"),
)


def _load(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", _TOKEN)
    for name in _MODULES:
        sys.modules.pop(name, None)
    return importlib.import_module("app.main")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return TestClient(_load(monkeypatch).app, headers={"Authorization": f"Bearer {_TOKEN}"})


def _scoring_text(context: dict[str, Any]) -> str:
    from app.funding import scoring_context_from_request

    text = scoring_context_from_request(context)
    assert text is not None
    return str(text)


def _options(column: dict[str, Any]) -> list[dict[str, Any] | None]:
    return [column, column["runner_up"], column["backup"]]


# --- The ranks are the package's ----------------------------------------------


@pytest.mark.parametrize("task", _TASKS, ids=lambda t: f"{t.category}/{t.complexity}")
def test_the_ranks_are_the_packages(task: scoring.Task) -> None:
    from app import ranks

    text = _scoring_text(_CONTEXT)
    out = scoring.ranked_columns(task, text)
    assert out is not None
    package = ranks.Read(out.columns, out.points)
    assert ranks.read(task, text) == package
    assert ranks.columns(task, text) == package.columns


def test_each_rank_is_another_maker_at_its_own_level_and_figures() -> None:
    from app import ranks
    from app.funding import load_catalog

    task = scoring.Task("coding", "high")
    text = _scoring_text(_CONTEXT)
    columns = ranks.columns(task, text)
    lad = scoring.ladder(task, text)
    assert columns is not None and lad is not None
    catalog = load_catalog()
    makers = {m["id"]: scoring._cost.model_provider(m["id"], catalog) for m in catalog["models"]}
    for tier in _TIERS:
        column = columns[tier]
        rung = lad.rungs[tier]
        # The Pick is the ladder's own rung, at the level it sets.
        assert (column["model_id"], column["platform_id"]) == (
            rung.candidate.model_id,
            rung.candidate.platform_id,
        )
        assert column["effort"] == scoring.normalize_level(rung.level)
        runner_up = column["runner_up"]
        assert runner_up is not None and not runner_up["stepped_down"]
        assert makers[runner_up["model_id"]] != makers[column["model_id"]]
        for option in _options(column):
            if option is None:
                continue
            # Each option is priced at its own level's token use.
            assert option["price_usd_per_1m"] and option["price_usd_per_1m"] > 0
            assert option["level_cell"]


def test_the_weighed_settings_hold_every_pick_and_draw_the_ladders_frontier() -> None:
    from app import ranks

    task = scoring.Task("coding", "high")
    text = _scoring_text(_CONTEXT)
    got = ranks.read(task, text)
    lad = scoring.ladder(task, text)
    assert got is not None and lad is not None
    by_key = {(p["model_id"], p["effort"]): p for p in got.points}
    assert len(by_key) == len(got.points)
    # The frontier drawn over them, each where the scorer ranks it (its index
    # less its margin), is the ladder's own.
    best, mine = float("-inf"), []
    for p in sorted(
        got.points,
        key=lambda p: (p["price_usd_per_1m"], -(p["aa_index"] - p["margin"]), p["model_id"]),
    ):
        if p["aa_index"] - p["margin"] > best:
            mine.append((p["model_id"], p["effort"]))
            best = p["aa_index"] - p["margin"]
    assert mine == [(f.candidate.model_id, f.candidate.evidence_level) for f in lad.points]
    assert all(p["margin"] >= 0 for p in got.points)
    assert all(p["margin"] == 0 for p in got.points if not p["estimated"])
    for rung in lad.rungs.values():
        c = rung.candidate
        point = by_key[(c.model_id, c.evidence_level)]
        assert point["adequate"] is True
        assert point["price_usd_per_1m"] == scoring.frontier_price(c)
    shaped = ranks.points(got.points)
    assert shaped is not None and len(shaped) == len(got.points)
    assert shaped[0].model_dump() == got.points[0]


def test_a_malformed_setting_is_left_out_of_the_response() -> None:
    from app import ranks

    good = {
        "model_id": "m",
        "platform_id": "p",
        "effort": "high",
        "aa_index": 50,
        "price_usd_per_1m": 2,
    }
    shaped = ranks.points(
        [
            good,
            {"model_id": "x"},
            {**good, "aa_index": "n/a"},
            {**good, "effort": None, "margin": 1.8},
        ]
    )
    assert shaped is not None
    assert [(p.model_id, p.effort, p.adequate, p.estimated, p.margin) for p in shaped] == [
        ("m", "high", True, False, 0.0),
        ("m", None, True, False, 1.8),
    ]
    negative = ranks.points([{**good, "margin": -3}])
    assert negative is not None and negative[0].margin == 0.0
    assert ranks.points([]) is None and ranks.points(None) is None
    assert ranks.points([{"model_id": "x"}]) is None
    assert len(ranks.points([good] * (ranks.MAX_POINTS + 5)) or []) == ranks.MAX_POINTS


def test_one_plan_is_ranked_its_own_models_only() -> None:
    """A caller who funds one maker is never ranked another maker's model
    they cannot run: the lower ranks are the Pick stepped down a level."""
    from app import ranks
    from app.funding import load_catalog

    catalog = load_catalog()
    makers = {m["id"]: scoring._cost.model_provider(m["id"], catalog) for m in catalog["models"]}
    got = ranks.read(
        scoring.Task("coding", "high"), _scoring_text({"subscriptions": ["claude-max"]})
    )
    assert got is not None
    funded = {makers[p["model_id"]] for p in got.points}
    assert len(funded) == 1
    for column in got.columns.values():
        assert makers[column["model_id"]] in funded
        for option in (column["runner_up"], column["backup"]):
            if option is not None:
                assert option["stepped_down"] and option["model_id"] == column["model_id"]


def test_a_task_key_names_its_task() -> None:
    from app import ranks

    assert ranks.task_from_key("coding/high") == scoring.Task("coding", "high")
    assert ranks.task_from_key("planning/high/novel") == scoring.Task("planning", "high", True)
    for bad in (
        None,
        7,
        "",
        "coding",
        "coding/extreme",
        "poetry/high",
        "coding/high/new",
        "a/b/c/d",
    ):
        assert ranks.task_from_key(bad) is None


def test_ranks_follow_the_picks_own_model_and_platform() -> None:
    from app import ranks

    column = ranks.columns(scoring.Task("coding", "high"), _scoring_text(_CONTEXT))
    assert column is not None
    quality = column["quality"]
    got = ranks.for_pick(quality, quality["model"], quality["platform"])
    assert got is not None
    assert got.pick.model == quality["model"] and got.pick.level == quality["level_cell"]
    assert got.runner_up is not None and got.runner_up.model == quality["runner_up"]["model"]
    # The engine may write the platform by its id, in any case.
    assert ranks.for_pick(quality, quality["model"].upper(), quality["platform_id"].upper())
    # Another model or platform: a guard replaced the row's pick.
    assert ranks.for_pick(quality, "Some Other Model", quality["platform"]) is None
    assert ranks.for_pick(quality, quality["model"], "Some Other Platform") is None
    assert ranks.for_pick(None, quality["model"], quality["platform"]) is None
    assert ranks.for_pick({}, quality["model"], quality["platform"]) is None


def test_reading_the_ranks_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import ranks

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("no ranks today")

    monkeypatch.setattr(scoring, "ranked_columns", boom)
    assert ranks.read(scoring.Task("coding", "high"), _scoring_text(_CONTEXT)) is None
    assert ranks.columns(scoring.Task("coding", "high"), _scoring_text(_CONTEXT)) is None
    assert ranks.for_pick({"model": "x"}, "x", "y") is None


# --- The ladder endpoint ------------------------------------------------------


def _pick(option: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": option["model"],
        "platform": option["platform"],
        "settings": {"effort": option["level_cell"], "thinking": "On"},
        "rationale": "TASK: Coding. PICK: It fits. EFFORT: It suits.",
        "conversation": "New",
        "session_cost_estimate": None,
        "comparison_table": None,
    }


def _fake_ladder(columns: dict[str, dict[str, Any]], guard: dict[str, Any]) -> Any:
    def fake(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"picks": {t: _pick(columns[t]) for t in _TIERS}, "guard": guard}

    return fake


def _post_ladder(client: TestClient, context: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"task_description": "refactor a pipeline"}
    if context is not None:
        body["context"] = context
    response = client.post("/v1/recommend/ladder", json=body)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_ladder_pick_carries_its_three_ranks_and_the_task_it_was_read_as(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    task = scoring.Task("coding", "high")
    columns = ranks.columns(task, _scoring_text(_CONTEXT))
    assert columns is not None
    guard = {"mode": "frontier", "classification": "coding/high", "healthy": True}
    monkeypatch.setattr(recommend, "recommend_structured_ladder", _fake_ladder(columns, guard))

    body = _post_ladder(client, _CONTEXT)
    assert body["task"] == {"category": "coding", "complexity": "high", "novel": False}
    for tier in _TIERS:
        got = body["picks"][tier]["ranks"]
        column = columns[tier]
        assert got is not None, tier
        for rank, option in zip(("pick", "runner_up", "backup"), _options(column), strict=True):
            if option is None:
                assert got[rank] is None
                continue
            assert got[rank] == {
                "model": option["model"],
                "model_id": option["model_id"],
                "platform": option["platform"],
                "platform_id": option["platform_id"],
                "effort": option["effort"],
                "level": option["level_cell"],
                "aa_index": option["aa_index"],
                "aa_estimated": option["aa_estimated"],
                "price_usd_per_1m": option["price_usd_per_1m"],
                "price_measured": option["price_measured"],
                "stepped_down": option["stepped_down"],
            }
        # The Pick's rank is the pick itself.
        assert got["pick"]["model"] == body["picks"][tier]["model"]
        assert got["runner_up"] is not None
    # The settings the ladder weighed ride along for the page's chart, every
    # pick among them.
    read = ranks.read(task, _scoring_text(_CONTEXT))
    assert read is not None
    assert body["points"] == read.points
    keys = {(p["model_id"], p["effort"]) for p in body["points"]}
    lad = scoring.ladder(task, _scoring_text(_CONTEXT))
    assert lad is not None
    for rung in lad.rungs.values():
        assert (rung.candidate.model_id, rung.candidate.evidence_level) in keys


def test_a_novel_task_is_reported_as_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    columns = ranks.columns(scoring.Task("planning", "high", True), _scoring_text(_CONTEXT))
    assert columns is not None
    guard = {"mode": "frontier", "classification": "planning/high/novel"}
    monkeypatch.setattr(recommend, "recommend_structured_ladder", _fake_ladder(columns, guard))
    body = _post_ladder(client, _CONTEXT)
    assert body["task"] == {"category": "planning", "complexity": "high", "novel": True}
    assert body["picks"]["quality"]["ranks"]["pick"]["model"] == columns["quality"]["model"]


def test_an_undeclared_profile_is_ranked_over_the_bundled_template(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request that declares no funding gets its table from the bundled
    template (the package's fallback), so its ranks are read there too."""
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    template = recommend._BUNDLED_USER_CONTEXT.read_text(encoding="utf-8")
    columns = ranks.columns(scoring.Task("coding", "medium"), template)
    assert columns is not None
    guard = {"mode": "frontier", "classification": "coding/medium"}
    monkeypatch.setattr(recommend, "recommend_structured_ladder", _fake_ladder(columns, guard))
    body = _post_ladder(client)
    assert body["task"] == {"category": "coding", "complexity": "medium", "novel": False}
    for tier in _TIERS:
        assert body["picks"][tier]["ranks"]["pick"]["model"] == columns[tier]["model"]


def test_a_refit_row_leaves_the_too_small_models_out_of_the_ranks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    task = scoring.Task("long-context", "high")
    tokens = 300_000
    small = scoring.too_small_for(tokens)
    assert small
    text = _scoring_text(_CONTEXT)
    columns = ranks.columns(task, text, small)
    assert columns is not None
    guard = {
        "mode": "frontier",
        "classification": "long-context/high",
        "context": {"input_tokens": tokens, "excluded": [small[0]], "fits": True},
    }
    seen: list[list[str]] = []
    real = ranks.read

    def spy(task_: Any, text_: str, unavailable: list[str] | None = None) -> Any:
        seen.append(list(unavailable or []))
        return real(task_, text_, unavailable)

    monkeypatch.setattr(recommend, "recommend_structured_ladder", _fake_ladder(columns, guard))
    monkeypatch.setattr(ranks, "read", spy)
    body = _post_ladder(client, {**_CONTEXT, "unavailable_models": ["benched-model"]})
    assert seen == [["benched-model", *small]]
    assert not {p["model_id"] for p in body["points"]} & set(small)
    reached = {
        o["model_id"]
        for tier in _TIERS
        for o in body["picks"][tier]["ranks"].values()
        if o is not None
    }
    assert not reached & set(small)


@pytest.mark.parametrize(
    "guard",
    [
        {},
        {"healthy": True},
        {"mode": "frontier", "classification": None, "found": "unclassified"},
        {"mode": "frontier", "classification": "poetry/high"},
    ],
    ids=["no-guard", "free-choice", "unclassified", "unknown-row"],
)
def test_a_response_the_table_did_not_place_has_no_ranks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, guard: dict[str, Any]
) -> None:
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    columns = ranks.columns(scoring.Task("coding", "high"), _scoring_text(_CONTEXT))
    assert columns is not None
    monkeypatch.setattr(recommend, "recommend_structured_ladder", _fake_ladder(columns, guard))
    body = _post_ladder(client, _CONTEXT)
    assert body["task"] is None
    assert body["points"] is None
    for tier in _TIERS:
        assert body["picks"][tier]["ranks"] is None


def test_a_pick_off_the_row_has_no_ranks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's ranks describe the row's pick. A response whose Cost pick is
    another model keeps its ranks on the two picks that are the row's."""
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    # No declared funding, so no access guard substitutes the unknown model.
    template = recommend._BUNDLED_USER_CONTEXT.read_text(encoding="utf-8")
    columns = ranks.columns(scoring.Task("coding", "high"), template)
    assert columns is not None
    guard = {"mode": "frontier", "classification": "coding/high"}

    def fake(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        picks = {t: _pick(columns[t]) for t in _TIERS}
        picks["cost"] = {**picks["cost"], "model": "Test Frontier Model"}
        return {"picks": picks, "guard": guard}

    monkeypatch.setattr(recommend, "recommend_structured_ladder", fake)
    body = _post_ladder(client)
    assert body["picks"]["cost"]["model"] == "Test Frontier Model"
    assert body["picks"]["cost"]["ranks"] is None
    assert body["picks"]["quality"]["ranks"]["pick"]["model"] == columns["quality"]["model"]


def test_a_failure_reading_the_ranks_leaves_the_picks_as_they_were(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ranks

    recommend = importlib.import_module("app.recommend")
    columns = ranks.columns(scoring.Task("coding", "high"), _scoring_text(_CONTEXT))
    assert columns is not None
    guard = {"mode": "frontier", "classification": "coding/high"}
    monkeypatch.setattr(recommend, "recommend_structured_ladder", _fake_ladder(columns, guard))

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("no ranks today")

    monkeypatch.setattr(ranks, "read", boom)
    body = _post_ladder(client, _CONTEXT)
    # The task it was read as is known without the ranks.
    assert body["task"] == {"category": "coding", "complexity": "high", "novel": False}
    assert body["points"] is None
    for tier in _TIERS:
        assert body["picks"][tier]["model"] == columns[tier]["model"]
        assert body["picks"][tier]["ranks"] is None


def test_a_single_pick_has_no_ranks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    recommend = importlib.import_module("app.recommend")

    def fake(prompt: str, config: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "model": "Test Frontier Model",
            "platform": "Claude Code",
            "settings": {"effort": "High", "thinking": "On"},
            "rationale": "Best for coding tasks.",
            "conversation": "New",
        }

    monkeypatch.setattr(recommend, "recommend_structured", fake)
    response = client.post("/v1/recommend", json={"task_description": "pick a model"})
    assert response.status_code == 200
    assert response.json()["ranks"] is None


# --- Quick pick ---------------------------------------------------------------


def test_quick_picks_rungs_carry_the_same_ranks(client: TestClient) -> None:
    from app import ranks

    body = {"category": "coding", "complexity": "high", **_CONTEXT}
    response = client.post("/v1/score", json=body)
    assert response.status_code == 200, response.text
    read = ranks.read(scoring.Task("coding", "high"), _scoring_text(_CONTEXT))
    assert read is not None
    columns = read.columns
    assert response.json()["points"] == read.points
    for rung in response.json()["rungs"]:
        column = columns[rung["priority"]]
        got = rung["ranks"]
        assert got is not None
        assert (got["pick"]["model_id"], got["pick"]["platform_id"]) == (
            rung["model_id"],
            rung["platform_id"],
        )
        assert got["pick"]["level"] == column["level_cell"]
        assert got["pick"]["aa_index"] == column["aa_index"]
        assert got["pick"]["price_usd_per_1m"] == column["price_usd_per_1m"]
        assert got["runner_up"]["model_id"] == column["runner_up"]["model_id"]
        assert got["runner_up"]["model_id"] != rung["model_id"]


def test_quick_pick_answers_without_its_ranks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("no ranks today")

    monkeypatch.setattr(scoring, "ranked_columns", boom)
    response = client.post("/v1/score", json={"category": "coding", "complexity": "high"})
    assert response.status_code == 200
    rungs = response.json()["rungs"]
    assert [r["priority"] for r in rungs] == ["quality", "balanced", "cost"]
    assert all(r["ranks"] is None for r in rungs)
    assert response.json()["points"] is None
