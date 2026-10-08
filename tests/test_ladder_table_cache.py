"""The ladder table is built once per user-context in a process.

The hosted service rebuilt the 28-row table on every request, and inside it
the scorer re-parsed the catalog JSON about a thousand times (cost.
model_provider loaded it per candidate): about a second a request on the
service's CPUs for a well-funded user, which put signed-in latency (bar B9)
over its line (Phase 4.5 soak, 2026-10-08).
"""

from __future__ import annotations

from importlib import resources

import pytest

from roadmodel import cost, scoring
from roadmodel import recommend as recommend_module

TEMPLATE = (resources.files("roadmodel.data") / "user-context.example.md").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def _empty_cache() -> None:
    recommend_module._TABLE_CACHE.clear()


def test_a_repeated_context_reuses_its_table(monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[str] = []
    real = scoring.ladder_table

    def counting(text: str, **kw: object) -> dict[str, scoring.Ladder]:
        builds.append(text)
        return real(text, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(scoring, "ladder_table", counting)
    first = recommend_module._ladder_table_for(TEMPLATE, None)
    assert first and recommend_module._ladder_table_for(TEMPLATE, []) is first
    assert len(builds) == 1
    # Another unavailable list or catalog override is another table.
    recommend_module._ladder_table_for(TEMPLATE, ["gpt-6-luna"])
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(cost.BUNDLED_CATALOG_PATH))
    recommend_module._ladder_table_for(TEMPLATE, None)
    assert len(builds) == 3


def test_a_failed_build_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> dict[str, scoring.Ladder]:
        raise RuntimeError("scoring failed")

    monkeypatch.setattr(scoring, "ladder_table", boom)
    assert recommend_module._ladder_table_for(TEMPLATE, None) == {}
    assert recommend_module._TABLE_CACHE == {}


def test_the_cache_stays_bounded() -> None:
    for i in range(recommend_module._TABLE_CACHE_MAX):
        recommend_module._TABLE_CACHE[(str(i), (), "")] = {}
    recommend_module._ladder_table_for(TEMPLATE, None)
    assert len(recommend_module._TABLE_CACHE) == recommend_module._TABLE_CACHE_MAX
    assert ("0", (), "") not in recommend_module._TABLE_CACHE  # the oldest went first


def test_model_provider_uses_the_catalog_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = cost._load_catalog()

    def no_reload() -> dict[str, object]:
        raise AssertionError("reloaded the catalog")

    monkeypatch.setattr(cost, "_load_catalog", no_reload)
    assert cost.model_provider("claude-opus-5-5", catalog) == "anthropic"
