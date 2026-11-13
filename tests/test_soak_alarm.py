"""The recommender soak fails loudly when production stops answering.

From 2026-09-21 to 2026-09-24 every production recommendation failed (the
service crashed at import) while `recommend-soak.yml` stayed green: its quality
bar is report-only, and its tracking issue already fails daily on known
residuals, so nobody read it as an alarm. `scripts/soak-health.ts` now marks the
service DOWN when half or more requests fail (exit 3); the workflow then fails
the run and opens an incident issue that closes itself on recovery. The
cron-health alarm, which watches every scheduled workflow, posts with the
workflow's own token: the App token's comments were refused, so it never
posted at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SOAK = REPO_ROOT / ".github" / "workflows" / "recommend-soak.yml"


def _steps() -> dict[str, dict[str, Any]]:
    wf = yaml.safe_load(SOAK.read_text())
    return {s["name"]: s for s in wf["jobs"]["soak"]["steps"] if "name" in s}


def test_the_script_reports_health_and_exits_3_when_down() -> None:
    script = (REPO_ROOT / "scripts" / "soak-recommend.ts").read_text()
    assert "healthLine(health)" in script
    assert "process.exitCode = health.down ? EXIT_DOWN" in script
    helper = (REPO_ROOT / "scripts" / "soak-health.ts").read_text()
    assert "export const EXIT_DOWN = 3;" in helper
    assert "SERVICE_HEALTH:" in helper


def test_a_down_service_opens_the_alarm_and_fails_the_run() -> None:
    steps = _steps()
    run = steps["Run soak (report-only)"]["run"]
    assert "health=$(grep -m1 '^SERVICE_HEALTH:' \"$SOAK_LOG\"" in run
    alarm = steps["Alarm while the recommender is down"]
    assert "steps.soak.outputs.exit == '3'" in alarm["if"]
    script = alarm["with"]["script"]
    assert "i.title === title" in script  # exact-title dedup, never search
    assert "createComment" in script and "issues.create(" in script
    fail = steps["Fail the run while the recommender is down"]
    assert "steps.soak.outputs.exit == '3'" in fail["if"]
    assert "exit 1" in fail["run"]
    # The alarm is filed before the run fails, or it would never be filed.
    names = list(steps)
    assert names.index("Alarm while the recommender is down") < names.index(
        "Fail the run while the recommender is down"
    )


def test_recovery_closes_the_alarm() -> None:
    close = _steps()["Close the alarm once the recommender answers again"]
    assert "steps.soak.outputs.exit != '3'" in close["if"]
    assert "steps.soak.outputs.exit != ''" in close["if"]  # the soak actually ran
    assert 'state: "closed"' in close["with"]["script"]


def test_a_run_that_meets_the_bar_closes_the_tracking_issue() -> None:
    """The tracking issue said it resolved itself, but nothing closed it: #1514
    (one slow morning run, passed two hours later) would have stayed open until
    someone closed it by hand. Only a run that scored the whole bar closes it."""
    steps = _steps()
    track = steps["Track regression in a single issue"]["with"]["script"]
    close = steps["Close the tracking issue once the bar is met"]
    cond = close["if"]
    assert "steps.soak.outputs.finished == 'true'" in cond
    assert "steps.soak.outputs.exit == '0'" in cond
    assert "steps.judge.outputs.exit == '0'" in cond
    # judge: false scores B2 alone, so it cannot clear a B6 miss.
    assert "(github.event_name == 'schedule' || inputs.judge)" in cond
    script = close["with"]["script"]
    title = 'const title = "Recommender soak: quality bar not met";'
    assert title in track and title in script  # closes the issue the miss opened
    assert 'labels: "dogfood"' in script and "i.title === title" in script
    assert 'state: "closed"' in script and "createComment" in script
    names = list(steps)
    assert names.index("Track regression in a single issue") < names.index(
        "Close the tracking issue once the bar is met"
    )


def test_a_soak_that_never_scores_fails_the_run() -> None:
    """From 2026-10-13 to 2026-11-12 the soak crashed before its first request:
    #1105 made the sign-in account required and the workflow never passed one.
    The job stayed green, so nobody saw it. The account is passed and required
    now, and a run that ends without the scorecard fails instead of reporting."""
    steps = _steps()
    account = "${{ secrets.ROADMODEL_DOGFOOD_EMAIL }}"
    check = steps["Check prod-soak secrets present"]
    assert check["env"]["ROADMODEL_DOGFOOD_EMAIL"] == account
    assert "exit 1" in check["run"]
    soak = steps["Run soak (report-only)"]
    assert soak["env"]["ROADMODEL_DOGFOOD_EMAIL"] == account
    assert "grep -q '^SOAK_DONE'" in soak["run"] and "finished=false" in soak["run"]
    script = (REPO_ROOT / "scripts" / "soak-recommend.ts").read_text()
    assert 'console.log("SOAK_DONE")' in script
    # A run that never scored reports no scorecard and no recovery.
    for name in (
        "Score B2 and B6 (judge)",
        "Track regression in a single issue",
        "Close the tracking issue once the bar is met",
        "Close the alarm once the recommender answers again",
    ):
        assert "steps.soak.outputs.finished == 'true'" in steps[name]["if"], name
    fail = steps["Fail the run when the soak did not finish"]
    assert "steps.soak.outputs.finished != 'true'" in fail["if"]
    assert "exit 1" in fail["run"]


def test_cron_health_posts_with_the_workflow_token() -> None:
    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "cron-health.yml").read_text())
    assert wf["jobs"]["health"]["permissions"]["issues"] == "write"
    step = next(
        s
        for s in wf["jobs"]["health"]["steps"]
        if s.get("name") == "File or clear the tracking issue"
    )
    # A workflow expression naming the token, not a secret value.
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"  # noqa: S105
