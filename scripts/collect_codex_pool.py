#!/usr/bin/env python3
"""Read the newest account-wide Codex rate_limits event across rollout logs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pool_usage import CACHE, save, window


def collect(sessions: Path) -> dict[str, Any] | None:
    latest = None
    for path in sessions.rglob("rollout-*.jsonl"):
        try:
            # Stream: long-lived sessions can be hundreds of MB. Do not read
            # transcripts into cache or use mtime as the observation time.
            with path.open() as handle:
                for line in handle:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                        payload = event.get("payload", {})
                        limits = payload.get("rate_limits")
                        at = datetime.fromisoformat(
                            event["timestamp"].replace("Z", "+00:00")
                        ).timestamp()
                        if not isinstance(limits, dict) or (latest and at <= latest["observed_at"]):
                            continue
                        if limits.get("limit_id") not in (None, "codex"):
                            continue  # Do not use a separate per-model meter as the account pool.
                        windows = []
                        for slot in ("primary", "secondary"):
                            value = limits.get(slot)
                            if not isinstance(value, dict):
                                continue
                            minutes = value.get("window_minutes")
                            name = (
                                "weekly" if minutes == 10080 else "5h" if minutes == 300 else slot
                            )
                            meter = window(
                                name, value.get("used_percent"), value.get("resets_at"), minutes
                            )
                            if meter:
                                windows.append(meter)
                        if windows:
                            latest = dict(
                                source="codex",
                                observed_at=at,
                                windows=windows,
                                extra={
                                    "rate_limit_reached": bool(
                                        limits.get("rate_limit_reached_type")
                                    )
                                },
                            )
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue  # Partial live lines and old schemas are normal.
        except OSError:
            continue
    return latest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=Path, default=Path.home() / ".codex" / "sessions")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    snapshot = collect(args.sessions)
    if snapshot:
        save(snapshot, args.cache)
    print("codex: snapshot saved" if snapshot else "codex: no meter; previous snapshot retained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
