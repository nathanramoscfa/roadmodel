#!/usr/bin/env python3
"""Refresh real meters and maintain the private Usage-pool status table hourly.

Claude's status-line wrapper supplies account-wide weekly/5h snapshots.
Codex, OpenRouter and supported Antigravity /usage are refreshed each run.
Fresh observations set states and dated resets; stale/missing data retains
states. Known passed resets still clear caps, with weekly dates rolled forward.
The Fable sub-cap remains manual. No PAYG maker keys or local inference pools.

Stdlib only, Python 3.11+. --dry-run prints a unified diff without writing the
context file or collecting new data; --refresh also refreshes cache in a dry run.
--no-collect applies only existing snapshots. See docs/usage-pools.md.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pool_table import render
from pool_usage import CACHE, load

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "docs" / "user-context.md"
SECTION = "Usage-pool status"
MARKER = re.compile(r"\s*\[auto: [^\]]*\]")
RESET_RE = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(\d{4}-\d{2}-\d{2})[ T]+(\d{1,2}):(\d{2})\s*([A-Z]{2,4})"
)
# Zones the operator writes by hand. An unlisted one is NOT guessed at.
TZ_OFFSETS = {"UTC": 0, "GMT": 0, "Z": 0, "EDT": -4, "EST": -5, "CDT": -5, "CST": -6,
              "MDT": -6, "MST": -7, "PDT": -7, "PST": -8}  # fmt: skip


def _split(line: str) -> list[str] | None:
    """Cells of a markdown table row (without the outer pipes), else None."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    return s[1:-1].split("|")


def _fit(text: str, width: int) -> str:
    return f" {text} ".ljust(width) if len(text) + 2 <= width else f" {text} "


def roll_row(cells: list[str], now: datetime) -> tuple[list[str], str] | None:
    """New cells + a one-line summary, or None when the row needs no change."""
    if len(cells) < 4:
        return None
    window, state, reset = cells[1].strip(), cells[2], cells[3].strip()
    m = RESET_RE.search(reset)
    if not m or m.group(4) not in TZ_OFFSETS:
        return None
    tz = timezone(timedelta(hours=TZ_OFFSETS[m.group(4)]))
    at = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M").replace(
        tzinfo=tz
    )
    if now < at:
        return None
    out = list(cells)
    changes: list[str] = []
    if re.search(r"`?(tight|exhausted)`?", state):
        out[2] = _fit("`headroom`", len(state))
        changes.append("-> headroom")
    if window.lower().startswith("7 d"):
        while at <= now:
            at += timedelta(days=7)
        new_reset = f"{at.strftime('%a %Y-%m-%d %H:%M')} {m.group(4)}"
        out[3] = _fit(new_reset, len(cells[3]))
        changes.append(f"reset -> {new_reset}")
    if not changes:
        return None
    if len(cells) > 4 and "-> headroom" in changes:
        note = MARKER.sub("", cells[4]).rstrip()
        stamp = f" [auto: reset to headroom {now.astimezone(tz).strftime('%Y-%m-%d')}]"
        out[4] = f" {note.strip()}{stamp} "
    return out, f"{cells[0].strip()}: " + ", ".join(changes)


def roll(
    text: str,
    now: datetime,
    snapshots: dict[str, dict[str, Any]] | None = None,
    zone: str = "America/New_York",
) -> tuple[str, list[str]]:
    lines = text.split("\n")
    summary: list[str] = []
    in_section = False
    for i, line in enumerate(lines):
        if line.startswith("#"):
            in_section = line.lstrip("# ").strip() == SECTION
            continue
        if not in_section:
            continue
        cells = _split(line)
        if cells is None:
            continue
        rolled = roll_row(cells, now)
        if rolled:
            lines[i] = "|" + "|".join(rolled[0]) + "|"
            summary.append(rolled[1])
    rolled_text = "\n".join(lines)
    if snapshots is not None:
        updated = render(rolled_text, snapshots, now.timestamp(), zone)
        if updated != rolled_text:
            summary.append("fresh usage snapshots applied")
        rolled_text = updated
    return rolled_text, summary


def refresh_collectors(cache: Path) -> None:
    for source in ("codex", "openrouter", "antigravity"):
        try:
            subprocess.run(  # noqa: S603 — fixed sibling scripts
                [
                    sys.executable,
                    str(Path(__file__).with_name(f"collect_{source}_pool.py")),
                    "--cache",
                    str(cache),
                ],
                check=True,
                timeout=90,
            )
        except (OSError, subprocess.SubprocessError):
            print(
                f"roll_pool_status: {source} unavailable; retain previous observation",
                file=sys.stderr,
            )


def write_context(path: Path, before: str, after: str) -> None:
    """Atomic replacement preserving permissions and refusing concurrent edits."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(after)
        if path.read_text(encoding="utf-8") != before:
            raise RuntimeError("context changed during update; retry")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--zone", default="America/New_York")
    ap.add_argument("--no-collect", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="Refresh cache even in a dry run")
    args = ap.parse_args(argv)
    path = args.file.resolve()
    if not path.is_file():
        print(f"roll_pool_status: {path} not found; nothing to do")
        return 0
    if not args.no_collect and (not args.dry_run or args.refresh):
        refresh_collectors(args.cache)
    text = path.read_text(encoding="utf-8")
    new, summary = roll(
        text, datetime.fromtimestamp(time.time(), timezone.utc), load(args.cache), args.zone
    )
    if not summary:
        print("roll_pool_status: no changes")
        return 0
    for s in summary:
        print(f"roll_pool_status: {s}")
    if args.dry_run:
        print(
            "".join(
                difflib.unified_diff(
                    text.splitlines(True),
                    new.splitlines(True),
                    fromfile=str(path),
                    tofile=str(path),
                )
            ),
            end="",
        )
    else:
        write_context(path, text, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
