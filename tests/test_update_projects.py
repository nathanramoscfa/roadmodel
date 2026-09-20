# tests/test_update_projects.py
"""Guards on scripts/update_projects.py — the one-run "upgrade roadmodel in
every project" updater behind /roadmodel-update.

The script is stdlib-only and fetched from the repo at run time, so these
tests import it from its path. Environment detection must never guess:
a project with no detectable env is reported, not updated into `base`.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "update_projects.py"
COMMAND = ROOT / "docs" / "claude-commands" / "roadmodel-update.md"


@pytest.fixture(scope="module")
def up() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_projects", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["update_projects"] = mod  # dataclasses + postponed annotations need this
    spec.loader.exec_module(mod)
    return mod


def _fake_venv(project: Path, name: str) -> Path:
    """A venv-shaped directory with a python launcher where the script looks."""
    prefix = project / name
    launcher = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    launcher.parent.mkdir(parents=True)
    launcher.write_text("")
    return prefix


# --------------------------------------------------------------------------
# Registry parsing
# --------------------------------------------------------------------------


def test_registry_line_forms(up: ModuleType) -> None:
    assert up.parse_registry_line("") is None
    assert up.parse_registry_line("   # just a comment") is None
    plain = up.parse_registry_line("/srv/app  # trailing comment")
    assert plain.path == Path("/srv/app") and plain.override is None
    conda = up.parse_registry_line("/srv/app | conda:app-env")
    assert conda.override == "conda:app-env"
    venv = up.parse_registry_line("C:\\dev\\app | venv:.venv")
    assert venv.override == "venv:.venv"
    with pytest.raises(ValueError):
        up.parse_registry_line("/srv/app | pipenv:whatever")


def test_add_to_registry_dedupes_and_requires_dirs(up: ModuleType, tmp_path: Path) -> None:
    reg = tmp_path / "cfg" / "projects.txt"
    a = tmp_path / "a"
    a.mkdir()
    assert up.add_to_registry(reg, [str(a)]) == [a.resolve()]
    assert up.add_to_registry(reg, [str(a)]) == []  # already registered
    assert [e.path for e in up.read_registry(reg)] == [a.resolve()]
    with pytest.raises(SystemExit):
        up.add_to_registry(reg, [str(tmp_path / "missing")])


# --------------------------------------------------------------------------
# Environment detection — never guess
# --------------------------------------------------------------------------


def test_detects_venv_dir(up: ModuleType, tmp_path: Path) -> None:
    prefix = _fake_venv(tmp_path, ".venv")
    env, note = up.resolve_env(up.Entry(tmp_path))
    assert env.kind == "venv" and env.prefix == prefix and "venv dir" in note


def test_venv_override_wins_and_must_exist(up: ModuleType, tmp_path: Path) -> None:
    _fake_venv(tmp_path, ".venv")
    other = _fake_venv(tmp_path, "tools-env")
    env, note = up.resolve_env(up.Entry(tmp_path, override="venv:tools-env"))
    assert env.prefix == other and note == "override"
    env, note = up.resolve_env(up.Entry(tmp_path, override="venv:nope"))
    assert env is None and "has no python" in note


def test_conda_by_environment_yml_and_folder_name(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envs_root = tmp_path / "conda-envs"
    named = _fake_venv(envs_root, "proj-env")
    folder_named = _fake_venv(envs_root, "myproj")
    monkeypatch.setattr(up, "_CONDA_ENVS", {"proj-env": named, "myproj": folder_named})

    project = tmp_path / "myproj"
    project.mkdir()
    env, note = up.resolve_env(up.Entry(project))
    assert env.kind == "conda" and env.label == "myproj" and "named like the folder" in note

    (project / "environment.yml").write_text("name: proj-env\ndependencies:\n  - python\n")
    env, note = up.resolve_env(up.Entry(project))
    assert env.label == "proj-env" and "environment.yml" in note

    (project / "environment.yml").write_text("name: not-created\n")
    env, note = up.resolve_env(up.Entry(project))
    assert env is None and "not created" in note


def test_no_env_is_reported_not_guessed(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _fake_venv(tmp_path / "conda", "base")
    monkeypatch.setattr(up, "_CONDA_ENVS", {"base": base})
    project = tmp_path / "bare"
    project.mkdir()
    env, note = up.resolve_env(up.Entry(project))
    assert env is None and "no env found" in note
    env, note = up.resolve_env(up.Entry(tmp_path / "does-not-exist"))
    assert env is None and "does not exist" in note


# --------------------------------------------------------------------------
# CLI — dry run end to end
# --------------------------------------------------------------------------


def test_dry_run_cli_plans_without_touching_anything(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _fake_venv(alpha, ".venv")
    delta = tmp_path / "delta"
    delta.mkdir()
    reg = tmp_path / "projects.txt"
    reg.write_text(f"{alpha}\n{delta}\n")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-file", str(reg), "--dry-run", "--no-commands"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "CONDA_EXE": str(tmp_path / "no-conda")},  # no conda lookups
    )
    assert result.returncode == 1, result.stdout + result.stderr  # delta has no env
    assert "[alpha] venv:.venv" in result.stdout
    assert "[delta] no env found" in result.stdout
    assert "alpha" in result.stdout and "FAILED" in result.stdout
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after  # dry run wrote nothing


def test_empty_registry_explains_how_to_add(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--projects-file",
            str(tmp_path / "none.txt"),
            "--no-commands",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "--add" in result.stderr


# --------------------------------------------------------------------------
# The command that drives it
# --------------------------------------------------------------------------


def test_roadmodel_update_command_points_at_the_script(up: ModuleType) -> None:
    text = COMMAND.read_text()
    assert f"{up.REPO_RAW}/scripts/update_projects.py" in text
    assert "projects.txt" in text
    assert "--add" in text and "--dry-run" in text
    assert "no env found" in text
    # The updater refreshes itself and its siblings; the tuple must name them all.
    for name in up.COMMANDS:
        assert (ROOT / "docs" / "claude-commands" / f"{name}.md").exists(), name
