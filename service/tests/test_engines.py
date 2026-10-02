# service/tests/test_engines.py
"""The engine registry (service/app/engines.json): it loads, every entry is
well-formed, and the engines offered on the /recommend menu are real, current
catalog models — so a renamed or superseded model fails here, in CI, instead
of sitting on the menu."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.engines import MENU_ACCESS, REGISTRY, load_registry

_REPO = Path(__file__).resolve().parents[2]
_CATALOG = {m["id"]: m for m in json.loads((_REPO / "docs" / "catalog.json").read_text())["models"]}


def test_registry_loads_with_a_valid_default_and_chain() -> None:
    assert REGISTRY.default in REGISTRY.engines
    assert REGISTRY.fallback_chain[0] == REGISTRY.default
    assert set(REGISTRY.fallback_chain) <= set(REGISTRY.engines)
    # The chain spans providers, so one provider's outage cannot take it down.
    providers = {REGISTRY.engines[h].provider for h in REGISTRY.fallback_chain}
    assert len(providers) == len(REGISTRY.fallback_chain)


def test_every_engine_bills_as_a_catalog_model() -> None:
    missing = [s.hint for s in REGISTRY.engines.values() if s.catalog_id not in _CATALOG]
    assert missing == []


def test_menu_engines_are_current_catalog_models() -> None:
    """A superseded model has a successor that is no dearer and at least as
    good everywhere; offering it as an engine would be offering the worse one."""
    stale = [
        s.hint
        for s in REGISTRY.engines.values()
        if s.menu is not None and _CATALOG[s.catalog_id].get("superseded_by")
    ]
    assert stale == []


def test_the_default_engine_is_public() -> None:
    """Anonymous visitors get the default engine, so it must be on the menu for
    everyone."""
    assert REGISTRY.engines[REGISTRY.default].menu == "public"


def test_menu_values_are_known() -> None:
    assert {s.menu for s in REGISTRY.engines.values()} <= {*MENU_ACCESS, None}


def _write(tmp_path: Path, registry: dict[str, Any]) -> Path:
    path = tmp_path / "engines.json"
    path.write_text(json.dumps(registry))
    return path


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "hint": "openai-x",
        "catalog_id": "x",
        "provider": "openai",
        "model": "x",
        "thinking_budget": 0,
        "max_output_tokens": 2048,
        "ladder_max_output_tokens": 6144,
        "temperature": None,
        "menu": "public",
    }
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"hint": ""}, "without a hint"),
        ({"model": ""}, "model"),
        ({"hint": "google-x"}, "start with its provider"),
        ({"menu": "everyone"}, "menu must be one of"),
        ({"max_output_tokens": -1}, "non-negative"),
        ({"temperature": "0"}, "temperature"),
    ],
)
def test_malformed_entries_fail_to_load(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    registry = {
        "default": "openai-x",
        "fallback_chain": ["openai-x"],
        "engines": [_entry(**overrides)],
    }
    with pytest.raises(ValueError, match=message):
        load_registry(_write(tmp_path, registry))


def test_unknown_default_or_chain_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="default engine"):
        load_registry(
            _write(tmp_path, {"default": "nope", "fallback_chain": [], "engines": [_entry()]})
        )
    with pytest.raises(ValueError, match="fallback_chain"):
        load_registry(
            _write(
                tmp_path,
                {"default": "openai-x", "fallback_chain": ["nope"], "engines": [_entry()]},
            )
        )


def test_duplicate_hints_fail_to_load(tmp_path: Path) -> None:
    registry = {
        "default": "openai-x",
        "fallback_chain": ["openai-x"],
        "engines": [_entry(), _entry()],
    }
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(_write(tmp_path, registry))
