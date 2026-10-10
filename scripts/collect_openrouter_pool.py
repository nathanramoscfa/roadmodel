#!/usr/bin/env python3
"""One GET of OpenRouter's current-key meter; the key stays in process memory."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pool_usage import CACHE, number, save


def collect(data: dict[str, Any], now: float) -> dict[str, Any] | None:
    data = data.get("data", {})
    if not isinstance(data, dict):
        return None
    # Deliberate allowlist: never persist the key, label or raw response.
    extra = {
        k: number(data.get(k))
        for k in (
            "usage",
            "limit",
            "limit_remaining",
            "usage_daily",
            "usage_weekly",
            "usage_monthly",
        )
    }
    if extra["limit"] is None or extra["limit_remaining"] is None:
        return None
    reset = data.get("limit_reset")
    extra["limit_reset"] = reset if reset in ("daily", "weekly", "monthly") else None
    return dict(source="openrouter", observed_at=now, windows=[], extra=extra)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args()
    try:
        key = (
            subprocess.run(  # noqa: S603
                [
                    "/usr/bin/security",
                    "find-generic-password",
                    "-s",
                    "roadmodel/OPENROUTER_API_KEY",
                    "-w",
                ],
                capture_output=True,
                check=True,
                timeout=10,
            )
            .stdout.decode()
            .strip()
        )
        if not key:
            raise ValueError("empty credential")
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            snapshot = collect(json.load(response), time.time())
        if snapshot is None:
            raise ValueError("unsupported meter")
        save(snapshot, args.cache)
    except (OSError, ValueError, subprocess.SubprocessError, urllib.error.URLError):
        # Exceptions can contain request metadata: never print their text.
        print("openrouter: collection failed; previous snapshot retained", file=sys.stderr)
        return 1
    print("openrouter: snapshot saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
