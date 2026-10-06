#!/usr/bin/env python3
"""Tidy the ``Usage-pool status`` table in docs/user-context.md after a reset.

The selector already READS a `tight` / `exhausted` row whose dated Resets time
has passed as `headroom` (src/roadmodel/scoring.py ``pool_states``). This
script makes the FILE say the same thing, so it never shows a stale cap:

- a `tight` / `exhausted` row whose reset has passed becomes `headroom`;
- a dated row with a 7-day window (passed reset, any state) gets its Resets
  cell rolled forward in whole weeks, keeping the weekday and time of day.

Rows with a rolling / undated Resets cell, or a time in a zone this script does
not know, are left alone — the same asymmetry as the scorer: wrongly clearing
a LIVE exhausted pool bills overflow at list price. It never SETS `tight` or
`exhausted`: nothing here can read the Claude Code usage meter, so that flip
stays the operator's.

Stdlib only; idempotent. Run daily via launchd (see
scripts/com.roadmodel.roll-pool-status.plist).

  roll_pool_status.py [--file docs/user-context.md] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def roll(text: str, now: datetime) -> tuple[str, list[str]]:
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
    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    path = args.file.resolve()
    if not path.is_file():
        print(f"roll_pool_status: {path} not found; nothing to do")
        return 0
    text = path.read_text(encoding="utf-8")
    new, summary = roll(text, datetime.now(timezone.utc))
    if not summary:
        print("roll_pool_status: no expired rows")
        return 0
    for s in summary:
        print(f"roll_pool_status: {s}")
    if not args.dry_run:
        path.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
