# tests/test_export_planning_kit.py
"""Smoke tests for scripts/export-planning-kit.sh.

The script normally fetches the kit fresh from GitHub; these tests drive it in
``--local`` mode so they never touch the network and assert the kit lands
intact in a target project directory.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "export-planning-kit.sh"

EXPECTED_FILES = [
    "model-selector.txt",
    "model-tier-cost-scale.md",
    "user-context.md",
    "HOW-TO-USE.md",
    "templates/project-roadmap-template.md",
    "templates/phase-roadmap-template.md",
]


def _run(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(target), "--local", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
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
