"""Selectable agent configurations and evidence specific to each one."""

from __future__ import annotations

import json
import math
from typing import Any, Final, TypeGuard

from roadmodel import data_files

FILENAME: Final = "agent-configurations.json"


@data_files.cached_on(FILENAME)
def configurations() -> tuple[dict[str, Any], ...]:
    try:
        doc = json.loads(data_files.data_file(FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    entries = doc.get("configurations") if isinstance(doc, dict) else None
    return (
        tuple(entry for entry in entries if isinstance(entry, dict))
        if isinstance(entries, list)
        else ()
    )


def _number(value: object, low: float, high: float = math.inf) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and low <= value <= high
    )


def evidence_for(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Only use figures tied to this configuration, with a cited source."""
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("configuration_id") != entry["id"]:
        return None
    source = evidence.get("source")
    if not isinstance(source, str) or not source.startswith("https://"):
        return None
    return evidence


def index_for(evidence: dict[str, Any]) -> tuple[float, float] | None:
    """An Intelligence Index value and the uncertainty of a Roadmodel estimate."""
    index = evidence.get("aa_index")
    if not isinstance(index, dict) or not _number(index.get("value"), 0, 100):
        return None
    if index.get("kind") == "measured":
        return float(index["value"]), 0.0
    band = index.get("band")
    if index.get("kind") == "estimated" and _number(band, 0.01, 100):
        return float(index["value"]), float(band)
    return None


def price_for(evidence: dict[str, Any]) -> tuple[float, float] | None:
    """Usage-normalized input and output prices for the full configuration."""
    price = evidence.get("price")
    if not isinstance(price, dict):
        return None
    in_price, out_price = price.get("input_per_1m"), price.get("output_per_1m")
    if not (_number(in_price, 0) and _number(out_price, 0.000001)):
        return None
    return float(in_price), float(out_price)


def tier_allowed(entry: dict[str, Any], tier: str) -> bool:
    # The catalog includes parenthetical billing variants of Google AI Ultra.
    return not entry["subscription_tiers"] or tier.rsplit(" (", 1)[0] in entry["subscription_tiers"]
