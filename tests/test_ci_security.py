from __future__ import annotations

import json
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
    for name in ("workflow-security", "codeql", "security-scan"):
        assert name in jobs["test"]["needs"]
        assert f"needs.{name}.result" in jobs["test"]["steps"][0]["run"]
    security = "\n".join(s.get("run", "") for s in jobs["workflow-security"]["steps"])
    assert "--require-hashes" in security and "sha256sum -c" in security
    assert "gitleaks git --redact=100" in security
    assert "check_codeql_sarif.py" in jobs["codeql"]["steps"][-1]["run"]


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


def sarif(results: list[dict[str, Any]], severity: str = "7.0") -> dict[str, Any]:
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "rules": [{"id": "rule", "properties": {"security-severity": severity}}]
                    }
                },
                "results": results,
            }
        ],
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (sarif([]), 0),
        (sarif([{"ruleId": "rule"}]), 1),
        (sarif([{"ruleIndex": 0}]), 1),
        (sarif([{"ruleId": "rule"}], "6.9"), 0),
        (sarif([{"ruleId": "rule", "level": "error"}], "1"), 1),
    ],
)
def test_codeql_gate_reads_rule_severity(
    tmp_path: Path, data: dict[str, Any], expected: int
) -> None:
    (tmp_path / "results.sarif").write_text(json.dumps(data))
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/check_codeql_sarif.py"), str(tmp_path)], capture_output=True
    )
    assert result.returncode == expected


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"version": "2.1.0", "runs": []},
        sarif([{"ruleId": "missing"}]),
        sarif([{"ruleId": "rule"}], "NaN"),
        sarif([{"ruleIndex": -1}]),
    ],
)
def test_missing_or_invalid_codeql_output_fails(tmp_path: Path, data: Any) -> None:
    if data is not None:
        (tmp_path / "results.sarif").write_text(json.dumps(data))
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/check_codeql_sarif.py"), str(tmp_path)], capture_output=True
    )
    assert result.returncode == 1


def test_codeql_empty_analysis_can_omit_rules(tmp_path: Path) -> None:
    data = sarif([])
    del data["runs"][0]["tool"]["driver"]["rules"]
    test_codeql_gate_reads_rule_severity(tmp_path, data, 0)


@pytest.mark.parametrize(
    "reference", [{"ruleId": "rule"}, {"rule": {"index": 0, "toolComponent": {"index": 0}}}]
)
def test_codeql_extension_rules_are_enforced(tmp_path: Path, reference: dict[str, Any]) -> None:
    data = sarif([reference])
    tool = data["runs"][0]["tool"]
    tool["extensions"] = [{"name": "security-pack", "rules": tool["driver"].pop("rules")}]
    test_codeql_gate_reads_rule_severity(tmp_path, data, 1)
