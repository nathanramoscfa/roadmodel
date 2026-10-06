"""Behavioral checks for live shared memory, migration, and private handoffs."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def context() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/agent_context.py"
    spec = importlib.util.spec_from_file_location("test_agent_context_impl", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    for args in (
        ["init"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.invalid"],
        ["commit", "--allow-empty", "-m", "Initial"],
    ):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    return path


def seed(context: ModuleType, project: Path, home: Path) -> Path:
    memory = context._legacy_memory(project, home)
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("# Memory\n\n- [Architecture](old.md)\n")
    (memory / "old.md").write_text("Important old detail\n" * 20000)
    (memory / "recent.md").write_text("Recent decision\n")
    return memory


def test_full_memory_migrates_once_and_is_bidirectionally_live(context, project, tmp_path):
    home = tmp_path / "home"
    legacy = seed(context, project, home)
    original = {p.name: p.read_bytes() for p in legacy.iterdir()}
    report, ok = context.sync_project(project, home)
    assert ok, report
    shared = project / ".roadmodel/memory"
    assert legacy.resolve() == shared.resolve()
    assert {p.name: p.read_bytes() for p in shared.iterdir()} == original
    assert list(legacy.parent.glob("memory.before-roadmodel-*"))
    (legacy / "from-claude.md").write_text("Live Claude fact")
    assert (shared / "from-claude.md").read_text() == "Live Claude fact"
    (shared / "from-codex.md").write_text("Live Codex fact")
    assert (legacy / "from-codex.md").read_text() == "Live Codex fact"
    assert context.sync_project(project, home)[1]
    manifest = json.loads((project / ".roadmodel/context.json").read_text())
    assert manifest["claude_memory"] == str(legacy)
    assert len(list(legacy.parent.glob("memory.before-roadmodel-*"))) == 1
    assert context.sync_project(project, home, check=True)[1]


def test_nested_memory_redirect_preserves_originals(context, project, tmp_path):
    home = tmp_path / "home"
    legacy = seed(context, project, home)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.md").write_text("Separate memory")
    context._link(legacy / "nested", outside)
    with pytest.raises(ValueError, match="symbolic link"):
        context._files(legacy)
    assert (legacy / "old.md").is_file()
    assert not (project / ".roadmodel/memory").exists()


def test_session_detects_new_memory_without_upgrader(context, project, tmp_path):
    home = tmp_path / "home"
    seed(context, project, home)
    assert context.sync_project(project, home)[1]
    (project / ".roadmodel/memory/unindexed.md").write_text("New unindexed fact")
    assert not context.sync_project(project, home, check=True)[1]
    lines, ok = context.session(project)
    assert ok, lines
    manifest = json.loads((project / ".roadmodel/context.json").read_text())
    assert "unindexed.md" in manifest["entries"]
    assert any("refreshed" in line for line in lines)
    assert context.sync_project(project, home, check=True)[1]


def test_existing_rules_settings_handoff_preserved(context, project, tmp_path):
    home = tmp_path / "home"
    (project / "AGENTS.md").write_text("# My rules\nRun real tests.\n")
    (project / "CLAUDE.md").write_text("# Claude rules\nKeep my rules.\n")
    (project / ".claude").mkdir()
    (project / ".claude/settings.local.json").write_text('{"permissions":{"allow":["Read"]}}')
    assert context.sync_project(project, home)[1]
    handoff = project / ".roadmodel/HANDOFF.md"
    handoff.write_text("My unfinished work and a decision")
    assert context.sync_project(project, home)[1]
    assert handoff.read_text() == "My unfinished work and a decision"
    assert "Run real tests." in (project / "AGENTS.md").read_text()
    assert "Keep my rules." in (project / "CLAUDE.md").read_text()
    assert "@AGENTS.md" in (project / "CLAUDE.local.md").read_text()
    assert json.loads((project / ".claude/settings.local.json").read_text())["permissions"] == {
        "allow": ["Read"]
    }


@pytest.mark.parametrize("mode", ["check", "dry_run"])
def test_readonly_modes_change_nothing(context, project, tmp_path, mode):
    home = tmp_path / "home"
    source = seed(context, project, home)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _, ok = context.sync_project(project, home, **{mode: True})
    assert ok == (mode == "dry_run")
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert not source.is_symlink()


def test_conflicting_memories_are_never_overwritten(context, project, tmp_path):
    home = tmp_path / "home"
    source = seed(context, project, home)
    target = project / ".roadmodel/memory"
    target.mkdir(parents=True)
    (target / "recent.md").write_text("Independent Codex decision")
    lines, ok = context.sync_project(project, home)
    assert not ok and "conflict" in lines[0]
    assert (target / "recent.md").read_text() == "Independent Codex decision"
    assert (source / "recent.md").read_text() == "Recent decision\n"
    assert not source.is_symlink()


def test_link_failure_restores_claude_store(context, project, tmp_path, monkeypatch):
    home = tmp_path / "home"
    source = seed(context, project, home)

    def fail(*args):
        raise OSError("junction refused")

    monkeypatch.setattr(context, "_link", fail)
    lines, ok = context.sync_project(project, home)
    assert not ok and "junction refused" in lines[0]
    assert (source / "recent.md").read_text() == "Recent decision\n"
    assert not source.is_symlink()


def test_changed_legacy_redirect_is_detected_after_repeated_sync(context, project, tmp_path):
    home = tmp_path / "home"
    source = seed(context, project, home)
    assert context.sync_project(project, home)[1]
    assert context.sync_project(project, home)[1]
    if os.name == "nt":
        source.rmdir()  # Remove the junction itself, preserving its target.
    else:
        source.unlink()
    source.mkdir()
    assert not context.session(project)[1]
    assert not context.sync_project(project, home)[1]


def test_tracked_private_context_is_refused(context, project, tmp_path):
    (project / ".agents").mkdir()
    (project / ".agents/memory.md").write_text("Private fact")
    subprocess.run(["git", "-C", str(project), "add", ".agents/memory.md"], check=True)
    lines, ok = context.sync_project(project, tmp_path / "home")
    assert not ok and "tracked" in lines[0]
    assert not (project / ".roadmodel/context.json").exists()


def test_custom_memory_directory_is_kept_in_place(context, project, tmp_path):
    home = tmp_path / "home"
    memory = tmp_path / "custom-memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("Shared by several projects")
    (project / ".claude").mkdir()
    (project / ".claude/settings.local.json").write_text(
        json.dumps({"autoMemoryDirectory": str(memory)})
    )
    lines, ok = context.sync_project(project, home)
    assert ok, lines
    assert not memory.is_symlink()
    assert (project / ".roadmodel/memory").resolve() == memory
    assert context.session(project)[1]


def test_worktree_uses_original_memory_and_common_excludes(context, project, tmp_path):
    home = tmp_path / "home"
    source = seed(context, project, home)
    assert context.sync_project(project, home)[1]
    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "-C", str(project), "worktree", "add", "-b", "topic", str(worktree)],
        check=True,
        capture_output=True,
    )
    lines, ok = context.sync_project(worktree, home)
    assert ok, lines
    assert (worktree / ".roadmodel/memory").resolve() == source.resolve()
    assert context.session(worktree)[1]
    ignored = subprocess.run(
        ["git", "-C", str(worktree), "check-ignore", ".roadmodel/context.json"], capture_output=True
    )
    assert ignored.returncode == 0


def test_private_adapters_leave_project_worktree_clean(context, project, tmp_path):
    assert context.sync_project(project, tmp_path / "home")[1]
    status = subprocess.check_output(["git", "-C", str(project), "status", "--short"], text=True)
    assert status == ""


def test_overlap_rejected(context, tmp_path):
    source = tmp_path / "memory"
    source.mkdir()
    (source / "fact.md").write_text("keep")
    with pytest.raises(ValueError, match="overlap"):
        context._adopt(source, source / "child")
    assert (source / "fact.md").read_text() == "keep"


def test_installed_helper_runs_without_roadmodel_package(context, project, tmp_path):
    assert context.sync_project(project, tmp_path / "home")[1]
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(project / ".roadmodel/context.py"),
            "--project",
            str(project),
            "--session",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Shared context verified" in result.stdout


def test_check_catches_missing_worktree_alias_and_setting(context, project, tmp_path):
    home = tmp_path / "home"
    assert context.sync_project(project, home)[1]
    worktree = tmp_path / "other"
    subprocess.run(
        ["git", "-C", str(project), "worktree", "add", "-b", "other", str(worktree)],
        check=True,
        capture_output=True,
    )
    assert context.sync_project(worktree, home)[1]
    (worktree / ".claude/settings.local.json").write_text("{}")
    assert not context.sync_project(worktree, home, check=True)[1]
    assert context.sync_project(worktree, home)[1]
    alias = worktree / ".roadmodel/memory"
    if os.name == "nt":
        alias.rmdir()
    else:
        alias.unlink()
    assert not context.sync_project(worktree, home, check=True)[1]


def test_check_catches_missing_worktree_helper(context, project, tmp_path):
    home = tmp_path / "home"
    assert context.sync_project(project, home)[1]
    (project / ".roadmodel/worktree_memory.py").unlink()
    assert not context.sync_project(project, home, check=True)[1]
