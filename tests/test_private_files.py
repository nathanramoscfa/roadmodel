"""Private exports stay outside Git and cannot follow repository output links."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from roadmodel.cli import cli
from roadmodel.private_files import atomic_private_write, protect_export, safe_destination


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def export(root: Path, source: Path, *args: str):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(
        cli,
        ["export-kit", str(root), "--user-context", str(source), *args],
        env={"XDG_CONFIG_HOME": str(root / "config"), "ROADMODEL_USER_CONTEXT": ""},
    )


def test_export_is_private_and_ignored_before_git_add(tmp_path: Path) -> None:
    root = tmp_path.resolve() / "project"
    root.mkdir()
    assert git(root, "init").returncode == 0
    source = tmp_path / "source.md"
    source.write_text("synthetic private context")
    result = export(root, source)
    assert result.exit_code == 0, result.output
    output = root / "planning/user-context.md"
    assert output.read_bytes() == source.read_bytes()
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert git(root, "check-ignore", "planning/user-context.md").returncode == 0
    assert git(root, "add", ".").returncode == 0
    assert "user-context.md" not in git(root, "ls-files").stdout
    assert "model-selector.txt" in git(root, "ls-files").stdout


def test_non_git_export_survives_future_git_init(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    target = protect_export(root, Path("nested/plan/user-context.md"))
    atomic_private_write(target, b"private")
    assert git(root, "init").returncode == 0
    for name in ("user-context.md", ".user-context.md.roadmodel-probe.tmp"):
        assert git(root, "check-ignore", "nested/plan/" + name).returncode == 0


@pytest.mark.parametrize("force", [False, True])
def test_tracked_output_refused_before_any_export(tmp_path: Path, force: bool) -> None:
    root = tmp_path.resolve()
    git(root, "init")
    out = root / "planning/user-context.md"
    out.parent.mkdir()
    out.write_text("public old content")
    assert git(root, "add", ".").returncode == 0
    source = root / "source.md"
    source.write_text("synthetic private context")
    result = export(root, source, *(["--force"] if force else []))
    assert result.exit_code != 0
    assert "tracked" in result.output
    assert out.read_text() == "public old content"
    assert not (out.parent / "model-selector.txt").exists()


def test_higher_priority_ignore_negation_refuses_copy(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    git(root, "init")
    (root / ".gitignore").write_text("!planning/user-context.md\n")
    with pytest.raises(ValueError, match="ignore rules"):
        protect_export(root, Path("planning/user-context.md"))
    assert not (root / "planning/user-context.md").exists()


@pytest.mark.parametrize("dest", ["../outside", "/outside", "nested/../../outside"])
def test_escaping_export_destination_refused(tmp_path: Path, dest: str) -> None:
    result = export(tmp_path, tmp_path / "missing", "--dest", dest)
    assert result.exit_code != 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX link/permission cases")
@pytest.mark.parametrize("leaf", ["user-context.md", "model-selector.txt", "templates"])
def test_repository_links_cannot_redirect_export(tmp_path: Path, leaf: str) -> None:
    root = tmp_path.resolve() / "project"
    root.mkdir()
    planning = root / "planning"
    planning.mkdir()
    outside = tmp_path / "outside"
    if leaf == "templates":
        outside.mkdir()
        sentinel = outside / "project-roadmap-template.md"
    else:
        sentinel = outside
    sentinel.write_text("unchanged")
    (planning / leaf).symlink_to(outside, target_is_directory=leaf == "templates")
    result = export(root, tmp_path / "missing", "--force")
    assert result.exit_code != 0
    assert sentinel.read_text() == "unchanged"
    assert len(list(planning.iterdir())) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX hardlinks and modes")
def test_atomic_replacement_detaches_hardlink_and_repairs_kept_mode(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    out = root / "planning/user-context.md"
    out.parent.mkdir()
    original = root / "original"
    original.write_text("keep curated context")
    original.chmod(0o644)
    os.link(original, out)
    result = export(root, root / "missing", "--force")
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == original.read_bytes()
    assert out.stat().st_ino != original.stat().st_ino
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert stat.S_IMODE(original.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink capability")
def test_canonical_source_link_is_supported(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    source = root / "canonical.md"
    source.write_text("synthetic private source")
    link = root / "source-link.md"
    link.symlink_to(source)
    result = export(root, link)
    assert result.exit_code == 0, result.output
    assert (root / "planning/user-context.md").read_bytes() == source.read_bytes()


def test_staging_failure_preserves_original_and_cleans_temp(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path.resolve() / "private"
    out.write_bytes(b"original")

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="synthetic"):
        atomic_private_write(out, b"replacement")
    assert out.read_bytes() == b"original"
    assert list(out.parent.iterdir()) == [out]


def test_git_metacharacters_and_linked_worktree(tmp_path: Path) -> None:
    root = tmp_path.resolve() / "repo"
    root.mkdir()
    git(root, "init")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "fixture",
    )
    worktree = tmp_path.resolve() / "worktree"
    assert git(root, "worktree", "add", "-b", "fixture", str(worktree)).returncode == 0
    relative = Path("nested [kit] !/user-context.md")
    out = protect_export(worktree, relative)
    atomic_private_write(out, b"private")
    assert git(worktree, "check-ignore", relative.as_posix()).returncode == 0
    assert git(worktree, "add", ".").returncode == 0
    assert not git(worktree, "ls-files").stdout.strip()


@pytest.mark.skipif(os.name != "posix", reason="directory-descriptor race protection")
def test_parent_swap_does_not_redirect_atomic_write(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path.resolve()
    parent, moved, outside = (root / name for name in ("parent", "moved", "outside"))
    parent.mkdir()
    outside.mkdir()
    sentinel = outside / "context"
    sentinel.write_bytes(b"untouched")
    original_open = os.open

    def swap(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if flags & os.O_EXCL:
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap)
    atomic_private_write(parent / "context", b"private")
    assert sentinel.read_bytes() == b"untouched"
    assert (moved / "context").read_bytes() == b"private"


def test_controls_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="control"):
        safe_destination(tmp_path, Path("bad\npath"))


def test_private_append_preserves_handover_and_refuses_links(tmp_path: Path) -> None:
    from roadmodel.private_files import open_private_append, private_directory

    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o755)
    private_directory(root)
    log = root / "update.log"
    log.write_text("before\n")
    log.chmod(0o644)
    with open_private_append(log) as parent, open_private_append(log) as child:
        parent.write("parent\n")
        parent.flush()
        child.write("child\n")
    assert log.read_text() == "before\nparent\nchild\n"
    if os.name == "posix":
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(log.stat().st_mode) == 0o600
        peer = root / "peer"
        os.link(log, peer)
        with pytest.raises(ValueError, match="hardlink"):
            open_private_append(log)


@pytest.mark.skipif(os.name != "nt", reason="native Windows path semantics")
@pytest.mark.parametrize("relative", ["C:private", "C:\\private", "\\private"])
def test_windows_drive_or_rooted_destination_refused(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="relative path"):
        safe_destination(tmp_path, Path(relative))


@pytest.mark.skipif(os.name != "posix", reason="POSIX special file")
def test_special_file_destination_refused(tmp_path: Path) -> None:
    target = tmp_path / "pipe"
    os.mkfifo(target)
    with pytest.raises(ValueError, match="regular file"):
        safe_destination(tmp_path, Path("pipe"))


def test_git_index_errors_and_alternate_index_cannot_hide_tracked_context(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    assert git(root, "init").returncode == 0
    target = root / "planning/user-context.md"
    target.parent.mkdir()
    target.write_text("original")
    assert git(root, "add", ".").returncode == 0
    monkeypatch.setenv("GIT_INDEX_FILE", str(root / "alternate-index"))
    with pytest.raises(ValueError, match="tracked"):
        protect_export(root, Path("planning/user-context.md"))
    monkeypatch.delenv("GIT_INDEX_FILE")
    (root / ".git/index").write_bytes(b"corrupt fixture")
    with pytest.raises(ValueError, match="index"):
        protect_export(root, Path("planning/user-context.md"))
    assert target.read_text() == "original"


def test_broken_repository_is_not_treated_as_non_git(tmp_path):
    (tmp_path / ".git").write_text("gitdir: missing\n")
    with pytest.raises(ValueError, match="exclusions"):
        protect_export(tmp_path, Path("planning/user-context.md"))
    assert not (tmp_path / "planning").exists()


def test_tracked_case_alias_is_refused_on_every_filesystem(tmp_path):
    root = tmp_path.resolve()
    assert git(root, "init").returncode == 0
    tracked = root / "planning/USER-CONTEXT.md"
    tracked.parent.mkdir()
    tracked.write_text("original")
    assert git(root, "add", ".").returncode == 0
    with pytest.raises(ValueError, match="tracked"):
        protect_export(root, Path("planning/user-context.md"))
    assert tracked.read_text() == "original"


@pytest.mark.parametrize("outer_git", [False, True])
def test_nested_repository_cannot_hide_private_output_from_owning_index(tmp_path, outer_git):
    root = tmp_path.resolve()
    if outer_git:
        assert git(root, "init").returncode == 0
    nested = root / "planning"
    nested.mkdir()
    assert git(nested, "init").returncode == 0
    target = nested / "user-context.md"
    target.write_text("original")
    assert git(nested, "add", ".").returncode == 0
    with pytest.raises(ValueError, match="nested repository"):
        protect_export(root, Path("planning/user-context.md"))
    assert target.read_text() == "original"
