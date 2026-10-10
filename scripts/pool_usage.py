"""Shared, stdlib-only usage snapshots and pure pool decisions.

Collectors persist only allowlisted meter fields, never raw responses/transcripts.
Timestamps are UTC epoch seconds; a missing decision means retain the current state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

CACHE = Path.home() / ".cache" / "roadmodel" / "pools"
WEEK = 7 * 24 * 60


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def window(name: str, used: Any, reset: Any, minutes: Any) -> dict[str, Any] | None:
    used, reset, minutes = number(used), number(reset), number(minutes)
    if used is None or reset is None or minutes is None:
        return None
    if not 0 <= used <= 100 or reset <= 0 or minutes <= 0:
        return None
    return dict(name=name, used_percent=used, resets_at=reset, window_minutes=minutes)


def save(snapshot: dict[str, Any], cache: Path = CACHE) -> None:
    """Replace a private snapshot atomically; readers never see a partial JSON file."""
    source = snapshot["source"]
    if source not in {"claude", "codex", "openrouter", "antigravity"}:
        raise ValueError("unknown pool source")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{source}-", dir=cache)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(snapshot, out, allow_nan=False)
            out.write("\n")
        os.replace(tmp, cache / f"{source}.json")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(cache: Path = CACHE) -> dict[str, dict[str, Any]]:
    result = {}
    try:
        expected = json.loads((cache / "accounts.json").read_text()).get("antigravity")
    except (OSError, ValueError, AttributeError):
        expected = None
    for source in ("claude", "codex", "openrouter", "antigravity"):
        try:
            data = json.loads((cache / f"{source}.json").read_text())
            if isinstance(data, dict) and data.get("source") == source:
                if source == "antigravity" and expected:
                    digest = hashlib.sha256(expected.lower().encode()).hexdigest()
                    if data.get("extra", {}).get("account_digest") != digest:
                        continue
                result[source] = data
        except (OSError, ValueError):
            pass
    return result


def decide(snapshot: dict[str, Any], meter: dict[str, Any] | None, now: float) -> str | None:
    """Pure decision, or None for missing, malformed, future, stale or reset data.

    Weekly pace needs 12 hours of history. Short windows use their elapsed
    fraction without that weekly guard. Stale data NEVER changes a state;
    the table roller separately handles a known passed reset.
    """
    observed = number(snapshot.get("observed_at"))
    if observed is None or observed > now or now - observed > 6 * 3600:
        return None
    extra = snapshot.get("extra", {})
    if not isinstance(extra, dict):
        return None
    if snapshot.get("source") == "openrouter":
        remaining, limit = number(extra.get("limit_remaining")), number(extra.get("limit"))
        if remaining is None or limit is None or limit <= 0:
            return None
        return "exhausted" if remaining < 1 else "tight" if remaining < 0.2 * limit else "headroom"
    if not isinstance(meter, dict):
        return None
    # The supported agy panel says '100% remaining / Quota available'
    # before a group starts its first window; there is no reset to invent.
    if (
        snapshot.get("source") == "antigravity"
        and meter.get("used_percent") == 0
        and meter.get("resets_at") is None
        and number(meter.get("window_minutes"))
    ):
        return (
            "headroom"
            if now - observed <= (3600 if meter["window_minutes"] <= 300 else 6 * 3600)
            else None
        )
    validated = window(
        "", meter.get("used_percent"), meter.get("resets_at"), meter.get("window_minutes")
    )
    if validated is None:
        return None
    minutes = validated["window_minutes"]
    reset = validated["resets_at"]
    used = validated["used_percent"]
    duration = minutes * 60
    elapsed = now - (reset - duration)
    # Snapshots cannot describe a window not yet started or already reset.
    if elapsed < 0 or now >= reset or not reset - duration <= observed < reset:
        return None
    if now - observed > (3600 if minutes <= 300 else 6 * 3600):
        return None
    if used >= 97 or meter.get("quota_error") is True or extra.get("rate_limit_reached") is True:
        return "exhausted"
    if used >= 85 and reset - now > 24 * 3600:
        return "tight"
    # Use elapsed at OBSERVATION, not read time: old usage must not improve pace.
    elapsed_at_observation = observed - (reset - duration)
    if elapsed_at_observation > 0 and (minutes < WEEK or elapsed_at_observation >= 12 * 3600):
        if used / (elapsed_at_observation / duration) >= 100:
            return "tight"
    return "headroom"
