#!/usr/bin/env python3
"""Claude status-line wrapper: cache meters, then run the saved original command.

Use --original FILE for a private JSON copy of the complete original statusLine
object. The original command gets byte-identical stdin, inherited environment,
cwd, stdout and stderr. Without an original, render compact weekly/5h usage.
No settings are changed by this script.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pool_usage import CACHE, save, window


def collect(data: dict[str, Any], now: float) -> dict[str, Any] | None:
    limits = data.get("rate_limits")
    if not isinstance(limits, dict):
        return None  # First-response absence must not refresh older observations.
    windows = []
    for field, minutes, name in [("seven_day", 10080, "weekly"), ("five_hour", 300, "5h")]:
        value = limits.get(field)
        if isinstance(value, dict):
            meter = window(name, value.get("used_percentage"), value.get("resets_at"), minutes)
            if meter:
                windows.append(meter)
    return dict(source="claude", observed_at=now, windows=windows, extra={}) if windows else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original", type=Path)
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    raw = sys.stdin.buffer.read()
    snapshot = None
    try:
        data = json.loads(raw)
        snapshot = collect(data, time.time()) if isinstance(data, dict) else None
        if snapshot:
            save(snapshot, args.cache)
    except (ValueError, OSError):
        pass  # Collection failure must never break the operator's status line.
    if args.original:
        original = json.loads(args.original.read_text())
        if isinstance(original, dict) and original.get("command"):
            # This is the operator's exact existing shell command, by design.
            return subprocess.run(original["command"], shell=True, input=raw).returncode  # noqa: S602
    if snapshot:
        labels = {"weekly": "wk", "5h": "5h"}
        print(
            " · ".join(f"{labels[w['name']]} {w['used_percent']:g}%" for w in snapshot["windows"])
        )
    else:
        print("wk — · 5h —")
    return 0


if __name__ == "__main__":
    sys.exit(main())
