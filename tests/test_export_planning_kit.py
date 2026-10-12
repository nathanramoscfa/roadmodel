# tests/test_export_planning_kit.py
"""Smoke tests for scripts/export-planning-kit.sh.

The script normally fetches the kit fresh from GitHub; these tests drive it in
``--local`` mode so they never touch the network and assert the kit lands
intact in a target project directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "export-planning-kit.sh"

EXPECTED_FILES = [
    "model-selector.txt",
    "model-tier-cost-scale.md",
    # The display contract travels with the selector: `roadmodel export-kit`
    # ships it, so the shell exporter must too or a shell-exported kit has the
    # algorithm without the rules for rendering its platform-conditional
    # setting fields.
    "settings-display.md",
    "user-context.md",
    "HOW-TO-USE.md",
    "templates/project-roadmap-template.md",
    "templates/phase-roadmap-template.md",
    # Fill-in paste-prompts: the operator copies one, fills the placeholders,
    # and submits — instead of retyping the ask each phase.
    "prompts/project-roadmap.md",
    "prompts/phase-roadmap.md",
]


def _run(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(target), "--local", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "ROADMODEL_PYTHON": sys.executable},
    )


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "export-planning-kit.sh must be executable"


def test_local_export_lands_every_file(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    uc = tmp_path / "user-context.md"
    uc.write_text("# User Context\n\ntest\n", encoding="utf-8")

    result = _run(target, "--user-context", str(uc))
    assert result.returncode == 0, result.stderr

    planning = target / "planning"
    for rel in EXPECTED_FILES:
        assert (planning / rel).is_file(), f"missing exported file: {rel}"

    # The selector must arrive whole (the script's own marker guard).
    assert "<model-selector>" in (planning / "model-selector.txt").read_text(encoding="utf-8")
    # The operator's real user-context is copied verbatim.
    assert (planning / "user-context.md").read_text(encoding="utf-8") == uc.read_text(
        encoding="utf-8"
    )
    # The how-to carries the "you are the engine" rule that keeps it $0-marginal.
    assert "you are the engine" in (planning / "HOW-TO-USE.md").read_text(encoding="utf-8").lower()


def test_missing_user_context_writes_placeholder_not_failure(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    missing = tmp_path / "nope" / "user-context.md"

    result = _run(target, "--user-context", str(missing))
    assert result.returncode == 0, result.stderr

    placeholder = (target / "planning" / "user-context.md").read_text(encoding="utf-8")
    assert "PLACEHOLDER" in placeholder


def test_custom_dest_subdir(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    uc = tmp_path / "uc.md"
    uc.write_text("# uc\n", encoding="utf-8")

    result = _run(target, "--dest", ".roadmodel", "--user-context", str(uc))
    assert result.returncode == 0, result.stderr
    assert (target / ".roadmodel" / "model-selector.txt").is_file()
    assert not (target / "planning").exists()


def test_missing_target_dir_errors(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does-not-exist"
    result = subprocess.run(
        ["bash", str(SCRIPT), str(nonexistent), "--local"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "does not exist" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_help_flag_exits_zero() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "planning kit" in result.stdout.lower()


@pytest.mark.parametrize("dest", ["../outside", "/outside", "nested/../../outside"])
def test_shell_rejects_escape_before_writing(tmp_path: Path, dest: str) -> None:
    result = _run(tmp_path, "--dest", dest)
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())


def test_shell_keeps_curated_context_and_protects_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    source = tmp_path / "source context.md"
    source.write_text("SYNTHETIC_PRIVATE_CONTEXT")
    assert _run(tmp_path, "--user-context", str(source)).returncode == 0
    source.unlink()
    assert _run(tmp_path, "--user-context", str(source), "--force").returncode == 0
    output = tmp_path / "planning/user-context.md"
    assert output.read_text() == "SYNTHETIC_PRIVATE_CONTEXT"
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    tracked = subprocess.check_output(["git", "-C", str(tmp_path), "ls-files"], text=True)
    assert "user-context.md" not in tracked
    assert "model-selector.txt" in tracked


def test_shell_tracked_context_and_links_fail_before_public_writes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    private = tmp_path / "planning/user-context.md"
    private.parent.mkdir()
    private.write_text("keep")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert _run(tmp_path, "--force").returncode != 0
    assert private.read_text() == "keep"
    assert not (private.parent / "model-selector.txt").exists()


def test_moving_ref_is_rejected_without_bootstrap(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path), "--ref", "main"],
        env={**os.environ, "ROADMODEL_PYTHON": "must-not-run"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2 and "--ref is retired" in result.stderr


def test_released_shell_isolates_cwd_and_pythonpath(tmp_path: Path) -> None:
    # The wrapper's version probe must not load a project-local namesake.
    # A sitecustomize canary catches even pre-import interpreter startup.
    marker = tmp_path / "executed"
    code = "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('ran')"
    (tmp_path / "sitecustomize.py").write_text(code)
    fake = tmp_path / "roadmodel"
    fake.mkdir()
    (fake / "__init__.py").write_text(code)
    # Stop after the isolated probe instead of installing anything over the network.
    wrapper = tmp_path / "python-wrapper"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        + 'for arg in "$@"; do if [[ "$arg" == "venv" ]]; then exit 91; fi; done\n'
        + "exec "
        + __import__("shlex").quote(sys.executable)
        + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    result = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "ROADMODEL_PYTHON": str(wrapper)},
        capture_output=True,
        text=True,
    )
    # Before the security release the probe bootstraps; with it installed the
    # real exporter can succeed. Neither case runs project code.
    assert result.returncode in (0, 91)
    assert not marker.exists()
