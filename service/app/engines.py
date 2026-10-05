# service/app/engines.py
"""The recommender engines: which models may generate a recommendation, and
how each one is called.

engines.json beside this module is the single source of truth. The service
runs an engine from it, and the web build copies it next to the catalog to
build the /recommend engine menu (web/scripts/sync-catalog.mjs), so the two
deployments can never disagree about what an engine id means. Before the
registry, an engine lived in four places (this module's hint table, the web's
override file, its routing constant and its display map) and they drifted: the
web named the current engine "roadmodel" because its display map had no entry
for it.

The file is validated on import, so a malformed registry fails the deploy's
first request loudly instead of misrouting traffic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_REGISTRY_PATH: Final = Path(__file__).with_name("engines.json")

# Who may choose an engine from the /recommend menu when it runs on the
# operator's keys: the invite list (founder included) or the founder alone.
# Enforced at the web edge, which refuses every other visitor before any engine
# runs (web/lib/funding-lane.ts); the service runs whatever hint the
# authenticated edge forwards.
MENU_ACCESS: Final = frozenset({"invited", "founder"})

# The providers a visitor may pay with their own key (service/app/visitor.py):
# the three with native adapters. Each has a default engine in the registry's
# `visitor_defaults`, used when the visitor names no engine of that provider.
VISITOR_PROVIDERS: Final = frozenset({"openai", "google", "anthropic"})


@dataclass(frozen=True)
class EngineSpec:
    hint: str
    catalog_id: str
    provider: str
    model: str
    thinking_budget: int | None
    max_output_tokens: int | None
    ladder_max_output_tokens: int | None
    temperature: float | None
    menu: str | None

    def params(self, *, ladder: bool) -> tuple[int | None, int | None, float | None]:
        """(thinking_budget, max_output_tokens, temperature) for one call."""
        cap = self.ladder_max_output_tokens if ladder else self.max_output_tokens
        return self.thinking_budget, cap, self.temperature


def _optional_int(entry: dict[str, Any], key: str) -> int | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"engine {entry.get('hint')!r}: {key} must be a non-negative int or null")
    return value


def _spec(entry: dict[str, Any]) -> EngineSpec:
    hint = entry.get("hint")
    if not isinstance(hint, str) or not hint:
        raise ValueError(f"engine entry without a hint: {entry!r}")
    for key in ("catalog_id", "provider", "model"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise ValueError(f"engine {hint!r}: {key} must be a non-empty string")
    if not hint.startswith(f"{entry['provider']}-"):
        raise ValueError(f"engine {hint!r}: the hint must start with its provider")
    temperature = entry.get("temperature")
    if temperature is not None and not isinstance(temperature, int | float):
        raise ValueError(f"engine {hint!r}: temperature must be a number or null")
    menu = entry.get("menu")
    if menu is not None and menu not in MENU_ACCESS:
        raise ValueError(f"engine {hint!r}: menu must be one of {sorted(MENU_ACCESS)} or null")
    return EngineSpec(
        hint=hint,
        catalog_id=entry["catalog_id"],
        provider=entry["provider"],
        model=entry["model"],
        thinking_budget=_optional_int(entry, "thinking_budget"),
        max_output_tokens=_optional_int(entry, "max_output_tokens"),
        ladder_max_output_tokens=_optional_int(entry, "ladder_max_output_tokens"),
        temperature=float(temperature) if temperature is not None else None,
        menu=menu,
    )


@dataclass(frozen=True)
class Registry:
    engines: dict[str, EngineSpec]
    default: str
    fallback_chain: tuple[str, ...]
    # Provider -> the engine a visitor's key runs when they name none of it.
    visitor_defaults: dict[str, str]


def _visitor_defaults(raw: Any, engines: dict[str, EngineSpec]) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != VISITOR_PROVIDERS:
        raise ValueError(
            f"visitor_defaults must name one engine for each of {sorted(VISITOR_PROVIDERS)}"
        )
    for provider, hint in raw.items():
        spec = engines.get(hint) if isinstance(hint, str) else None
        if spec is None or spec.provider != provider:
            raise ValueError(
                f"visitor_defaults[{provider!r}] must be a {provider} engine in the registry"
            )
    return dict(raw)


def load_registry(path: Path = _REGISTRY_PATH) -> Registry:
    raw = json.loads(path.read_text(encoding="utf-8"))
    engines: dict[str, EngineSpec] = {}
    for entry in raw.get("engines", []):
        spec = _spec(entry)
        if spec.hint in engines:
            raise ValueError(f"duplicate engine hint {spec.hint!r}")
        engines[spec.hint] = spec
    default = raw.get("default")
    if default not in engines:
        raise ValueError(f"default engine {default!r} is not in the registry")
    chain = tuple(raw.get("fallback_chain", []))
    unknown = [hint for hint in chain if hint not in engines]
    if not chain or unknown:
        raise ValueError(f"fallback_chain must name registry engines (unknown: {unknown})")
    return Registry(
        engines=engines,
        default=default,
        fallback_chain=chain,
        visitor_defaults=_visitor_defaults(raw.get("visitor_defaults"), engines),
    )


REGISTRY: Final = load_registry()


# The engine eval's per-engine record (scripts/eval_recommend_engines.py
# --summary-json writes docs/engine-eval.json and this copy beside the
# registry, because the service deploys from service/ and cannot read docs/;
# tests/test_engine_eval_mirror.py holds the two equal). An engine passes once
# it answered every structured field on at least PASS_SHARE of the probes: the
# same rule the web menu applies (web/lib/recommend-engines.ts isEvaluated).
_EVAL_PATH: Final = Path(__file__).with_name("engine-eval.json")
PASS_SHARE: Final = 0.9


def load_evaluated(path: Path = _EVAL_PATH) -> frozenset[str]:
    """The hints whose eval record passes. A missing or unreadable file passes
    none, so a visitor then runs their provider's default engine."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    engines = raw.get("engines") if isinstance(raw, dict) else None
    if not isinstance(engines, dict):
        return frozenset()
    passed: set[str] = set()
    for hint, record in engines.items():
        if not isinstance(record, dict):
            continue
        probes, ok = record.get("probes"), record.get("passed")
        if isinstance(probes, int) and isinstance(ok, int) and probes > 0:
            if ok / probes >= PASS_SHARE:
                passed.add(hint)
    return frozenset(passed)


EVALUATED: Final = load_evaluated()
