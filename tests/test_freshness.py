"""Freshness check: warn loudly if the automated refresh hasn't run
in too long. The weekly cron is the project's heartbeat; this test
catches a stuck or disabled workflow before silent doc rot.
"""
from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STALE_DAYS_THRESHOLD = 14
BOT_AUTHOR = "roadmodel-bot"


def _last_bot_commit_timestamp() -> dt.datetime | None:
    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            f"--author={BOT_AUTHOR}",
            "--pretty=%ct",
            "--",
            "docs/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout.strip()
    if not output:
        return None
    return dt.datetime.fromtimestamp(int(output), tz=dt.timezone.utc)


def test_automation_recently_committed() -> None:
    last = _last_bot_commit_timestamp()
    if last is None:
        pytest.skip(
            f"No '{BOT_AUTHOR}' commits found in git history yet. "
            "First automated run hasn't happened, or git history is shallow."
        )
    age = dt.datetime.now(tz=dt.timezone.utc) - last
    assert age <= dt.timedelta(days=STALE_DAYS_THRESHOLD), (
        f"Last automated refresh was {age.days} days ago "
        f"(threshold: {STALE_DAYS_THRESHOLD} days). "
        f"The weekly cron may be broken — check "
        f".github/workflows/update-models.yml and the Actions tab."
    )
