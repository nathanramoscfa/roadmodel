# tests/test_ci_smoke.py
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
EXPECTED_JOBS = {"build", "sign", "testpypi-upload", "pypi-upload", "github-release"}


def test_release_workflow_exists_and_has_required_jobs() -> None:
    assert RELEASE_WORKFLOW_PATH.exists(), f"Missing workflow: {RELEASE_WORKFLOW_PATH}"

    workflow = yaml.safe_load(RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "release.yml did not parse to a top-level mapping"

    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "release.yml is missing a top-level 'jobs' mapping"

    missing = EXPECTED_JOBS - set(jobs)
    assert not missing, f"release.yml is missing expected jobs: {sorted(missing)}"
