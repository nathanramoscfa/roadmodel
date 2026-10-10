"""Allowlisted per-user pool observations; shared with the stdlib Mac uploader."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, TypeGuard

POOLS = {
    "claude:weekly": ("claude", "claude-code", 10080),
    "claude:5h": ("claude", "claude-code", 300),
    "codex:weekly": ("codex", "codex-cli", 10080),
    "codex:5h": ("codex", "codex-cli", 300),
    "antigravity:all": ("antigravity", "antigravity", None),
    "openrouter:credits": ("openrouter", "openrouter", 0),
}
ORDER = {"headroom": 0, "tight": 1, "exhausted": 2}


def numeric(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize(raw: Any, now: float | None = None) -> list[dict[str, Any]]:
    """Drop malformed entries and unknown fields, retaining stale known states."""
    now = time.time() if now is None else now
    if not isinstance(raw, list) or len(raw) > len(POOLS):
        return []
    result: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("pool"), str):
            continue
        pool = row["pool"]
        if pool not in POOLS or not isinstance(row.get("state"), str) or row["state"] not in ORDER:
            continue
        source, platform, expected = POOLS[pool]
        observed, reset = row.get("observed_at"), row.get("resets_at")
        used, minutes = row.get("used_percent"), row.get("window_minutes")
        if not numeric(observed) or not numeric(used) or not numeric(minutes):
            continue
        if not 0 < observed <= now or not 0 <= used <= 100:
            continue
        if expected is not None and minutes != expected:
            continue
        if expected is None and minutes not in (300, 10080):
            continue
        if pool == "openrouter:credits":
            if reset is not None:
                continue
        elif reset is None:
            if source != "antigravity" or used != 0 or row["state"] != "headroom":
                continue
        elif not numeric(reset) or not observed < reset <= observed + minutes * 60 + 60:
            continue
        clean = dict(
            pool=pool,
            source=source,
            platform_id=platform,
            state=row["state"],
            observed_at=observed,
            resets_at=reset,
            used_percent=used,
            window_minutes=minutes,
        )
        previous = result.get(pool)
        # Duplicate rows may only make the observation more conservative.
        if previous is None or ORDER[clean["state"]] > ORDER[previous["state"]]:
            result[pool] = clean
    return [result[key] for key in sorted(result)]


def fresh(row: dict[str, Any], now: float) -> bool:
    ttl = 3600 if 0 < row["window_minutes"] <= 300 else 6 * 3600
    reset = row["resets_at"]
    return now - row["observed_at"] <= ttl and (reset is None or now < reset)


def merge(previous: Any, incoming: Any, now: float) -> list[dict[str, Any]]:
    """Only fresh, non-replayed observations replace saved states; absence retains."""
    rows = {row["pool"]: row for row in normalize(previous, now)}
    for row in normalize(incoming, now):
        old = rows.get(row["pool"])
        if fresh(row, now) and (old is None or row["observed_at"] > old["observed_at"]):
            rows[row["pool"]] = row
    return [rows[key] for key in sorted(rows)]


def states(raw: Any, now: float | None = None) -> dict[str, str]:
    now = time.time() if now is None else now
    result: dict[str, str] = {}
    for row in normalize(raw, now):
        state = row["state"]
        if row["resets_at"] is not None and now >= row["resets_at"]:
            state = "headroom"
        platform = row["platform_id"]
        if ORDER[state] > ORDER.get(result.get(platform, "headroom"), -1) or platform not in result:
            result[platform] = state
    return result


def table(raw: Any, now: float | None = None) -> str:
    now = time.time() if now is None else now
    rows = normalize(raw, now)
    if not rows:
        return ""
    lines = [
        "",
        "## Usage-pool status",
        "",
        "Metered states override an uncapped declaration for the matching platform. "
        "An exhausted OpenRouter reserve requires adding credits and never resets by time.",
        "",
        "| Pool | Window | State | Resets | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        source, name = row["pool"].split(":")
        label = {
            "claude": "Claude subscription",
            "codex": "Codex",
            "antigravity": "Antigravity",
            "openrouter": "OpenRouter credits",
        }[source]
        if name in ("weekly", "5h"):
            label += f" — {name}"
        reset = row["resets_at"]
        reset_text = (
            datetime.fromtimestamp(math.ceil(reset / 60) * 60, timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            if reset is not None
            else "—"
        )
        state = "headroom" if reset is not None and now >= reset else row["state"]
        lines.append(
            f"| {label} | metered | `{state}` | {reset_text} | "
            f"[auto: {source} {row['used_percent']:g}% at {row['observed_at']:g}] |"
        )
    return "\n".join(lines) + "\n"
