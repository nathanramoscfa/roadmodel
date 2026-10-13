"""Private diagnostic artifacts: preflight before paid work, then pinned streams."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import TextIO

from local_private import private_files


def fresh_directory(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    private_files().private_directory(path)
    return path


def _parent(path: Path) -> None:
    if not path.parent.exists():
        private_files().private_directory(path.parent)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("Diagnostic parent must be a private directory.")
    if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError("Diagnostic parent must be privately owned.")
    # Windows creation/access is checked by the native helper, never mode bits.


class PrivateArtifact:
    """Reserve a new artifact, or safely reuse an explicitly private cache."""

    def __init__(self, path: Path, *, cache: bool = False) -> None:
        self.path = path.expanduser().absolute()
        _parent(self.path)
        private = private_files()
        if cache and self.path.exists():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Diagnostic cache must be an independent regular file.")
            if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
                raise ValueError("Diagnostic cache must be privately owned.")
        else:
            private.atomic_private_write(self.path, b"", replace=False)
        with private.open_private_update(self.path) as handle:
            info = os.fstat(handle.fileno())
            self.identity = (info.st_dev, info.st_ino)
            self.data = handle.read()

    def _unchanged(self) -> None:
        with private_files().open_private_update(self.path) as handle:
            info = os.fstat(handle.fileno())
            if (info.st_dev, info.st_ino) != self.identity or handle.read() != self.data:
                raise ValueError("Diagnostic artifact changed during the operation.")

    def append(self) -> TextIO:
        self._unchanged()
        stream = private_files().open_private_append(self.path)
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != self.identity:
            stream.close()
            raise ValueError("Diagnostic artifact changed during the operation.")
        return stream

    def write(self, text: str) -> None:
        private_files().atomic_private_write(
            self.path, text.encode("utf-8"), before_replace=self._unchanged
        )
