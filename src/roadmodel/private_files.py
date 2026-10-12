"""Atomic private files and safe planning-kit destinations (stdlib only).

POSIX modes and protected Windows ACLs are enforced before private bytes exist.
Canonical source symlinks may be read by callers; output links are refused.
"""

from __future__ import annotations

import os
import secrets
import stat

# Fixed read-only Git invocations, without a shell.
import subprocess  # nosec B404
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO


class UnsafePrivatePath(ValueError):
    """An output path cannot safely hold private content."""


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _regular(info: os.stat_result) -> None:
    if _linked(info) or not stat.S_ISREG(info.st_mode):
        raise UnsafePrivatePath("Output must be a regular file, not a link or special file.")


class _WindowsFiles:
    """Handle-relative local NTFS/ReFS I/O with protected creation-time ACLs.

    Kept in this file because the isolated updater extracts this stdlib helper.
    UNC/device paths and reparse points are deliberately unsupported. Existing
    broad log ACLs require an explicit operator repair; appending fails closed.
    """

    def __init__(self) -> None:
        import ctypes as c
        from ctypes import wintypes as w

        self.c, self.w = c, w
        pointer = c.c_void_p
        pp = c.POINTER(pointer)
        loader = c.WinDLL  # type: ignore[attr-defined]  # Windows-only stdlib API
        kernel = loader("kernel32", use_last_error=True, winmode=0x800)
        security = loader("advapi32", use_last_error=True, winmode=0x800)
        native = loader("ntdll", use_last_error=True, winmode=0x800)

        class Unicode(c.Structure):
            _fields_ = [("length", w.WORD), ("maximum", w.WORD), ("buffer", pointer)]

        class Attributes(c.Structure):
            _fields_ = [
                ("length", w.DWORD),
                ("root", w.HANDLE),
                ("name", c.POINTER(Unicode)),
                ("flags", w.DWORD),
                ("descriptor", pointer),
                ("qos", pointer),
            ]

        class Status(c.Structure):
            _fields_ = [("status", pointer), ("information", c.c_size_t)]

        class Info(c.Structure):
            _fields_ = [
                ("attributes", w.DWORD),
                ("created", w.FILETIME),
                ("accessed", w.FILETIME),
                ("written", w.FILETIME),
                ("volume", w.DWORD),
                ("size_high", w.DWORD),
                ("size_low", w.DWORD),
                ("links", w.DWORD),
                ("index_high", w.DWORD),
                ("index_low", w.DWORD),
            ]

        class Acl(c.Structure):
            _fields_ = [
                ("revision", w.BYTE),
                ("pad", w.BYTE),
                ("size", w.WORD),
                ("count", w.WORD),
                ("pad2", w.WORD),
            ]

        class Ace(c.Structure):
            _fields_ = [("kind", w.BYTE), ("flags", w.BYTE), ("size", w.WORD)]

        class Rename(c.Structure):
            _fields_ = [
                ("replace", w.BYTE),
                ("root", w.HANDLE),
                ("length", w.DWORD),
                ("name", w.WCHAR * 1),
            ]

        self.Unicode, self.Attributes, self.Status = Unicode, Attributes, Status
        self.Info, self.Acl, self.Ace, self.Rename = Info, Acl, Ace, Rename

        def bind(dll: Any, name: str, result: Any, *arguments: Any) -> Any:
            function = getattr(dll, name)
            function.restype, function.argtypes = result, arguments
            return function

        self.close = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
        self.free = bind(kernel, "LocalFree", pointer, pointer)
        self.process = bind(kernel, "GetCurrentProcess", w.HANDLE)
        self.thread = bind(kernel, "GetCurrentThread", w.HANDLE)
        self.open_process_token = bind(security, "OpenProcessToken", w.BOOL, w.HANDLE, w.DWORD, pp)
        self.open_thread_token = bind(
            security, "OpenThreadToken", w.BOOL, w.HANDLE, w.DWORD, w.BOOL, pp
        )
        self.get_token = bind(
            security,
            "GetTokenInformation",
            w.BOOL,
            w.HANDLE,
            c.c_int,
            pointer,
            w.DWORD,
            c.POINTER(w.DWORD),
        )
        self.sid_string = bind(security, "ConvertSidToStringSidW", w.BOOL, pointer, pp)
        self.convert_sd = bind(
            security,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            w.BOOL,
            w.LPCWSTR,
            w.DWORD,
            pp,
            pointer,
        )
        self.get_control = bind(
            security,
            "GetSecurityDescriptorControl",
            w.BOOL,
            pointer,
            c.POINTER(w.WORD),
            c.POINTER(w.DWORD),
        )
        self.get_ace = bind(security, "GetAce", w.BOOL, pointer, w.DWORD, pp)
        self.get_security = bind(
            security, "GetSecurityInfo", w.DWORD, w.HANDLE, c.c_int, w.DWORD, pp, pp, pp, pp, pp
        )
        self.get_dacl = bind(
            security,
            "GetSecurityDescriptorDacl",
            w.BOOL,
            pointer,
            c.POINTER(w.BOOL),
            pp,
            c.POINTER(w.BOOL),
        )
        self.set_security = bind(
            security,
            "SetSecurityInfo",
            w.DWORD,
            w.HANDLE,
            c.c_int,
            w.DWORD,
            pointer,
            pointer,
            pointer,
            pointer,
        )
        self.create_root = bind(
            kernel,
            "CreateFileW",
            w.HANDLE,
            w.LPCWSTR,
            w.DWORD,
            w.DWORD,
            pointer,
            w.DWORD,
            w.DWORD,
            w.HANDLE,
        )
        self.get_info = bind(
            kernel, "GetFileInformationByHandle", w.BOOL, w.HANDLE, c.POINTER(Info)
        )
        self.volume_info = bind(
            kernel,
            "GetVolumeInformationByHandleW",
            w.BOOL,
            w.HANDLE,
            w.LPWSTR,
            w.DWORD,
            pointer,
            pointer,
            c.POINTER(w.DWORD),
            w.LPWSTR,
            w.DWORD,
        )
        self.create = bind(
            native,
            "NtCreateFile",
            c.c_int32,
            pp,
            w.DWORD,
            c.POINTER(Attributes),
            c.POINTER(Status),
            pointer,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            pointer,
            w.DWORD,
        )
        self.set_info = bind(
            native,
            "NtSetInformationFile",
            c.c_int32,
            w.HANDLE,
            c.POINTER(Status),
            pointer,
            w.DWORD,
            c.c_int,
        )

    @staticmethod
    def check(ok: Any) -> None:
        if not ok:
            raise UnsafePrivatePath("Windows private file safety check failed.")

    def sid(self, pointer: Any) -> str:
        result = self.c.c_void_p()
        self.check(self.sid_string(pointer, self.c.byref(result)))
        try:
            return str(self.c.wstring_at(result))
        finally:
            self.free(result)

    def user(self) -> str:
        c, w = self.c, self.w
        token = c.c_void_p()
        if self.open_thread_token(self.thread(), 8, True, c.byref(token)):
            self.close(token)
            raise UnsafePrivatePath("Impersonated private file access is unsupported.")
        self.check(c.get_last_error() == 1008)  # ERROR_NO_TOKEN
        self.check(self.open_process_token(self.process(), 8, c.byref(token)))
        try:
            count = w.DWORD()
            self.get_token(token, 1, None, 0, c.byref(count))  # TokenUser
            self.check(c.get_last_error() == 122 and 0 < count.value < 65536)
            buffer = c.create_string_buffer(count.value)
            self.check(self.get_token(token, 1, buffer, len(buffer), c.byref(count)))
            return self.sid(c.c_void_p.from_buffer(buffer).value)
        finally:
            self.close(token)

    @contextmanager
    def descriptor(self, directory: bool = False) -> Iterator[tuple[Any, frozenset[str]]]:
        user = self.user()
        principals = frozenset({user, "S-1-5-18", "S-1-5-32-544"})
        flags = "OICI" if directory else ""
        sddl = (
            "O:"
            + user
            + "D:P"
            + "".join(f"(A;{flags};FA;;;{principal})" for principal in sorted(principals))
        )
        descriptor = self.c.c_void_p()
        self.check(self.convert_sd(sddl, 1, self.c.byref(descriptor), None))
        try:
            yield descriptor, principals
        finally:
            self.free(descriptor)

    def verify(
        self,
        handle: int,
        principals: frozenset[str],
        *,
        directory: bool = False,
        owner_only: bool = False,
    ) -> None:
        c, w = self.c, self.w
        owner, dacl, descriptor = c.c_void_p(), c.c_void_p(), c.c_void_p()
        self.check(
            self.get_security(
                handle, 1, 5, c.byref(owner), None, c.byref(dacl), None, c.byref(descriptor)
            )
            == 0
        )
        try:
            self.check(self.sid(owner) in principals)
            if owner_only:
                return
            control, revision = w.WORD(), w.DWORD()
            self.check(self.get_control(descriptor, c.byref(control), c.byref(revision)))
            self.check(dacl.value and control.value & 0x1000)  # protected DACL
            acl = c.cast(dacl, c.POINTER(self.Acl)).contents
            self.check(acl.count == len(principals))
            observed = set()
            for index in range(acl.count):
                entry = c.c_void_p()
                self.check(self.get_ace(dacl, index, c.byref(entry)))
                header = c.cast(entry, c.POINTER(self.Ace)).contents
                self.check(
                    header.kind == 0
                    and header.flags == (3 if directory else 0)
                    and header.size >= 16
                )
                address = int(entry.value or 0)
                self.check(w.DWORD.from_address(address + 4).value == 0x001F01FF)
                observed.add(self.sid(address + 8))
            self.check(observed == principals)
        finally:
            self.free(descriptor)

    def info(self, handle: int, directory: bool = False) -> Any:
        info = self.Info()
        self.check(self.get_info(handle, self.c.byref(info)))
        self.check(not info.attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        self.check(bool(info.attributes & 0x10) == directory)
        return info

    def open(
        self,
        parent: int,
        name: str,
        access: int,
        disposition: int,
        *,
        directory: bool = False,
        descriptor: Any = None,
        share: int = 3,
    ) -> int:
        c = self.c
        encoded = name.encode("utf-16-le")
        self.check(0 < len(encoded) <= 65532)
        text = c.create_string_buffer(encoded + b"\0\0")
        unicode = self.Unicode(len(encoded), len(encoded) + 2, c.cast(text, c.c_void_p))
        attributes = self.Attributes(
            c.sizeof(self.Attributes), parent, c.pointer(unicode), 0x1040, descriptor, None
        )
        handle, status = c.c_void_p(), self.Status()
        result = self.create(
            c.byref(handle),
            access | 0x100000 | 0x20000 | 0x80,
            c.byref(attributes),
            c.byref(status),
            None,
            0x80,
            share,
            disposition,
            0x200020 | (1 if directory else 0x40),
            None,
            0,
        )
        # STATUS_OBJECT_NAME_NOT_FOUND is needed for nonmutating leaf preflight.
        if result & 0xFFFFFFFF == 0xC0000034:
            raise FileNotFoundError("Private output does not exist.")
        self.check(result >= 0 and handle.value)
        value = int(handle.value or 0)
        try:
            self.info(value, directory)
            if directory and status.information == 2:  # FILE_CREATED
                self.verify(
                    value, frozenset({self.user(), "S-1-5-18", "S-1-5-32-544"}), directory=True
                )
            return value
        except BaseException:
            self.close(value)
            raise

    @staticmethod
    def validate(path: Path) -> None:
        # No UNC/extended/device namespace, ADS, dot-dot or Win32 device alias.
        anchor = path.anchor
        if (
            len(anchor) != 3
            or anchor[1:] != ":\\"
            or not anchor[0].isascii()
            or not anchor[0].isalpha()
        ):
            raise UnsafePrivatePath("Private Windows files require a local absolute drive path.")
        for part in path.parts[1:]:
            stem = part.split(".", 1)[0].upper()
            reserved = stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or (
                stem.startswith(("COM", "LPT"))
                and len(stem[3:]) == 1
                and stem[3:] in "123456789¹²³"
            )
            if (
                reserved
                or part in {".", ".."}
                or part.endswith((" ", "."))
                or any(ord(char) < 32 or ord(char) == 127 or char in ':<>"|?*' for char in part)
            ):
                raise UnsafePrivatePath("Unsupported private Windows path component.")

    @contextmanager
    def parent(self, path: Path, *, repair: bool = False) -> Iterator[int]:
        self.validate(path)
        handles: list[int] = []
        root = self.create_root(path.anchor, 0x1200A0, 3, None, 3, 0x02200000, None)
        self.check(root and root != self.c.c_void_p(-1).value)
        handles.append(int(root))
        try:
            self.info(int(root), True)
            flags = self.w.DWORD()
            self.check(self.volume_info(root, None, 0, None, None, self.c.byref(flags), None, 0))
            self.check(flags.value & 8)  # FILE_PERSISTENT_ACLS
            with self.descriptor(True) as (descriptor, principals):
                parts = path.parent.parts[1:]
                for index, part in enumerate(parts):
                    final = repair and index == len(parts) - 1
                    child = self.open(
                        handles[-1],
                        part,
                        0x20 | (0x40000 if final else 0),
                        3,
                        directory=True,
                        descriptor=descriptor,
                    )
                    handles.append(child)
                    if final:
                        self.verify(child, principals, directory=True, owner_only=True)
                        present, defaulted, dacl = self.w.BOOL(), self.w.BOOL(), self.c.c_void_p()
                        self.check(
                            self.get_dacl(
                                descriptor,
                                self.c.byref(present),
                                self.c.byref(dacl),
                                self.c.byref(defaulted),
                            )
                        )
                        self.check(present.value and dacl.value)
                        # Explicitly owned directory only. Inheritable ACEs may
                        # also tighten its children; arbitrary parents stay intact.
                        self.check(
                            self.set_security(child, 1, 0x80000004, None, None, dacl, None) == 0
                        )
                        self.verify(child, principals, directory=True)
                self.check(not repair or bool(parts))
                yield handles[-1]
        finally:
            for handle in reversed(handles):
                self.close(handle)

    def rename(self, handle: int, parent: int, name: str, *, replace: bool = True) -> None:
        c = self.c
        encoded = name.encode("utf-16-le")
        buffer = c.create_string_buffer(c.sizeof(self.Rename) + len(encoded))
        rename = self.Rename.from_buffer(buffer)
        rename.replace, rename.root, rename.length = int(replace), parent, len(encoded)
        c.memmove(c.addressof(buffer) + self.Rename.name.offset, encoded, len(encoded))
        status = self.Status()
        self.check(self.set_info(handle, c.byref(status), buffer, len(buffer), 10) >= 0)

    def discard(self, handle: int) -> None:
        flag, status = self.w.BYTE(1), self.Status()
        self.check(self.set_info(handle, self.c.byref(status), self.c.byref(flag), 1, 13) >= 0)

    def fd(self, handle: int, flags: int) -> int:
        import msvcrt

        try:
            fd = msvcrt.open_osfhandle(handle, flags | 0x80)  # type: ignore[attr-defined]
        except OSError:
            raise UnsafePrivatePath("Cannot open the private Windows file stream.") from None
        return int(fd)

    def write(
        self,
        path: Path,
        data: bytes,
        *,
        replace: bool = True,
        before_replace: Callable[[], None] | None = None,
    ) -> None:
        with self.parent(path) as parent, self.descriptor() as (descriptor, principals):
            try:
                target = self.open(parent, path.name, 0, 1)
            except FileNotFoundError:
                pass
            else:
                self.close(target)
            name = f".{path.name}.roadmodel-{secrets.token_hex(16)}.tmp"
            handle = self.open(
                parent, name, 0x10000 | 0x40000000, 2, descriptor=descriptor, share=0
            )
            published = False
            fd: int | None = None
            try:
                self.verify(handle, principals)
                self.check(self.info(handle).links == 1)
                fd = self.fd(handle, os.O_WRONLY | 0x8000)
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    self.check(written > 0)
                    view = view[written:]
                os.fsync(fd)
                if before_replace is not None:
                    before_replace()
                self.rename(handle, parent, path.name, replace=replace)
                published = True
            finally:
                try:
                    if not published:
                        self.discard(handle)
                finally:
                    if fd is None:
                        self.close(handle)
                    else:
                        os.close(fd)

    def read(self, path: Path) -> bytes:
        with self.parent(path) as parent:
            handle = self.open(parent, path.name, 0x80000000, 1)
            try:
                fd = self.fd(handle, os.O_RDONLY | 0x8000)
            except BaseException:
                self.close(handle)
                raise
            try:
                stream = os.fdopen(fd, "rb")
            except BaseException:
                os.close(fd)
                raise
            with stream:
                return stream.read()

    def append(self, path: Path) -> TextIO:
        with self.parent(path) as parent, self.descriptor() as (descriptor, principals):
            handle = self.open(parent, path.name, 4, 3, descriptor=descriptor)
            try:
                self.verify(handle, principals)
                self.check(self.info(handle).links == 1)
            except BaseException:
                self.close(handle)
                raise
            try:
                fd = self.fd(handle, os.O_WRONLY | os.O_APPEND | 0x8000)
            except BaseException:
                self.close(handle)
                raise
            try:
                return os.fdopen(fd, "a", encoding="utf-8")
            except BaseException:
                os.close(fd)
                raise


def _windows() -> _WindowsFiles:
    # Do not cache the identity/descriptor: every operation rechecks the token.
    return _WindowsFiles()


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
        with _windows().parent(path / ".directory-check", repair=True):
            pass


def atomic_private_write(
    path: Path,
    data: bytes,
    *,
    replace: bool = True,
    before_replace: Callable[[], None] | None = None,
) -> None:
    """Write new bytes at 0600, replacing hardlinks without touching their peers."""
    path = path.expanduser().absolute()
    if os.name == "nt":
        _windows().write(path, data, replace=replace, before_replace=before_replace)
        return
    temporary = f".{path.name}.roadmodel-{secrets.token_hex(16)}.tmp"
    directory: int | None = None
    staged: str | Path = path.parent / temporary
    target: str | Path = path
    if os.name == "posix":
        directory = _parent_fd(path)
        staged, target = temporary, path.name
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
        if before_replace is not None:
            before_replace()
        if replace:
            os.replace(staged, target, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            os.link(
                staged, target, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
            )
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
        return _windows().read(path)
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
    if os.name == "nt":
        return _windows().append(path)
    directory = _parent_fd(path)
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
