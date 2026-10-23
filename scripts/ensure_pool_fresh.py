#!/usr/bin/env python3
"""Session-start guard: keep the Usage-pool meters live without launchd.

Runs from a Claude Code SessionStart hook. When the Claude meter is missing or
older than --max-age, start the same private job the hourly agent runs
(detached, so the session never waits) and say so in one line; the hook's
stdout reaches the agent. It also reports when the hourly launchd agent is not
loaded, which is how the pool silently went stale for ten days. Silent when
everything is fresh. A throttle stamp keeps ten windows opening at once from
starting ten refreshes. Never changes launchd or any setting itself.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pool_usage import CACHE

LABEL = "com.roadmodel.roll-pool-status"
THROTTLE = 600  # seconds between refresh starts


def age_hours(seconds: float) -> str:
    return f"{seconds / 3600:.1f}h" if seconds < 48 * 3600 else f"{seconds / 86400:.0f}d"


def claude_age(cache: Path, now: float) -> float | None:
    try:
        data = json.loads((cache / "claude.json").read_text())
        observed = float(data["observed_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return max(0.0, now - observed)


def launchd_problem() -> str | None:
    """Why the hourly agent is not running, or None (also None off macOS)."""
    if sys.platform != "darwin":
        return None
    uid = os.getuid()
    try:
        loaded = subprocess.run(  # noqa: S603 — fixed argv
            ["/bin/launchctl", "print", f"gui/{uid}/{LABEL}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if loaded.returncode == 0:
            return None
        disabled = subprocess.run(  # noqa: S603 — fixed argv
            ["/bin/launchctl", "print-disabled", f"gui/{uid}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if f'"{LABEL}" => disabled' in disabled.stdout:
        return "disabled in launchd"
    return "not loaded in launchd"


def start_refresh(cache: Path, now: float) -> bool:
    """Start the private pool job detached unless one started recently."""
    stamp = cache / ".ensure-refresh"
    try:
        if now - stamp.stat().st_mtime < THROTTLE:
            return False
    except OSError:
        pass
    try:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp.touch(mode=0o600)
        os.utime(stamp, (now, now))
        job = Path(__file__).with_name("private_job.py")
        subprocess.Popen(  # noqa: S603 — fixed sibling script, detached
            [sys.executable, "-I", "-X", "utf8", str(job), "pools"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--max-age", type=float, default=3000.0, help="seconds before a refresh")
    args = ap.parse_args(argv)
    now = time.time()
    notes = []
    age = claude_age(args.cache, now)
    if age is None or age > args.max_age:
        seen = "never measured" if age is None else f"last measured {age_hours(age)} ago"
        started = start_refresh(args.cache, now)
        notes.append(
            f"Usage-pool meters were stale ({seen}); "
            + (
                "a background refresh was started, so recommendations after a minute use live headroom"
                if started
                else "a refresh started moments ago"
            )
        )
    problem = launchd_problem()
    if problem:
        notes.append(
            f"the hourly pool agent is {problem}; meters refresh only when a session starts"
        )
    if notes:
        print("roadmodel: " + "; ".join(notes) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
