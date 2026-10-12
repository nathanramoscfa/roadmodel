"""Native ACL and handle tests; also run against the extracted stdlib helper."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows security descriptors")


@pytest.fixture
def files() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "src/roadmodel/private_files.py"
    spec = importlib.util.spec_from_file_location("private_files_native", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def broad_acl(files, path, *, directory=False):
    """A synthetic Everyone grant, applied only inside pytest's private fixture."""
    api = files._windows()
    c = api.c
    descriptor = c.c_void_p()
    flags = "OICI" if directory else ""
    text = f"D:P(A;{flags};FA;;;{api.user()})(A;{flags};FA;;;WD)"
    api.check(api.convert_sd(text, 1, c.byref(descriptor), None))
    try:
        present, defaulted, dacl = api.w.BOOL(), api.w.BOOL(), c.c_void_p()
        api.check(api.get_dacl(descriptor, c.byref(present), c.byref(dacl), c.byref(defaulted)))
        with api.parent(path) as parent:
            handle = api.open(parent, path.name, 0x40000, 1, directory=directory)
            try:
                api.check(api.set_security(handle, 1, 0x80000004, None, None, dacl, None) == 0)
            finally:
                api.close(handle)
    finally:
        api.free(descriptor)


def verify_path(files, path, *, directory=False):
    api = files._windows()
    with api.parent(path) as parent, api.descriptor(directory) as (_, principals):
        handle = api.open(parent, path.name, 0, 1, directory=directory)
        try:
            api.verify(handle, principals, directory=directory)
        finally:
            api.close(handle)


def test_protected_acl_precedes_first_byte_and_preserves_broad_parent(files, tmp_path, monkeypatch):
    import msvcrt

    parent = tmp_path / "ordinary"
    parent.mkdir()
    broad_acl(files, parent, directory=True)
    output = parent / "context"
    real_write = os.write
    checked = []

    def inspect(fd, data):
        api = files._windows()
        with api.descriptor() as (_, principals):
            api.verify(msvcrt.get_osfhandle(fd), principals)
        checked.append(True)
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", inspect)
    files.atomic_private_write(output, b"synthetic private bytes")
    assert checked
    assert output.read_bytes() == b"synthetic private bytes"
    verify_path(files, output)
    with pytest.raises(files.UnsafePrivatePath):
        verify_path(files, parent, directory=True)  # public parent unchanged


def test_replacement_detaches_broad_hardlink_and_handles_non_bmp_name(files, tmp_path):
    target = tmp_path / "private-\U0001f642.txt"
    peer = tmp_path / "peer"
    target.write_bytes(b"old")
    broad_acl(files, target)
    os.link(target, peer)
    files.atomic_private_write(target, b"new")
    assert peer.read_bytes() == b"old"
    assert files.read_private_output(target) == b"new"
    assert target.stat().st_nlink == 1
    verify_path(files, target)
    assert not list(tmp_path.glob(".*.roadmodel-*.tmp"))


def test_private_directory_repairs_only_selected_owned_directory(files, tmp_path):
    outer = tmp_path / "ordinary"
    outer.mkdir()
    broad_acl(files, outer, directory=True)
    private = outer / "private"
    private.mkdir()
    files.private_directory(private)
    verify_path(files, private, directory=True)
    with pytest.raises(files.UnsafePrivatePath):
        verify_path(files, outer, directory=True)


def test_new_append_handles_share_inode_without_overwriting(files, tmp_path):
    path = tmp_path / "new.log"
    with files.open_private_append(path) as a, files.open_private_append(path) as b:
        assert not os.get_inheritable(a.fileno())
        for index in range(10):
            a.write(f"a{index}\n")
            a.flush()
            b.write(f"b{index}\n")
            b.flush()
    assert path.read_text() == "".join(f"a{i}\nb{i}\n" for i in range(10))
    verify_path(files, path)


def test_broad_legacy_log_is_refused_even_without_an_existing_reader(files, tmp_path):
    path = tmp_path / "legacy.log"
    path.write_bytes(b"unchanged")
    broad_acl(files, path)
    for hold in (False, True):
        reader = path.open("rb") if hold else None
        try:
            with pytest.raises(files.UnsafePrivatePath):
                files.open_private_append(path)
        finally:
            if reader:
                reader.close()
    assert path.read_bytes() == b"unchanged"


def test_append_refuses_hardlink_without_affecting_peer(files, tmp_path):
    path = tmp_path / "log"
    files.atomic_private_write(path, b"old")
    peer = tmp_path / "peer"
    os.link(path, peer)
    with pytest.raises(files.UnsafePrivatePath):
        files.open_private_append(path)
    assert peer.read_bytes() == b"old"


