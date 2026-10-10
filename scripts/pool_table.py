"""Pure usage-table rendering, shared by preview and the hourly updater."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pool_usage import decide, number

MARKER = re.compile(r"\s*\[auto: [^\]]*\]")
ORDER = {"headroom": 0, "tight": 1, "exhausted": 2}


def render(
    text: str, snapshots: dict[str, dict[str, Any]], now: float, zone: str = "America/New_York"
) -> str:
    """Update known rows, preserve manual sub-caps and all other content.

    Unknown/missing/stale data leaves each row alone. Only known fresh
    windows can add rows. For a grouped pool ALL windows must be fresh to
    lower a state; a fresh exhausted group can still raise it.
    """
    tz = ZoneInfo(zone)
    lines = text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == "## Usage-pool status"), None
    )
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    rows: dict[str, int] = {}
    for i in range(start + 1, end):
        cells = lines[i].strip().strip("|").split("|")
        if len(cells) < 5 or not lines[i].lstrip().startswith("|"):
            continue
        name = cells[0].strip().lower()
        if "fable" in name or "sub-cap" in name:
            continue
        if "claude" in name and ("weekly" in name or "5-hour" in name or "5h" in name):
            rows["claude:weekly" if "weekly" in name else "claude:5h"] = i
        elif "codex" in name:
            rows["codex:weekly" if "week" in name else "codex:5h"] = i
        elif "antigravity" in name:
            rows["antigravity:all"] = i
        elif "openrouter" in name:
            rows["openrouter:credits"] = i
    additions = []
    for source, snapshot in snapshots.items():
        meters = snapshot.get("windows")
        if not isinstance(meters, list):
            continue
        groups = [(m.get("name"), [m]) for m in meters if isinstance(m, dict)]
        if source == "antigravity":
            groups = [("all", meters)] if meters else []
        elif source == "openrouter":
            groups = [("credits", [None])]
        for name, group in groups:
            if source in ("claude", "codex") and name not in ("weekly", "5h"):
                continue
            states = [decide(snapshot, meter, now) for meter in group]
            valid = [state for state in states if state is not None]
            if not valid:
                continue
            state = max(valid, key=ORDER.__getitem__)
            key = f"{source}:{name}"
            index = rows.get(key)
            if index is not None:
                cells = [c.strip() for c in lines[index].strip().strip("|").split("|")]
                old = cells[2].strip("` ")
                if old in ORDER and ORDER[state] < ORDER[old] and len(valid) != len(group):
                    continue
            else:
                labels = {
                    "claude": "Claude subscription",
                    "codex": "Codex",
                    "antigravity": "Antigravity",
                    "openrouter": "OpenRouter credits",
                }
                cells = [
                    labels[source] + (f" — {name}" if name in ("weekly", "5h") else ""),
                    "",
                    "",
                    "—",
                    "",
                ]
            # A missing reset from a fully unused agy group is real unknown,
            # not a synthetic seven-day date. Other groups' resets still apply.
            resets = [
                m["resets_at"]
                for m, s in zip(group, states, strict=True)
                if isinstance(m, dict) and s == state and number(m.get("resets_at")) is not None
            ]
            reset_text = (
                datetime.fromtimestamp(max(resets), tz).strftime("%a %Y-%m-%d %H:%M %Z")
                if resets
                else cells[3]
            )
            minutes = {m.get("window_minutes") for m in group if isinstance(m, dict)}
            period = (
                "7 days" if minutes == {10080} else "5 hours" if minutes == {300} else "metered"
            )
            if source == "openrouter":
                period = "fixed reserve"
                # A prepaid reserve with no automatic top-up NEVER resets.
                reset_text = "—"
            before = list(cells)
            if source == "codex" and name == "weekly":
                cells[0] = re.sub(r"5h\s*/\s*weekly", "weekly", cells[0], flags=re.I)
            cells[1:4] = [period, f"`{state}`", reset_text]
            used = [
                m["used_percent"]
                for m in group
                if isinstance(m, dict) and number(m.get("used_percent")) is not None
            ]
            if source == "openrouter":
                extra = snapshot.get("extra", {})
                limit, remaining = number(extra.get("limit")), number(extra.get("limit_remaining"))
                used = (
                    [max(0, min(100, 100 * (1 - remaining / limit)))]
                    if limit and remaining is not None
                    else []
                )
            percentage = f"{max(used):.2f}".rstrip("0").rstrip(".") + "%" if used else "unknown"
            stamp = datetime.fromtimestamp(snapshot["observed_at"], tz).strftime(
                "%Y-%m-%d %H:%M %Z"
            )
            cells[4] = (
                MARKER.sub("", cells[4]).strip() + f" [auto: {source} {percentage} at {stamp}]"
            )
            if index is not None and before == cells:
                continue
            line = "| " + " | ".join(cells) + " |\n"
            if index is None:
                additions.append(line)
            else:
                lines[index] = line
    if additions:
        # Insert after the existing table, before following explanatory prose.
        insertion = max(
            [i + 1 for i in range(start + 1, end) if lines[i].lstrip().startswith("|")],
            default=start + 1,
        )
        lines[insertion:insertion] = additions
    return "".join(lines)
