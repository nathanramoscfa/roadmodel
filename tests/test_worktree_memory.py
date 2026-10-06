"""Actual git worktree coverage and lossless, conflict-safe memory imports."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def memory():
    file = Path(__file__).resolve().parents[1] / "scripts/worktree_memory.py"
    spec = importlib.util.spec_from_file_location("worktree_memory_test", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(project, *args):
    return subprocess.run(
        ["git", "-C", str(project), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def setup(memory, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "commit", "--allow-empty", "-m", "Initial")
    worktree = tmp_path / "project-dev"
    git(root, "worktree", "add", "-b", "dev", str(worktree))
    home = tmp_path / "home"
    source = home / ".claude/projects" / memory._slug(worktree) / "memory"
    source.mkdir(parents=True)
    (source / "MEMORY.md").write_text("# Memory\n\n[Details](topics/old.md)\n")
    (source / "topics").mkdir()
    (source / "topics/old.md").write_text("Old detail\n" * 20000)
    return root, worktree, home, source


def archived(memory, setup):
    root, worktree, _, _ = setup
    return root / memory.ARCHIVE / memory._namespace(worktree)


def test_import_preserves_every_byte_relative_links_and_sources(memory, setup):
    root, worktree, home, source = setup
    source_before = {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    lines, ok = memory.import_worktree_memory(root, home)
    assert ok, lines
    target = archived(memory, setup)
    assert {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    } == source_before
    assert {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    } == source_before
    state = json.loads((root / memory.STATE).read_text())
    assert state["imports"][memory._namespace(worktree)]["source"] == str(source)
    assert memory.import_worktree_memory(root, home, check=True)[1]
    assert not git(root, "status", "--porcelain")


def test_source_changes_update_only_unchanged_local_files(memory, setup):
    root, _, home, source = setup
    assert memory.import_worktree_memory(root, home)[1]
    target = archived(memory, setup)
    (source / "topics/old.md").write_text("Changed by Claude")
    (source / "new.md").write_text("New Claude memory")
    assert not memory.import_worktree_memory(root, home, check=True)[1]
    assert memory.import_worktree_memory(root, home)[1]
    assert (target / "topics/old.md").read_text() == "Changed by Claude"
    assert (target / "new.md").read_text() == "New Claude memory"
    (target / "topics/old.md").write_text("Changed by Codex")
    assert memory.import_worktree_memory(root, home)[1]
    (source / "topics/old.md").write_text("New change by Claude")
    lines, ok = memory.import_worktree_memory(root, home)
    assert not ok and any("conflict preserved" in line for line in lines)
    assert (target / "topics/old.md").read_text() == "Changed by Codex"
    assert (source / "topics/old.md").read_text() == "New change by Claude"


def test_removed_source_files_and_worktrees_retain_archives(memory, setup):
    root, worktree, home, source = setup
    assert memory.import_worktree_memory(root, home)[1]
    target = archived(memory, setup)
    (source / "topics/old.md").unlink()
    assert memory.import_worktree_memory(root, home)[1]
    assert (target / "topics/old.md").exists()
    git(root, "worktree", "remove", str(worktree))
    assert memory.import_worktree_memory(root, home)[1]
    assert (target / "MEMORY.md").exists()
    assert memory._namespace(worktree) in (root / memory.ARCHIVE / "INDEX.md").read_text()


def test_unrelated_sibling_memory_is_never_imported(memory, setup):
    root, _, home, _ = setup
    sibling = root.parent / "project-unrelated"
    sibling.mkdir()
    git(sibling, "init")
    source = home / ".claude/projects" / memory._slug(sibling) / "memory"
    source.mkdir(parents=True)
    (source / "MEMORY.md").write_text("Unrelated")
    assert memory.import_worktree_memory(root, home)[1]
    assert len(json.loads((root / memory.STATE).read_text())["imports"]) == 1


@pytest.mark.parametrize("mode", ["check", "dry_run"])
def test_readonly_modes_do_not_write(memory, setup, mode):
    root, _, home, source = setup
    before = {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    _, ok = memory.import_worktree_memory(root, home, **{mode: True})
    assert ok == (mode == "dry_run")
    assert before == {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    assert not (root / memory.STATE).exists()
    assert source.is_dir()


def test_existing_conflicting_copy_and_tracked_paths_are_refused(memory, setup):
    root, _, home, _ = setup
    target = archived(memory, setup)
    target.mkdir(parents=True)
    (target / "MEMORY.md").write_text("Existing independent memory")
    assert not memory.import_worktree_memory(root, home)[1]
    assert (target / "MEMORY.md").read_text() == "Existing independent memory"
    git(root, "add", "-f", memory.STATE)
    lines, ok = memory.import_worktree_memory(root, home)
    assert not ok and "tracked" in lines[-1]


def test_redirected_destination_does_not_write_external_files(memory, setup, tmp_path):
    root, _, home, _ = setup
    external = tmp_path / "external"
    external.mkdir()
    (root / ".roadmodel").symlink_to(external, target_is_directory=True)
    lines, ok = memory.import_worktree_memory(root, home)
    assert not ok and "redirects" in lines[-1]
    assert not list(external.iterdir())


def test_windows_project_slug_replaces_drive_and_separators(memory):
    assert memory._slug(Path(r"E:\Code\Python\some_project")) == "E--Code-Python-some-project"


def test_only_root_requires_git_trust(memory, setup, monkeypatch):
    root, _, home, _ = setup
    real_git = memory._git

    def restricted_git(project, *args):
        if project != root:
            raise ValueError("dubious ownership: sandbox only trusts active root")
        return real_git(project, *args)

    monkeypatch.setattr(memory, "_git", restricted_git)
    lines, ok = memory.import_worktree_memory(root, home)
    assert ok, lines
    assert (archived(memory, setup) / "MEMORY.md").exists()


def test_worktree_replaced_by_unrelated_repo_is_refused(memory, setup):
    root, worktree, home, _ = setup
    unrelated = root.parent / "unrelated"
    unrelated.mkdir()
    git(unrelated, "init")
    (worktree / ".git").write_text(f"gitdir: {unrelated / '.git'}\n")
    (unrelated / ".git/commondir").write_text(".\n")
    lines, ok = memory.import_worktree_memory(root, home)
    assert not ok and "another repo" in lines[-1]
    assert not (root / memory.STATE).exists()


def test_configured_custom_store_accepts_archives_and_preserves_private_state(
    memory, setup, tmp_path
):
    root, _, home, source = setup
    custom = tmp_path / "custom-memory"
    custom.mkdir()
    (root / ".roadmodel").mkdir()
    try:
        (root / ".roadmodel/memory").symlink_to(custom, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    (root / ".claude").mkdir()
    (root / ".claude/settings.local.json").write_text(
        json.dumps({"autoMemoryDirectory": str(custom)})
    )
    source_before = (source / "topics/old.md").read_bytes()
    lines, ok = memory.import_worktree_memory(root, home)
    assert ok, lines
    target = archived(memory, setup)
    assert target.resolve().is_relative_to(custom)
    assert (target / "topics/old.md").read_bytes() == source_before
    assert (source / "topics/old.md").read_bytes() == source_before
    assert (root / memory.STATE).is_file()
    assert not (custom / "worktree-imports.json").exists()
    assert memory.import_worktree_memory(root, home, check=True)[1]


def test_custom_store_still_rejects_redirects_inside_an_archive(memory, setup, tmp_path):
    root, _, home, _ = setup
    custom = tmp_path / "custom-memory"
    custom.mkdir()
    (root / ".roadmodel").mkdir()
    try:
        (root / ".roadmodel/memory").symlink_to(custom, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    (root / ".claude").mkdir()
    (root / ".claude/settings.local.json").write_text(
        json.dumps({"autoMemoryDirectory": str(custom)})
    )
    external = tmp_path / "unrelated"
    external.mkdir()
    (custom / "worktrees").symlink_to(external, target_is_directory=True)
    lines, ok = memory.import_worktree_memory(root, home)
    assert not ok and "redirects" in lines[-1]
    assert not list(external.iterdir())


def test_unconfigured_memory_redirect_is_rejected(memory, setup, tmp_path):
    root, _, home, _ = setup
    external = tmp_path / "external-memory"
    external.mkdir()
    (root / ".roadmodel").mkdir()
    try:
        (root / ".roadmodel/memory").symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    lines, ok = memory.import_worktree_memory(root, home)
    assert not ok and "configured store" in lines[-1]
    assert not list(external.iterdir())


def test_edit_made_during_scan_is_preserved_with_old_provenance(memory, setup, monkeypatch):
    root, worktree, home, source = setup
    assert memory.import_worktree_memory(root, home)[1]
    target = archived(memory, setup) / "MEMORY.md"
    state_before = json.loads((root / memory.STATE).read_text())
    old_hash = state_before["imports"][memory._namespace(worktree)]["files"]["MEMORY.md"]
    (source / "MEMORY.md").write_text("New source index\n")
    original_read = Path.read_bytes
    edited = False

    def interleaved_read(path):
        nonlocal edited
        content = original_read(path)
        # The index write has been queued by the time the next source file
        # is read. A concurrent agent updates that destination during the scan.
        if path == source / "topics/old.md" and not edited:
            edited = True
            target.write_text("New local index from another agent\n")
        return content

    monkeypatch.setattr(Path, "read_bytes", interleaved_read)
    lines, ok = memory.import_worktree_memory(root, home)
    assert edited and not ok
    assert any("concurrent edit preserved" in line for line in lines)
    assert target.read_text() == "New local index from another agent\n"
    state_after = json.loads((root / memory.STATE).read_text())
    assert state_after["imports"][memory._namespace(worktree)]["files"]["MEMORY.md"] == old_hash
    # The differing copies are still a conflict on the next check, rather
    # than being mistaken for a deliberately retained local-only change.
    assert not memory.import_worktree_memory(root, home, check=True)[1]
