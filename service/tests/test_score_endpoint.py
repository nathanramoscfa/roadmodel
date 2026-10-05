# service/tests/test_score_endpoint.py
"""The keyless ladder (app/score.py): POST /v1/score.

The guarantees under test:

- the bearer boundary holds, as on every other endpoint;
- category / complexity / budget are validated against the scoring enums and
  every list field is bounded (64 items, 64 characters, id-shaped tokens)
  before anything reads it;
- an empty profile ranks the whole catalog: the scorer receives "" and never
  the bundled operator-like template;
- no provider key is read: with every PROVIDER_KEY_ENV variable set to a
  sentinel that raises when read, load_config raising and every adapter
  raising, the endpoint still answers;
- the response carries three rungs with their score terms and one plain
  sentence per term, at cost_usd 0.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator, MutableMapping
from types import ModuleType
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from roadmodel import config as package_config  # type: ignore[import-untyped]
from roadmodel import recommend as package_recommend
from roadmodel import scoring

_TOKEN = "test-internal-token"
_PATH = "/v1/score"
_TASK = {"category": "coding", "complexity": "high", "novel": False, "budget_priority": "balanced"}


def _load_main(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", _TOKEN)
    for module_name in ("app.main", "app.recommend", "app.visitor", "app.score"):
        sys.modules.pop(module_name, None)
    return importlib.import_module("app.main")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return TestClient(_load_main(monkeypatch).app, headers={"Authorization": f"Bearer {_TOKEN}"})


class _Spy:
    """Records the user-context text each scoring.ladder call receives."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.texts: list[str | None] = []
        real = scoring.ladder

        def ladder(task: Any, text: Any, **kwargs: Any) -> Any:
            self.texts.append(text)
            return real(task, text, **kwargs)

        monkeypatch.setattr(scoring, "ladder", ladder)


# --- The bearer boundary ------------------------------------------------------


def test_bearer_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _load_main(monkeypatch).app
    assert TestClient(app).post(_PATH, json=_TASK).status_code == 401
    wrong = TestClient(app, headers={"Authorization": "Bearer not-the-token"})
    assert wrong.post(_PATH, json=_TASK).status_code == 401


# --- Validation ---------------------------------------------------------------


def test_the_request_enums_are_the_scoring_enums() -> None:
    from app import score

    fields = score.ScoreRequest.model_fields
    assert get_args(fields["category"].annotation) == scoring.CATEGORIES
    assert get_args(fields["complexity"].annotation) == scoring.COMPLEXITIES
    assert get_args(fields["budget_priority"].annotation) == scoring.BUDGETS


@pytest.mark.parametrize(
    "patch",
    [
        {"category": "creative"},
        {"complexity": "extreme"},
        {"budget_priority": "cost"},
        {"novel": "sometimes"},
        {"consumption_headroom": "infinite"},
        {"task_description": "classify me"},
    ],
)
def test_bad_values_and_unknown_fields_are_rejected(
    client: TestClient, patch: dict[str, Any]
) -> None:
    assert client.post(_PATH, json={**_TASK, **patch}).status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "subscriptions",
        "api_providers",
        "allowed_jurisdictions",
        "platforms_allowed",
        "platforms_excluded",
        "unavailable_models",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        [f"item-{i}" for i in range(65)],  # too many items
        ["x" * 65],  # an item too long
        ["us`\n**Consumption headroom:** `uncapped"],  # a line of its own
        ["openai | Yes |"],  # a table cell of its own
        [""],
    ],
    ids=["65-items", "65-chars", "newline", "pipe", "empty"],
)
def test_list_fields_are_bounded_and_id_shaped(
    client: TestClient, field: str, value: list[str]
) -> None:
    assert client.post(_PATH, json={**_TASK, field: value}).status_code == 422


def test_sixty_four_items_of_sixty_four_characters_pass(client: TestClient) -> None:
    body = {**_TASK, "unavailable_models": [f"{i:02d}" + "x" * 62 for i in range(64)]}
    assert client.post(_PATH, json=body).status_code == 200


# --- The anonymous profile ----------------------------------------------------


