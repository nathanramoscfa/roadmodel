#!/usr/bin/env python3
"""Cache Claude's account meters from the supported headless `claude -p /usage`.

Works from any surface (the VS Code extension never runs the status line) and
spends no model usage: /usage is answered locally by the CLI. Writes the same
claude snapshot as the status-line wrapper, plus the Fable weekly sub-cap.
Parsing is strict; unexpected output saves nothing, so the previous
observation ages out rather than being replaced by a guess.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pool_usage import CACHE, save, window

LINES = (
    ("5h", 300, re.compile(r"^Current session:\s*(.+)$", re.M)),
    ("weekly", 10080, re.compile(r"^Current week \(all models\):\s*(.+)$", re.M)),
    ("fable", 10080, re.compile(r"^Current week \(Fable\):\s*(.+)$", re.M)),
)
BODY = re.compile(
    r"^(?P<pct><?\d+(?:\.\d+)?)%\s+used\s*·\s*resets\s+(?P<when>.+?)\s*\((?P<zone>[A-Za-z_]+/[A-Za-z_]+)\)\s*$"
)
WHEN = re.compile(
    r"^(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+at\s+)?(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?(?P<ampm>am|pm)$"
)


def parse_reset(when: str, zone: str, now: float) -> float | None:
    """Epoch seconds of the printed reset, or None when it cannot be read exactly."""
    m = WHEN.match(when)
    if not m:
        return None
    try:
        tz = ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        return None
    hour = int(m["hour"]) % 12 + (12 if m["ampm"] == "pm" else 0)
    local = datetime.fromtimestamp(now, tz)
    try:
        if m["mon"]:
            month = datetime.strptime(m["mon"], "%b").month
            at = local.replace(
                month=month, day=int(m["day"]), hour=hour, minute=int(m["min"] or 0),
                second=0, microsecond=0,
            )  # fmt: skip
            if at.timestamp() < now - 2 * 86400:
                at = at.replace(year=at.year + 1)
        else:  # A reset within a day prints only the time: the next such moment.
            at = local.replace(hour=hour, minute=int(m["min"] or 0), second=0, microsecond=0)
            if at.timestamp() <= now:
                at += timedelta(days=1)
    except ValueError:
        return None
    return at.timestamp()


def parse(text: str, now: float) -> dict[str, Any] | None:
    windows = []
    for name, minutes, pattern in LINES:
        line = pattern.search(text)
        body = BODY.match(line.group(1).strip()) if line else None
        if not body:
            continue
        used = float(body["pct"].lstrip("<")) if not body["pct"].startswith("<") else 0.5
        reset = parse_reset(body["when"], body["zone"], now)
        meter = window(name, used, reset, minutes)
        if meter:
            windows.append(meter)
    # Without the all-models weekly line there is no pool to describe.
    if not any(w["name"] == "weekly" for w in windows):
        return None
    return dict(source="claude", observed_at=now, windows=windows, extra={})


def find_claude() -> str | None:
    """launchd's PATH is minimal, so look where the CLI is normally installed."""
    extra = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")]
    return shutil.which("claude", path=os.pathsep.join([os.environ.get("PATH", ""), *extra]))


def collect(now: float, cwd: Path, attempts: int = 3) -> dict[str, Any] | None:
    """Run /usage, retrying: a cold CLI sometimes prints a cost summary instead."""
    claude = find_claude()
    if claude is None:
        return None
    # launchd hands a job almost no environment; the CLI needs HOME and USER to
    # find its login. Pass exactly those, never the caller's tokens or session ids.
    env = {
        "HOME": str(Path.home()),
        "USER": os.environ.get("USER") or getpass.getuser(),
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
    }
    for attempt in range(attempts):
        if attempt:
            time.sleep(3)
        try:
            result = subprocess.run(  # noqa: S603 — absolute CLI path, fixed arguments
                [claude, "-p", "/usage"],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=cwd,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            continue
        snapshot = parse(result.stdout, time.time()) if result.returncode == 0 else None
        if snapshot:
            return snapshot
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args(argv)
    try:
        snapshot = collect(time.time(), Path.home())
    except (OSError, subprocess.SubprocessError):
        snapshot = None
    if snapshot is None:
        print(
            "collect_claude_usage: /usage unavailable or unreadable; nothing saved", file=sys.stderr
        )
        return 1
    save(snapshot, args.cache)
    print("claude: snapshot saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
