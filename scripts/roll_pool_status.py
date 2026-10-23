#!/usr/bin/env python3
"""Refresh real meters and maintain the private Usage-pool status table hourly.

Claude's account-wide weekly, 5h and Fable sub-cap come from the headless
`claude -p /usage` each run (the status-line wrapper is a secondary source).
Codex, OpenRouter and supported Antigravity /usage are refreshed each run.
Fresh observations set states and dated resets; stale/missing data retains
states. Known passed resets still clear caps, with weekly dates rolled forward.
No PAYG maker keys or local inference pools.

Stdlib only, Python 3.11+. --dry-run prints a unified diff without writing the
context file or collecting new data; --refresh also refreshes cache in a dry run.
--no-collect applies only existing snapshots. --sync-web also uploads fresh,
normalized observations with a per-user Keychain session, even when the local
table is unchanged. A dry run never authenticates or uploads.
See docs/usage-pools.md.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
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
STALE = re.compile(r"\s*\[stale: [^\]]*\]")
STAMP = re.compile(r"\[auto: [^\]]*? at (\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2}) ([A-Z]{2,4})\]")
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


def mark_stale(text: str, now: datetime) -> str:
    """Flag rows whose last real measurement is too old to trust, clear the flag
    when fresh. States are never changed here: only the Notes say the row is
    unverified, so a reader cannot mistake an old `headroom` for a live one."""
    lines = text.split("\n")
    in_section = False
    for i, line in enumerate(lines):
        if line.startswith("#"):
            in_section = line.lstrip("# ").strip() == SECTION
            continue
        cells = _split(line) if in_section else None
        if cells is None or len(cells) < 5:
            continue
        note = STALE.sub("", cells[4])
        m = STAMP.search(note)
        if m and m.group(4) in TZ_OFFSETS:
            tz = timezone(timedelta(hours=TZ_OFFSETS[m.group(4)]))
            seen = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
            limit = 3600 if cells[1].strip().lower().startswith("5 h") else 6 * 3600
            if (now - seen.replace(tzinfo=tz)).total_seconds() > limit:
                note = (
                    f"{note.rstrip()} [stale: no fresh meter since "
                    f"{m.group(1)} {m.group(2).zfill(2)}:{m.group(3)} {m.group(4)}; "
                    "state unverified]"
                )
        if note != cells[4]:
            lines[i] = "|" + "|".join([*cells[:4], f" {note.strip()} ", *cells[5:]]) + "|"
    return "\n".join(lines)


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
    marked = mark_stale(rolled_text, now)
    if marked != rolled_text:
        summary.append("stale-meter flags updated")
    return marked, summary


def refresh_collectors(cache: Path) -> None:
    for script in ("claude_usage", "codex", "openrouter", "antigravity"):
        source = script.split("_")[0]
        try:
            subprocess.run(  # noqa: S603 — fixed sibling scripts
                [
                    sys.executable,
                    "-I",
                    "-X",
                    "utf8",
                    str(
                        Path(__file__).with_name(
                            f"collect_{script}.py"
                            if script == "claude_usage"
                            else f"collect_{source}_pool.py"
                        )
                    ),
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
    """Private atomic replacement with optimistic conflict detection."""
    from local_private import private_files

    private = private_files()

    def unchanged() -> None:
        if private.read_private_output(path).decode("utf-8") != before:
            raise RuntimeError("context changed during update; retry")

    private.atomic_private_write(path, after.encode("utf-8"), before_replace=unchanged)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--zone", default="America/New_York")
    ap.add_argument("--no-collect", action="store_true")
    ap.add_argument(
        "--sync-web", action="store_true", help="Push fresh meters with a per-user Keychain session"
    )
    ap.add_argument("--refresh", action="store_true", help="Refresh cache even in a dry run")
    args = ap.parse_args(argv)
    path = args.file.resolve()
    if not path.is_file():
        print(f"roll_pool_status: {path} not found; nothing to do")
        return 0
    if not args.no_collect and (not args.dry_run or args.refresh):
        refresh_collectors(args.cache)
    # Preserve raw newlines so optimistic replacement compares the exact bytes
    # read, including a context created by a Windows editor.
    text = path.read_bytes().decode("utf-8")
    new, summary = roll(
        text, datetime.fromtimestamp(time.time(), timezone.utc), load(args.cache), args.zone
    )
    if not summary:
        print("roll_pool_status: no changes")
        if args.dry_run:
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
    elif new != text:
        write_context(path, text, new)
    if args.sync_web and not args.dry_run:
        return subprocess.run(  # noqa: S603 — fixed sibling script
            [
                sys.executable,
                "-I",
                "-X",
                "utf8",
                str(Path(__file__).with_name("push_pool_status.py")),
                "--cache",
                str(args.cache),
            ],
            check=False,
            timeout=120,
        ).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
