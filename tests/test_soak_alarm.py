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
    assert "process.exit(health.down ? EXIT_DOWN" in script
    helper = (REPO_ROOT / "scripts" / "soak-health.ts").read_text()
    assert "export const EXIT_DOWN = 3;" in helper
    assert "SERVICE_HEALTH:" in helper


def test_a_down_service_opens_the_alarm_and_fails_the_run() -> None:
    steps = _steps()
    run = steps["Run soak (report-only)"]["run"]
    assert "health=$(grep -m1 '^SERVICE_HEALTH:' /tmp/soak.log" in run
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


def test_cron_health_posts_with_the_workflow_token() -> None:
    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "cron-health.yml").read_text())
    assert wf["permissions"]["issues"] == "write"
    step = next(
        s
        for s in wf["jobs"]["health"]["steps"]
        if s.get("name") == "File or clear the tracking issue"
    )
    # A workflow expression naming the token, not a secret value.
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"  # noqa: S105