@pytest.mark.parametrize(
    "name",
    [
        "secret:stream",
        "NUL",
        "con.txt",
        "COM1.txt",
        "LPT\u00b2",
        "tail.",
        "tail ",
        "bad\nname",
        "..\\escape",
    ],
)
def test_windows_aliases_are_rejected_before_private_bytes(files, tmp_path, name):
    with pytest.raises(files.UnsafePrivatePath):
        files.atomic_private_write(tmp_path / name, b"private")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "method",
    ["atomic_private_write", "read_private_output", "open_private_append", "private_directory"],
)
def test_ancestor_junction_cannot_redirect_private_access(files, tmp_path, method):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "context"
    sentinel.write_bytes(b"unchanged")
    junction = tmp_path / "junction"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, timeout=30
    )
    assert made.returncode == 0
    try:
        args = (
            (junction / "context", b"private")
            if method == "atomic_private_write"
            else (junction / "context",)
        )
        with pytest.raises(files.UnsafePrivatePath):
            getattr(files, method)(*args)
        assert sentinel.read_bytes() == b"unchanged"
    finally:
        junction.rmdir()


def test_held_ancestor_cannot_be_renamed_mid_write(files, tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    api = files._windows()
    original = api.open
    blocked = []

    def swap(parent_handle, name, *args, **kwargs):
        handle = original(parent_handle, name, *args, **kwargs)
        if name == "parent":
            with pytest.raises(OSError):
                parent.rename(tmp_path / "moved")
            blocked.append(True)
        return handle

    monkeypatch.setattr(api, "open", swap)
    monkeypatch.setattr(files, "_windows", lambda: api)
    files.atomic_private_write(parent / "context", b"private")
    assert blocked and (parent / "context").read_bytes() == b"private"


def test_no_acl_volume_fails_before_creating_components(files, tmp_path, monkeypatch):
    api = files._windows()

    def no_acls(*args):
        args[5]._obj.value = 0
        return True

    monkeypatch.setattr(api, "volume_info", no_acls)
    monkeypatch.setattr(files, "_windows", lambda: api)
    with pytest.raises(files.UnsafePrivatePath):
        files.atomic_private_write(tmp_path / "new" / "context", b"private")
    assert not list(tmp_path.iterdir())


def test_failed_write_removes_only_its_own_staging_handle(files, tmp_path, monkeypatch):
    target = tmp_path / "context"
    target.write_bytes(b"old")

    def fail(*args):
        raise OSError("fixture write failure")

    monkeypatch.setattr(os, "write", fail)
    with pytest.raises(OSError, match="fixture"):
        files.atomic_private_write(target, b"private")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]


def test_actual_staging_name_is_git_excluded_before_publication(files, tmp_path, monkeypatch):
    assert subprocess.run(["git", "init", str(tmp_path)], capture_output=True).returncode == 0
    target = files.protect_export(tmp_path, Path("planning/context.md"))
    api = files._windows()
    rename = api.rename
    checked = []

    def check_staging(handle, parent, name, **kwargs):
        staging = list(target.parent.glob(".context.md.roadmodel-*.tmp"))
        assert len(staging) == 1
        relative = str(staging[0].relative_to(tmp_path))
        assert (
            subprocess.run(
                ["git", "-C", str(tmp_path), "check-ignore", relative], capture_output=True
            ).returncode
            == 0
        )
        assert (
            subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True).returncode
            == 0
        )
        tracked = subprocess.run(
            ["git", "-C", str(tmp_path), "ls-files"], capture_output=True, text=True
        )
        assert ".tmp" not in tracked.stdout and "context.md" not in tracked.stdout
        checked.append(True)
        rename(handle, parent, name, **kwargs)

    monkeypatch.setattr(api, "rename", check_staging)
    monkeypatch.setattr(files, "_windows", lambda: api)
    files.atomic_private_write(target, b"private")
    assert checked and target.read_bytes() == b"private"


def test_similarly_named_regular_windows_files_remain_supported(files, tmp_path):
    for name in ("COM12", "LPT23", "space in name"):
        path = tmp_path / name
        files.atomic_private_write(path, b"private")
        assert path.read_bytes() == b"private"


def test_exclusive_publication_never_overwrites_existing_backup(files, tmp_path):
    path = tmp_path / "backup"
    files.atomic_private_write(path, b"old", replace=False)
    with pytest.raises(files.UnsafePrivatePath):
        files.atomic_private_write(path, b"new", replace=False)
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


def test_private_update_handles_share_inode_and_preserve_seeks(files, tmp_path):
    path = tmp_path / "update.lock"
    with files.open_private_update(path) as a, files.open_private_update(path) as b:
        a.write(b"\0owner")
        a.flush()
        b.seek(1)
        assert b.read() == b"owner"
        b.seek(1)
        b.write(b"child")
        b.flush()
        a.seek(1)
        assert a.read() == b"child"
    verify_path(files, path)


def test_private_update_refuses_broad_legacy_lock(files, tmp_path):
    path = tmp_path / "update.lock"
    path.write_bytes(b"old")
    broad_acl(files, path)
    with pytest.raises(files.UnsafePrivatePath):
        files.open_private_update(path)
    assert path.read_bytes() == b"old"


def test_explicit_acl_repair_preserves_bytes_and_requires_closed_readers(files, tmp_path):
    path = tmp_path / "old-memory.md"
    path.write_bytes(b"preserve memory")
    broad_acl(files, path)
    before = path.stat()
    with path.open("rb"):
        with pytest.raises(files.UnsafePrivatePath):
            files.private_file_permissions(path)
    files.private_file_permissions(path)
    assert path.read_bytes() == b"preserve memory"
    assert path.stat().st_ino == before.st_ino
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    verify_path(files, path)
