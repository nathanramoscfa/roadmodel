"""Atomic private files and safe planning-kit destinations (stdlib only).

POSIX permissions are enforced. Windows mode bits are not an owner-only ACL.
Canonical source symlinks may be read by callers; output links are refused.
"""

from __future__ import annotations

import os
import secrets
import stat

# Fixed read-only Git invocations, without a shell.
import subprocess  # nosec B404
import unicodedata
from pathlib import Path
from typing import TextIO


class UnsafePrivatePath(ValueError):
    """An output path cannot safely hold private content."""


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _regular(info: os.stat_result) -> None:
    if _linked(info) or not stat.S_ISREG(info.st_mode):
        raise UnsafePrivatePath("Output must be a regular file, not a link or special file.")


def safe_destination(root: Path, relative: Path) -> Path:
    """Preflight without writing. The explicitly selected root is canonical."""
    if relative.anchor or relative.drive or not relative.parts or ".." in relative.parts:
        raise UnsafePrivatePath("Destination must be a relative path inside the project.")
    if any(ord(c) < 32 or ord(c) == 127 for c in str(relative)):
        raise UnsafePrivatePath("Destination contains unsupported control characters.")
    current = root.resolve(strict=True)
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if index == len(relative.parts) - 1:
            _regular(info)
        elif _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise UnsafePrivatePath("Destination parents must be directories, not links.")
    return current


def _parent_fd(path: Path) -> int:
    """Pin every parent directory; a replaced ancestor cannot redirect writes."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = path.absolute().parent
    fd = os.open(parent.anchor, flags)
    try:
        for part in parent.parts[1:]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _windows_parent(path: Path) -> None:
    parent = Path(path.anchor)
    for part in path.parent.parts[1:]:
        parent /= part
        parent.mkdir(mode=0o700, exist_ok=True)
        info = parent.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise UnsafePrivatePath("Private directory cannot be a link.")


def private_directory(path: Path) -> None:
    """Create/repair only an explicitly owned private directory, without links."""
    path = path.expanduser().absolute()
    if os.name == "posix":
        fd = _parent_fd(path / ".directory-check")
        try:
            os.fchmod(fd, 0o700)
        finally:
            os.close(fd)
    else:
        _windows_parent(path / ".directory-check")


def atomic_private_write(path: Path, data: bytes) -> None:
    """Write new bytes at 0600, replacing hardlinks without touching their peers."""
    path = path.expanduser().absolute()
    temporary = f".{path.name}.roadmodel-{secrets.token_hex(16)}.tmp"
    directory: int | None = None
    staged: str | Path = path.parent / temporary
    target: str | Path = path
    if os.name == "posix":
        directory = _parent_fd(path)
        staged, target = temporary, path.name
    else:
        _windows_parent(path)
    try:
        try:
            _regular(os.stat(target, dir_fd=directory, follow_symlinks=False))
        except FileNotFoundError:
            pass
        fd = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as handle:
            if os.name == "posix":
                os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, target, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(staged, dir_fd=directory)
        except FileNotFoundError:
            pass
        if directory is not None:
            os.close(directory)


def read_private_output(path: Path) -> bytes:
    """Read an existing output without following a substituted destination link."""
    path = path.expanduser().absolute()
    if os.name != "posix":
        _windows_parent(path)
        _regular(path.lstat())
        return path.read_bytes()
    directory = _parent_fd(path)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            _regular(os.fstat(handle.fileno()))
            return handle.read()
    finally:
        os.close(directory)


def open_private_append(path: Path) -> TextIO:
    """Append a private log without replacing an inode held by a handover child."""
    path = path.expanduser().absolute()
    directory = _parent_fd(path) if os.name == "posix" else None
    if directory is None:
        _windows_parent(path)
        if path.exists():
            _regular(path.lstat())
    target = path.name if directory is not None else path
    fd = None
    try:
        fd = os.open(
            target,
            os.O_APPEND | os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory,
        )
        info = os.fstat(fd)
        _regular(info)
        if info.st_nlink != 1:
            raise UnsafePrivatePath("Private log must not share a hardlink.")
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        stream = os.fdopen(fd, "a", encoding="utf-8")
        fd = None
        return stream
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Always inspect the selected checkout's real index and worktree. An
    # inherited alternate index must not hide an already tracked private file.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment["GIT_LITERAL_PATHSPECS"] = "1" if args[0] == "ls-files" else "0"
    # The callers choose fixed subcommands; file names are literal pathspecs.
    return subprocess.run(  # noqa: S603  # nosec B603, B607
        ["git", "-C", str(project), "-c", "core.fsmonitor=false", *args],  # noqa: S607
        capture_output=True,
        text=True,
        env=environment,
    )


def _pattern(path: str) -> str:
    return "".join("\\" + c if c in "\\ !#[]*?" else c for c in path)


def protect_export(project: Path, relative: Path) -> Path:
    """Exclude a private destination and its staging names before any bytes exist."""
    project = project.resolve(strict=True)
    output = safe_destination(project, relative)
    boundary = project
    for component in output.parent.relative_to(project).parts:
        boundary /= component
        if (boundary / ".git").exists() or (boundary / ".git").is_symlink():
            raise UnsafePrivatePath("Select the nested repository itself as the export root.")
    repo = _git(project, "rev-parse", "--show-toplevel")
    if repo.returncode == 0:
        root = Path(repo.stdout.strip()).resolve(strict=True)
        name = output.relative_to(root).as_posix()
        indexed = _git(root, "ls-files", "-z")
        if indexed.returncode:
            raise UnsafePrivatePath("Cannot verify the repository's private file index.")
        # macOS/Windows can resolve a different case or Unicode spelling to
        # the same file. Refuse those aliases even on case-sensitive hosts.
        canonical_name = unicodedata.normalize("NFC", name).casefold()
        if any(
            unicodedata.normalize("NFC", tracked).casefold() == canonical_name
            for tracked in indexed.stdout.split("\0")
        ):
            raise UnsafePrivatePath("Private destination is tracked; remove it from Git first.")
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common.returncode:
            raise UnsafePrivatePath("Cannot locate the repository's private exclusions.")
        ignore = Path(common.stdout.strip()).resolve(strict=True) / "info" / "exclude"
    else:
        if any(
            (parent / ".git").exists() or (parent / ".git").is_symlink()
            for parent in (project, *project.parents)
        ):
            raise UnsafePrivatePath("Cannot verify the repository's private exclusions.")
        # Nearest .gitignore continues protecting this copy after a future git init.
        root = output.parent
        name = output.name
        ignore = safe_destination(project, relative.parent / ".gitignore")
    try:
        _regular(ignore.lstat())
        existing = ignore.read_bytes()
    except FileNotFoundError:
        existing = b""
    path = Path(name)
    temporary = (path.parent / ("." + path.name + ".roadmodel-")).as_posix()
    rules = ["/" + _pattern(name), "/" + _pattern(temporary) + "*.tmp"]
    additions = [rule for rule in rules if rule.encode() not in existing.splitlines()]
    if additions:
        data = existing + (b"\n" if existing and not existing.endswith(b"\n") else b"")
        atomic_private_write(ignore, data + ("\n".join(additions) + "\n").encode())
    if repo.returncode == 0:
        for candidate in (name, temporary + "probe.tmp"):
            if _git(root, "check-ignore", "--no-index", "--quiet", "--", candidate).returncode:
                raise UnsafePrivatePath("Repository ignore rules do not protect private output.")
    return output
