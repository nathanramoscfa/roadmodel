"""One advisory updater lock per machine, with explicit child handover.

The installed launcher holds the operating-system lock while a synchronously
invoked replacement updater runs. Its child can identify that ownership through
a random inherited token and owner PID, including Windows venv redirectors
between the processes. No project or rule data is stored in the lock file.
"""

from __future__ import annotations

import errno
import importlib.util
import json
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

LOCK_TOKEN_ENV = "ROADMODEL_UPDATER_LOCK_TOKEN"  # noqa: S105 — environment variable name
LOCK_PID_ENV = "ROADMODEL_UPDATER_LOCK_PID"
_WINDOWS = os.name == "nt"
_BUSY = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


def _acquire(stream: BinaryIO) -> bool:
    stream.seek(0)
    try:
        if _WINDOWS:
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in _BUSY:
            return False
        raise


def _release(stream: BinaryIO) -> None:
    stream.seek(0)
    if _WINDOWS:
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _windows_process_parents() -> dict[int, int]:
    """Return a native process snapshot without starting another interpreter.

    A Windows venv's python.exe is a redirector which launches the base Python
    as its child. The updater owner therefore need not be os.getppid().
    """
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        parents: dict[int, int] = {}
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return parents
    finally:
        kernel.CloseHandle(snapshot)


def _owner_is_ancestor(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if not _WINDOWS:
        return pid == os.getppid()
    parents = _windows_process_parents()
    current = os.getpid()
    seen: set[int] = set()
    while current in parents and current not in seen:
        if current == pid:
            return True
        seen.add(current)
        current = parents[current]
    return False


def _inherited_owner(stream: BinaryIO) -> bool:
    token = os.environ.get(LOCK_TOKEN_ENV)
    owner_pid = os.environ.get(LOCK_PID_ENV)
    if not token or not owner_pid:
        return False
    try:
        # Match the record before checking ancestry. A token copied into an
        # unrelated shell is insufficient, as is a PID for a departed owner.
        pid = int(owner_pid)
        stream.seek(1)  # Windows locks byte zero; owner metadata is after it.
        state = json.loads(stream.read().decode("utf-8"))
        return (
            isinstance(state, dict)
            and state.get("version") == 1
            and type(state.get("pid")) is int
            and state["pid"] == pid
            and isinstance(state.get("token"), str)
            and secrets.compare_digest(state["token"], token)
            and _owner_is_ancestor(pid)
        )
    except (OSError, ValueError, TypeError):
        return False


def _private_stream(config: Path) -> BinaryIO:
    here = Path(__file__).resolve()
    path = (
        here.parent.parent / "src/roadmodel/private_files.py"
        if here.parent.name == "scripts" and (here.parent.parent / "pyproject.toml").is_file()
        else here.with_name("private_files.py")
    )
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError("released helper unavailable")
        spec = importlib.util.spec_from_file_location("roadmodel_lock_private", path)
        if spec is None or spec.loader is None:
            raise ValueError("released helper unavailable")
        module = importlib.util.module_from_spec(spec)
        # Fixed released companion, avoiding CWD imports and generated bytecode.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)  # noqa: S102  # nosec B102
        module.private_directory(config)
        return module.open_private_update(config / "update.lock")
    except (OSError, ValueError):
        raise RuntimeError(
            "Private lock cannot be opened safely; repair its permissions before retrying."
        ) from None


@contextmanager
def machine_lock(config: Path) -> Iterator[None]:
    """Hold config/update.lock or raise RuntimeError if another updater owns it.

    OS locks, rather than PID files, decide contention and expire when a
    process exits. Check/help/dry-run callers should bypass this context.
    """
    config = Path(config)
    with _private_stream(config) as stream:
        # CRT byte-range locks permit locking beyond EOF. Acquire before the
        # first write so another first opener cannot race the sentinel.
        if not _acquire(stream):
            if not _inherited_owner(stream):
                raise RuntimeError("Another roadmodel updater is already running on this machine")
            yield
            return

        old = {name: os.environ.get(name) for name in (LOCK_TOKEN_ENV, LOCK_PID_ENV)}
        token = secrets.token_hex(32)
        pid = os.getpid()
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
                stream.flush()
            state = json.dumps({"version": 1, "pid": pid, "token": token}).encode("utf-8")
            # Never truncate the locked sentinel byte, including during an
            # owner change. Readers may inspect metadata without touching it.
            stream.seek(1)
            stream.write(state)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            os.environ[LOCK_TOKEN_ENV] = token
            os.environ[LOCK_PID_ENV] = str(pid)
            yield
        finally:
            for name, previous in old.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
            _release(stream)
