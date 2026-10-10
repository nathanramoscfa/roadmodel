#!/usr/bin/env python3
"""Read the supported agy /usage panel, with quota-error-only log fallback.

No private Google endpoint is called. A local PTY invokes the documented
slash command, never a model prompt. Raw terminal output is discarded.
https://www.antigravity.google/docs/cli/commands/usage
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pool_usage import CACHE, save

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")
ERROR = re.compile(
    r"RESOURCE_EXHAUSTED|\b429\b|quota.{0,40}(?:exhausted|exceeded|reached)|(?:exhausted|exceeded).{0,40}quota",
    re.I,
)
STAMP = re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")


def parse_panel(raw: str, now: float) -> dict[str, Any] | None:
    text = ANSI.sub("", raw).replace("\r", "\n")
    windows = []
    for name, body in re.findall(
        r"(GEMINI MODELS|CLAUDE AND GPT MODELS)(.*?)(?=GEMINI MODELS|CLAUDE AND GPT MODELS|$)",
        text,
        re.S,
    ):
        match = re.search(
            r"(Weekly|5.Hour) Limit Remaining\s*\[[^\]]*\]\s*(\d+(?:\.\d+)?)%", body, re.I
        )
        if not match:
            continue
        remaining = float(match[2])
        if not 0 <= remaining <= 100:
            continue
        minutes = 10080 if match[1].lower() == "weekly" else 300
        reset = re.search(r"Refreshes in\s*(?:(\d+)h)?\s*(?:(\d+)m)?", body)
        resets_at = None
        if reset and (reset[1] or reset[2]):
            # The panel truncates minutes; wait one extra minute to avoid
            # expiring a live exhausted window early.
            resets_at = now + (int(reset[1] or 0) * 60 + int(reset[2] or 0) + 1) * 60
        elif remaining != 100 or "Quota available" not in body:
            continue
        windows.append(
            dict(
                name=("gemini" if name == "GEMINI MODELS" else "claude-gpt")
                + ("-weekly" if minutes == 10080 else "-5h"),
                used_percent=round(100 - remaining, 4),
                resets_at=resets_at,
                window_minutes=minutes,
            )
        )
    # A partially rendered panel cannot safely clear a group we didn't see.
    if len({w["name"].split("-")[0] for w in windows}) != 2:
        return None
    return dict(
        source="antigravity", observed_at=now, windows=windows, extra={"readout": "agy /usage"}
    )


def usage_panel(binary: str, timeout: float = 25) -> str:
    """Bounded PTY read of the documented command, with a tall viewport."""
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 65, 160, 0, 0))
    proc = subprocess.Popen(  # noqa: S603 — operator-selected installed CLI
        [binary],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "TERM": "xterm-256color", "NO_COLOR": "1"},
    )
    os.close(slave)
    data = ""
    sent = False
    scrolled = False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline and proc.poll() is None:
            if not select.select([master], [], [], 0.2)[0]:
                continue
            data += os.read(master, 65536).decode(errors="replace")
            clean = ANSI.sub("", data)
            if "Do you trust the contents" in clean:
                return data  # Keep the client's trust boundary; use log fallback.
            if not sent and "? for shortcuts" in clean:
                os.write(master, b"/usage")
                # Separate typing and Enter avoids TUI paste/autocomplete races.
                time.sleep(0.3)
                os.write(master, b"\r")
                sent = True
            if sent and parse_panel(data, time.time()):
                return data
            if sent and not scrolled and "CLAUDE AND GPT MODELS" in clean:
                os.write(master, b"\x1b[6~")
                scrolled = True
        return data  # Incomplete panels are rejected by parse_panel.
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        os.close(master)


def log_error(root: Path) -> dict[str, Any] | None:
    """Only actual timestamped failure records, never quoted conversation text.

    A file's modification time is NOT an error time. No errors means unknown,
    never headroom. Freshness is measured from the original error timestamp.
    """
    latest = 0.0
    for pattern in ("*.log", "*.json", "*.jsonl"):
        for path in root.rglob(pattern):
            try:
                with path.open(errors="replace") as handle:
                    for line in handle:
                        if not ERROR.search(line):
                            continue
                        candidate = None
                        if path.suffix in (".json", ".jsonl"):
                            try:
                                record = json.loads(line)
                                error = record.get("error")
                                if not error or not ERROR.search(json.dumps(error)):
                                    continue
                                candidate = record.get("timestamp")
                            except (ValueError, AttributeError):
                                continue
                        elif re.search(r"\b(?:ERROR|error|WARN|warn)\b", line):
                            stamp = STAMP.search(line)
                            candidate = stamp[0] if stamp else None
                        if candidate:
                            try:
                                latest = max(
                                    latest,
                                    datetime.fromisoformat(
                                        candidate.replace("Z", "+00:00")
                                    ).timestamp(),
                                )
                            except (ValueError, TypeError):
                                pass
            except OSError:
                continue
    if not latest:
        return None
    return dict(
        source="antigravity",
        observed_at=latest,
        windows=[
            dict(
                name="quota-error",
                used_percent=100,
                resets_at=latest + 5 * 3600,
                window_minutes=300,
                quota_error=True,
            )
        ],
        extra={"readout": "quota-error log"},
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument(
        "--logs", type=Path, default=Path.home() / ".gemini" / "antigravity-cli" / "log"
    )
    ap.add_argument("--agy", default="/opt/homebrew/bin/agy")
    ap.add_argument("--logs-only", action="store_true")
    args = ap.parse_args()
    snapshot = None
    if not args.logs_only:
        try:
            args.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            snapshot = parse_panel(usage_panel(args.agy), time.time())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    snapshot = snapshot or log_error(args.logs)
    if snapshot:
        save(snapshot, args.cache)
    print(
        "antigravity: snapshot saved"
        if snapshot
        else "antigravity: no meter; previous snapshot retained"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
