from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name: str) -> dict[str, Any]:
    return dict(yaml.safe_load((ROOT / ".github/workflows" / name).read_text()))


def test_actions_and_app_tokens_are_scoped() -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        data = workflow(path.name)
        assert data["permissions"] == {}, path
        for job in data["jobs"].values():
            assert "permissions" in job, path
            for step in job.get("steps", []):
                use = step.get("uses", "")
                if use:
                    assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", use), use
                if use.startswith("actions/checkout@"):
                    assert "persist-credentials" in step["with"]
                if use.startswith("actions/create-github-app-token@"):
                    args = step["with"]
                    assert args["owner"] == "${{ github.repository_owner }}"
                    assert args["repositories"] == "${{ github.event.repository.name }}"
                    permissions = {k for k in args if k.startswith("permission-")}
                    assert permissions
                    assert permissions <= {
                        "permission-contents",
                        "permission-pull-requests",
                        "permission-issues",
                    }


def test_required_gate_includes_security_results() -> None:
    jobs = workflow("tests.yml")["jobs"]
    for name in ("workflow-security", "codeql", "security-scan", "bandit-whole-tree"):
        assert name in jobs["test"]["needs"]
        assert f"needs.{name}.result" in jobs["test"]["steps"][0]["run"]
    security = "\n".join(s.get("run", "") for s in jobs["workflow-security"]["steps"])
    assert "--require-hashes" in security and "sha256sum -c" in security
    assert "gitleaks git --redact=100" in security
    assert "check_codeql_sarif.py" in jobs["codeql"]["steps"][-1]["run"]


def test_codeql_runs_full_queries_and_binds_success_before_enforcement() -> None:
    job = workflow("tests.yml")["jobs"]["codeql"]
    assert job["env"]["CODEQL_ACTION_DIFF_INFORMED_QUERIES"] == "false"
    assert job["env"]["CODEQL_OVERLAY_DATABASE_MODE"] == "none"
    assert set(job["strategy"]["matrix"]["language"]) == {"python", "javascript-typescript"}
    steps = job["steps"]
    checkout, snapshot, init, analyze, review, upload, enforce = steps
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    assert "-B -I scripts/check_codeql_sarif.py snapshot" in snapshot["run"]
    assert init["with"]["queries"] == "security-extended"
    assert init["with"]["tools"] == "linked"
    assert init["with"]["build-mode"] == "none"
    assert analyze["with"]["upload"] == "always"
    assert analyze["with"]["wait-for-processing"] is True
    for step in (review, enforce):
        assert "always()" in step["if"] and "!cancelled()" in step["if"]
        assert step["env"]["CODEQL_ANALYZE_OUTCOME"] == "${{ steps.codeql_analyze.outcome }}"
        assert "--snapshot" in step["run"]
        assert "-B -I scripts/check_codeql_sarif.py" in step["run"]
    assert " review " in review["run"] and " check " in enforce["run"]
    assert "always()" in upload["if"] and "steps.codeql_review.outcome == 'success'" in upload["if"]
    assert upload["with"]["path"] == "${{ runner.temp }}/codeql-review.json"
    assert upload["with"]["if-no-files-found"] == "error"
    assert all("continue-on-error" not in step for step in steps)


def test_bandit_uses_pristine_checkout_and_isolated_locked_runner() -> None:
    job = workflow("tests.yml")["jobs"]["bandit-whole-tree"]
    checkout, _, install, fixtures, snapshot, analyze, upload = job["steps"]
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    assert "--require-hashes --no-compile" in install["run"]
    assert "security_bandit_runner_acceptance.py" in fixtures["run"]
    for step, command in ((snapshot, "snapshot"), (analyze, "run")):
        assert f"-I -B scripts/check_bandit.py {command}" in step["run"]
    assert "--review-output" in analyze["run"] and "--snapshot" in analyze["run"]
    assert "always()" in upload["if"] and "!cancelled()" in upload["if"]
    assert upload["with"]["path"] == "${{ runner.temp }}/bandit-review.json"
    assert upload["with"]["if-no-files-found"] == "error"
    assert not any("pip install -e" in s.get("run", "") for s in job["steps"])
    assert all("continue-on-error" not in s for s in job["steps"])


