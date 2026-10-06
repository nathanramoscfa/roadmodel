"""One advisory updater lock per machine, with explicit child handover.

The installed launcher holds the operating-system lock while a synchronously
invoked replacement updater runs. Its direct child can identify that ownership
through a random inherited token and owner PID. No project or rule data is
stored in the persistent, harmless lock file.
"""

from __future__ import annotations

import errno
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


def _inherited_owner(stream: BinaryIO) -> bool:
    token = os.environ.get(LOCK_TOKEN_ENV)
    owner_pid = os.environ.get(LOCK_PID_ENV)
    if not token or not owner_pid:
        return False
    try:
        # Handover is deliberately limited to a direct child (or reentrant
        # use by the owner). A stale token in an unrelated shell is not proof
        # that the lock holder will remain alive throughout this operation.
        pid = int(owner_pid)
        if pid not in (os.getpid(), os.getppid()):
            return False
        stream.seek(1)  # Windows locks byte zero; owner metadata is after it.
        state = json.loads(stream.read().decode("utf-8"))
        return (
            isinstance(state, dict)
            and state.get("version") == 1
            and type(state.get("pid")) is int
            and state["pid"] == pid
            and isinstance(state.get("token"), str)
            and secrets.compare_digest(state["token"], token)
        )
    except (OSError, ValueError, TypeError):
        return False


@contextmanager
def machine_lock(config: Path) -> Iterator[None]:
    """Hold config/update.lock or raise RuntimeError if another updater owns it.

    OS locks, rather than PID files, decide contention and expire when a
    process exits. Check/help/dry-run callers should bypass this context.
    """
    config = Path(config)
    config.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(config / "update.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+b") as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"\0")  # msvcrt requires a byte at the locked offset.
            stream.flush()
        if not _acquire(stream):
            if not _inherited_owner(stream):
                raise RuntimeError("Another roadmodel updater is already running on this machine")
            yield
            return

        old = {name: os.environ.get(name) for name in (LOCK_TOKEN_ENV, LOCK_PID_ENV)}
        token = secrets.token_hex(32)
        pid = os.getpid()
        try:
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
