"""Freshness check: warn loudly if the automated refresh hasn't run
in too long. The daily cron is the project's heartbeat; this test
catches a stuck or disabled workflow before silent doc rot.

WHERE THIS RUNS (and why it is not a per-PR gate). This guard is marked
``freshness`` and is DESELECTED from the per-PR test matrix and from
verify-phase01's V2.2 lane; it runs in the daily alarm
(``.github/workflows/cron-health.yml``), which files a tracking issue when
it fires.

That split exists because the guard's old wiring deadlocked the repo. When
the catalog cron broke (2026-08-21, Opus output truncated at max_tokens),
this test went red on EVERY pull request — including the PRs that fix the
cron. A stale catalog then blocked its own repair, and five cron PRs rotted
into conflicts behind it. An alarm that blocks the fix for the thing it is
alarming about is worse than no alarm.

Deselecting is NOT the same as skipping: the assertion still runs daily, at
full strength, on a schedule, and its failure is loud (a filed issue) rather
than silent. Do not weaken the assertion itself, and do not turn the
``None`` branch below into a skip on a full clone.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STALE_DAYS_THRESHOLD = 14
# The cron's commit identity. This is the GitHub App (`roadmodel-cron-bot`)
# that replaced the retired maintainer PAT; commits land as
# "roadmodel-cron-bot[bot]". The value here was still the PAT-era
# "roadmodel-bot", which is NOT a substring of the App's name, so
# `git log --author=` matched nothing and this guard silently skipped from the
# App migration onward — through the exact stall it exists to catch (26 cron
# PRs unmerged, the catalog missing Claude Opus 5 for two weeks).
BOT_AUTHOR = "roadmodel-cron-bot"


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


def _is_shallow_clone() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() == "true"


@pytest.mark.freshness
def test_automation_recently_committed() -> None:
    last = _last_bot_commit_timestamp()
    if last is None:
        # A shallow clone genuinely cannot see the history, so skipping is
        # correct there. With FULL history (tests.yml gives test-matrix
        # fetch-depth: 0), "no bot commits at all" is itself the alarm: either
        # the cron has never landed anything, or BOT_AUTHOR no longer matches
        # the identity it commits under. Skipping that case is how this guard
        # went quiet for weeks — fail instead.
        if _is_shallow_clone():
            pytest.skip(
                f"Shallow clone: cannot search history for '{BOT_AUTHOR}' commits. "
                "Run with fetch-depth: 0 for this guard to mean anything."
            )
        raise AssertionError(
            f"No '{BOT_AUTHOR}' commits touching docs/ found in full git history. "
            "Either the automated refresh has never landed, or its commit identity "
            "changed and BOT_AUTHOR is now stale — check the author on recent cron "
            "commits (`git log --format='%an' -- docs/`) and update it. Do NOT "
            "relax this into a skip: a silently-skipping freshness guard is "
            "indistinguishable from a healthy one."
        )
    age = dt.datetime.now(tz=dt.timezone.utc) - last
    assert age <= dt.timedelta(days=STALE_DAYS_THRESHOLD), (
        f"Last automated refresh was {age.days} days ago "
        f"(threshold: {STALE_DAYS_THRESHOLD} days). "
        f"The weekly cron may be broken — check "
        f".github/workflows/update-models.yml and the Actions tab."
    )