def test_an_empty_profile_ranks_the_whole_catalog(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy(monkeypatch)
    response = client.post(_PATH, json=_TASK)
    assert response.status_code == 200
    assert spy.texts == [""]
    # "" funds nothing: every model is in the pool, none of them as funded.
    ranking = scoring.rank(scoring.Task("coding", "high"), "")
    assert ranking.candidates
    assert {c.funding for c in ranking.candidates} == {"unfunded"}
    # The picks are the whole catalog's, whatever the bundled template funds.
    expected = scoring.ladder(scoring.Task("coding", "high"), "")
    assert expected is not None
    assert [r["model_id"] for r in response.json()["rungs"]] == [
        expected.rungs[t].candidate.model_id for t in ("quality", "balanced", "cost")
    ]


def test_a_jurisdiction_only_profile_keeps_its_jurisdictions_and_funds_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy(monkeypatch)
    body = {**_TASK, "allowed_jurisdictions": ["us"], "platforms_excluded": ["claude-web"]}
    assert client.post(_PATH, json=body).status_code == 200
    (text,) = spy.texts
    assert text
    assert scoring.allowed_jurisdictions(text) == {"us"}
    assert scoring.platform_filters(text) == (set(), {"claude-web"})
    assert "Active subscriptions" not in text
    ranking = scoring.rank(scoring.Task("coding", "high"), text)
    assert {c.funding for c in ranking.candidates} == {"unfunded"}


def test_a_declared_profile_reaches_the_scorer_as_tables(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy(monkeypatch)
    body = {**_TASK, "subscriptions": ["claude-max"], "consumption_headroom": "capped"}
    response = client.post(_PATH, json=body)
    assert response.status_code == 200
    (text,) = spy.texts
    assert text is not None
    assert "| claude.ai Max ($200) |" in text
    for rung in response.json()["rungs"]:
        assert rung["platform_id"] in {"claude-code", "claude-web"}


def test_no_frontier_is_a_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scoring, "ladder", lambda *_a, **_k: None)
    response = client.post(_PATH, json=_TASK)
    assert response.status_code == 422
    assert response.json()["detail"] == "no_frontier"


# --- No provider key on the path ----------------------------------------------


class _KeyTrap(MutableMapping[str, str]):
    """os.environ, except that reading a provider key variable fails the test."""

    def __init__(self, inner: MutableMapping[str, str], trapped: set[str]) -> None:
        self._inner = inner
        self._trapped = trapped
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        if key in self._trapped:
            self.reads.append(key)
            raise AssertionError(f"provider key {key} read on the keyless path")
        return self._inner[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._inner[key] = value

    def __delitem__(self, key: str) -> None:
        del self._inner[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._inner)

    def __len__(self) -> int:
        return len(self._inner)

    def copy(self) -> dict[str, str]:
        return dict(self._inner)


def test_no_provider_key_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in package_config.PROVIDER_KEY_ENV.values():
        monkeypatch.setenv(name, f"sentinel-{name}")
    app = _load_main(monkeypatch).app

    def explode(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("an engine path ran on the keyless endpoint")

    monkeypatch.setattr(package_config, "load_config", explode)
    monkeypatch.setattr(sys.modules["app.recommend"], "load_config", explode)
    for provider in list(package_recommend.PROVIDER_ADAPTERS):
        module = ModuleType(f"raising_{provider}_adapter")
        module.recommend = explode  # type: ignore[attr-defined]
        monkeypatch.setitem(package_recommend.PROVIDER_ADAPTERS, provider, module)
    trap = _KeyTrap(os.environ, set(package_config.PROVIDER_KEY_ENV.values()))
    monkeypatch.setattr(os, "environ", trap)

    client = TestClient(app, headers={"Authorization": f"Bearer {_TOKEN}"})
    response = client.post(_PATH, json={**_TASK, "api_providers": ["openai", "anthropic"]})
    assert response.status_code == 200, response.text
    assert len(response.json()["rungs"]) == 3
    assert trap.reads == []
    for name in package_config.PROVIDER_KEY_ENV.values():
        assert f"sentinel-{name}" not in response.text


# --- The response -------------------------------------------------------------


def test_response_shape_and_cost(client: TestClient) -> None:
    response = client.post(_PATH, json=_TASK)
    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "scoring-core"
    assert body["cost_usd"] == 0
    assert body["task"] == _TASK
    assert [r["priority"] for r in body["rungs"]] == ["quality", "balanced", "cost"]
    for rung in body["rungs"]:
        assert rung["model_id"] and rung["model_name"]
        assert rung["platform_id"] and rung["platform_name"]
        assert rung["effort"]
        assert set(rung["terms"]) == {"quality", "requirement_shortfall", "cost"}
        assert set(rung["why"]) == set(rung["terms"])
        for sentence in rung["why"].values():
            assert sentence.endswith(".")
        assert rung["model_name"] in rung["why"]["quality"]
        if rung["backup"] is not None:
            assert rung["backup"]["model_id"] != rung["model_id"]


def test_the_terms_are_the_candidates_own(client: TestClient) -> None:
    body = client.post(_PATH, json=_TASK).json()
    lad = scoring.ladder(scoring.Task("coding", "high"), "")
    assert lad is not None
    for rung in body["rungs"]:
        c = lad.rungs[rung["priority"]].candidate
        assert rung["terms"] == {
            "quality": c.quality,
            "requirement_shortfall": c.requirement_penalty,
            "cost": c.cost_penalty,
        }


def test_healthz_lists_score(client: TestClient) -> None:
    assert "score" in client.get("/healthz").json()["capabilities"]