def test_release_builds_verified_commit_and_preserves_manual_gate() -> None:
    jobs = workflow("release.yml")["jobs"]
    assert jobs["build"]["needs"] == "verify"
    assert "github.ref == 'refs/heads/main'" in jobs["verify"]["if"]
    assert jobs["verify"]["steps"][0]["with"]["ref"] == "main"
    builds = jobs["build"]["steps"]
    assert builds[1]["with"]["ref"] == "${{ needs.verify.outputs.commit }}"
    assert "--no-isolation" in builds[-2]["run"]
    assert jobs["pypi-upload"]["environment"] == "pypi-production"
    assert "workflow_dispatch" in jobs["pypi-upload"]["if"]
    for name in ("pypi-upload", "testpypi-upload", "github-release"):
        job = jobs[name]
        assert "verify" in job["needs"]
        assert any("--expect-object" in step.get("run", "") for step in job["steps"])


@pytest.mark.parametrize("field", ["VERSION_INPUT", "SOURCE"])
@pytest.mark.parametrize("value", ['$(touch "$MARKER")', 'x"; touch "$MARKER"; #', "v1.2.3\ntrue"])
def test_install_inputs_cannot_execute_shell(field: str, value: str, tmp_path: Path) -> None:
    step = next(
        s
        for s in workflow("verify-pypi.yml")["jobs"]["install-smoke"]["steps"]
        if s.get("name") == "Install roadmodel"
    )
    assert "${{" not in step["run"]
    marker = tmp_path / "executed"
    env = {
        **os.environ,
        "VERSION_INPUT": "v1.2.3",
        "SOURCE": "pypi",
        field: value,
        "MARKER": str(marker),
    }
    result = subprocess.run(["bash", "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize("producer", ["models", "claude-code", "codex", "deepseek", "gemini"])
@pytest.mark.parametrize("dry_run", ["true", "false", ""])
def test_producer_flags_remain_separate_arguments(producer: str, dry_run: str) -> None:
    steps = workflow(f"update-{producer}.yml")["jobs"]["update"]["steps"]
    step = next(s for s in steps if "ARGS=" in s.get("run", ""))
    result = subprocess.run(
        ["bash", "-c", "python() { printf '%s\\0' \"$@\"; };\n" + step["run"]],
        env={**os.environ, "DRY_RUN": dry_run, "DOCS_CHANGED": "true", "EVENT_NAME": "schedule"},
        capture_output=True,
        check=True,
    )
    arguments = result.stdout.decode().split("\0")[:-1]
    expected = [] if producer == "models" else ["--docs-changed"]
    if dry_run == "true":
        expected.append("--dry-run")
    assert arguments[1:] == expected


@pytest.mark.parametrize("language", ["python", "javascript-typescript"])
def test_codeql_pr_file_coverage_is_literal_and_inherited_before_init(language: str) -> None:
    data = workflow("tests.yml")
    job = data["jobs"]["codeql"]
    assert language in job["strategy"]["matrix"]["language"]
    key = "CODEQL_ACTION_FILE_COVERAGE_ON_PRS"
    assert type(job["env"][key]) is str
    assert job["env"][key] == "true"
    initializers = [
        s for s in job["steps"] if s.get("uses", "").startswith("github/codeql-action/init@")
    ]
    analyzers = [
        s for s in job["steps"] if s.get("uses", "").startswith("github/codeql-action/analyze@")
    ]
    assert len(initializers) == len(analyzers) == 1
    assert initializers[0]["with"]["languages"] == "${{ matrix.language }}"
    for step in job["steps"]:
        effective = {**data.get("env", {}), **job["env"], **step.get("env", {})}
        assert type(effective[key]) is str
        assert effective[key] == "true"
        assert key not in step.get("run", "")
