"""Privileged merges must resolve a refresh's own data PR through GitHub."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cron_pr", ROOT / "scripts/cron_pr.py")
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
REPO = "example/project"
SHA = "a" * 40


def fixture() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    run = {
        "id": 123,
        "repository": {"full_name": REPO},
        "head_branch": "main",
        "event": "workflow_dispatch",
        "conclusion": "success",
        "path": ".github/workflows/update-codex.yml",
        "created_at": "2026-10-12T12:00:00Z",
        "updated_at": "2026-10-12T12:10:00Z",
    }
    pr = {
        "number": 42,
        "user": {"login": "roadmodel-cron-bot[bot]", "type": "Bot"},
        "base": {"ref": "main", "repo": {"full_name": REPO}, "sha": "b" * 40},
        "head": {"ref": "chore/codex-refresh-2026-10-12", "repo": {"full_name": REPO}, "sha": SHA},
        "draft": False,
        "created_at": "2026-10-12T12:05:00Z",
        "changed_files": 1,
    }
    return run, pr, [{"filename": "docs/catalog.json", "status": "modified"}]


def test_own_data_pr_returns_exact_commit() -> None:
    assert guard.validate(*fixture(), REPO) == SHA


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", "pull_request"),
        ("head_branch", "feature/example"),
        ("conclusion", "failure"),
        ("path", ".github/workflows/recommend-soak.yml"),
    ],
)
def test_run_provenance(field: str, value: str) -> None:
    run, pr, files = fixture()
    run[field] = value
    with pytest.raises(ValueError):
        guard.validate(run, pr, files, REPO)


@pytest.mark.parametrize("field", ["author", "fork", "branch", "base", "old", "draft", "sha"])
def test_pr_provenance(field: str) -> None:
    run, pr, files = fixture()
    if field == "author":
        pr["user"]["login"] = "external-contributor"
    elif field == "fork":
        pr["head"]["repo"]["full_name"] = "external/project"
    elif field == "branch":
        pr["head"]["ref"] = "feature/example"
    elif field == "base":
        pr["base"]["ref"] = "release"
    elif field == "old":
        pr["created_at"] = "2026-10-11T12:05:00Z"
    elif field == "draft":
        pr["draft"] = True
    else:
        pr["head"]["sha"] = "--help"
    with pytest.raises(ValueError):
        guard.validate(run, pr, files, REPO)


@pytest.mark.parametrize(
    "name", ["scripts/update_projects.py", ".github/workflows/tests.yml", "src/roadmodel/cli.py"]
)
def test_executable_changes_are_rejected(name: str) -> None:
    run, pr, _ = fixture()
    with pytest.raises(ValueError):
        guard.validate(run, pr, [{"filename": name}], REPO)
    with pytest.raises(ValueError):
        guard.validate(
            run, pr, [{"filename": "docs/catalog.json", "previous_filename": name}], REPO
        )


def test_partial_file_inventory_is_rejected() -> None:
    run, pr, files = fixture()
    pr["changed_files"] = 101
    with pytest.raises(ValueError):
        guard.validate(run, pr, files, REPO)


def test_shell_resolver_never_reads_log_links(tmp_path: Path) -> None:
    run, pr, files = fixture()
    payload = {"run": run, "pr": pr, "files": files}
    payload["commit"] = {"sha": SHA, "committer": {"date": pr["created_at"]}}
    payload["tree"] = {"tree": [{"path": "docs/catalog.json", "type": "blob", "mode": "100644"}]}
    data = tmp_path / "fixture.json"
    data.write_text(json.dumps(payload))
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "j=json.load(open(os.environ['TEST_GH_DATA']))\n"
        "if '--log' in sys.argv:\n"
        " print('https://github.com/example/project/pull/999'); sys.exit(0)\n"
        "p=sys.argv[-1]\n"
        "if '/actions/runs/' in p: result=j['run']\n"
        "elif '/compare/' in p: result={'files':j['files']}\n"
        "elif '/git/commits/' in p: result=j['commit']\n"
        "elif '/git/trees/' in p: result=j['tree']\n"
        "elif '/pulls?' in p: result=[j['pr']]\n"
        "else: result=j['pr']\n"
        "print(json.dumps([result]))\n"
    )
    gh.chmod(0o700)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", TEST_GH_DATA=str(data))
    env["ROADMODEL_REPO"] = REPO
    result = subprocess.run(
        [
            "bash",
            "-c",
            'HERE="$1/scripts"; . "$HERE/ops-lib.sh"; prs_from_run 123',
            "audit",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert result.stdout.strip() == "42"
    assert "999" not in result.stdout
    # API failures must never trigger a log-based fallback.
    bad = copy.deepcopy(payload)
    bad["pr"]["head"]["repo"] = None
    data.write_text(json.dumps(bad))
    result = subprocess.run(
        [
            "bash",
            "-c",
            'HERE="$1/scripts"; . "$HERE/ops-lib.sh"; prs_from_run 123',
            "audit",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_same_day_refresh_uses_commit_time() -> None:
    run, pr, files = fixture()
    pr["created_at"] = "2026-10-12T01:00:00Z"
    assert guard.validate(run, pr, files, REPO, committed_at="2026-10-12T12:04:00Z") == SHA


def test_rebase_rechecks_paths_without_requiring_original_timestamp() -> None:
    run, pr, files = fixture()
    later = "2026-10-12T12:30:00Z"
    with pytest.raises(ValueError):
        guard.validate(run, pr, files, REPO, committed_at=later)
    assert guard.validate(run, pr, files, REPO, committed_at=later, check_time=False) == SHA
    files[0]["filename"] = "scripts/update_projects.py"
    with pytest.raises(ValueError):
        guard.validate(run, pr, files, REPO, committed_at=later, check_time=False)


@pytest.mark.parametrize("mode", ["120000", "100755", "160000"])
def test_immutable_tree_rejects_non_data_modes(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    run, pr, files = fixture()
    paths: list[str] = []

    def api(repo: str, path: str) -> Any:
        assert repo == REPO
        paths.append(path)
        if path.startswith("compare/"):
            assert path == f"compare/{'b' * 40}...{SHA}"
            return {"files": files}
        if path.startswith("git/commits/"):
            return {"sha": SHA, "committer": {"date": pr["created_at"]}}
        return {"tree": [{"path": "docs/catalog.json", "type": "blob", "mode": mode}]}

    monkeypatch.setattr(guard, "api", api)
    with pytest.raises(ValueError, match="regular non-executable"):
        guard.validated_commit(run, pr, REPO)
    assert all("pulls/" not in path for path in paths)
