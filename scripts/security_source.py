"""Bind security analysis to immutable, complete tracked Git source."""

from __future__ import annotations

import hashlib
import os
import re
import selectors
import stat
import subprocess
import time
from pathlib import Path

from security_sarif import MANIFEST_PATH, digest, repo_path, require

MAX_FILE = 16 * 1024 * 1024
MAX_TREE = 128 * 1024 * 1024
MAX_PATHS = 20000


def bounded_command(argv: list[str], env: dict, limit: int, timeout: float = 60) -> bytes:
    """Bound stdout during capture; discard command errors without exposing paths."""
    require(type(limit) is int and 0 < limit <= MAX_TREE and timeout > 0)
    process = subprocess.Popen(  # noqa: S603 — controlled Git/scanner argv, no shell
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
    )
    chunks, total = [], 0
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0)
                ready = selector.select(min(remaining, 0.25))
                for key, _ in ready:
                    chunk = os.read(key.fileobj.fileno(), min(65536, limit - total + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    require(total <= limit)
                    chunks.append(chunk)
            remaining = deadline - time.monotonic()
            require(remaining > 0)
            require(process.wait(timeout=remaining) == 0)
        return b"".join(chunks)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def bounded_regular(root: Path, relative: str, limit=MAX_FILE) -> tuple[bytes, int]:
    """Anchor every component with O_NOFOLLOW; never follow a source symlink."""
    relative = repo_path(relative)
    require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"))
    flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptor = os.open(root, flags | os.O_DIRECTORY)
    try:
        for component in relative.split("/")[:-1]:
            child = os.open(component, flags | os.O_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(relative.split("/")[-1], flags, dir_fd=descriptor)
        try:
            before = os.fstat(file_descriptor)
            require(
                stat.S_ISREG(before.st_mode)
                and before.st_nlink == 1
                and 0 <= before.st_size <= limit
            )
            chunks, total = [], 0
            while chunk := os.read(file_descriptor, min(1024 * 1024, limit - total + 1)):
                total += len(chunk)
                require(total <= limit)
                chunks.append(chunk)
            after = os.fstat(file_descriptor)
            require(
                (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            )
            return b"".join(chunks), before.st_mode
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


class GitTree:
    def __init__(self, root: Path, commit: str | None = None):
        self.root = root.resolve(strict=True)
        self.root_uri = self.root.as_uri().rstrip("/") + "/"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_NO_REPLACE_OBJECTS="1",
            GIT_OPTIONAL_LOCKS="0",
            GIT_TERMINAL_PROMPT="0",
        )
        actual = self.git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        require(bool(re.fullmatch(r"[0-9a-f]{40}", actual)))
        self.commit = actual if commit is None else commit
        require(bool(re.fullmatch(r"[0-9a-f]{40}", self.commit)))
        require(self.git("cat-file", "-t", self.commit).strip() == b"commit")
        self.entries, self.blobs = {}, {}
        records = self.git(
            "ls-tree", "-rz", "--full-tree", self.commit, limit=8 * 1024 * 1024
        ).split(b"\0")
        require(len(records) <= MAX_PATHS + 1 and records[-1] == b"")
        total = 0
        for record in records[:-1]:
            header, name = record.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            path = repo_path(name.decode("utf-8"))
            require(path not in self.entries and mode in {"100644", "100755"} and kind == "blob")
            require(bool(re.fullmatch(r"[0-9a-f]{40}", oid)))
            size_text = self.git("cat-file", "-s", oid).decode().strip()
            require(size_text.isascii() and size_text.isdecimal())
            size = int(size_text)
            require(size <= MAX_FILE)
            total += size
            require(total <= MAX_TREE)
            data = self.git("cat-file", "blob", oid, limit=MAX_FILE)
            require(len(data) == size)
            self.entries[path] = {
                "mode": mode,
                "oid": oid,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            self.blobs[path] = data
        require(bool(self.entries))

    def git(self, *args: str, limit=1024 * 1024) -> bytes:
        argv = [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-C",
            str(self.root),
            *args,
        ]
        return bounded_command(argv, self.env, limit)

    def context_digest(self, excluded=MANIFEST_PATH) -> str:
        require(excluded == MANIFEST_PATH)
        return digest(
            {
                "policy": "whole-tree-v1",
                "files": [
                    [path, entry["mode"], entry["sha256"]]
                    for path, entry in sorted(self.entries.items())
                    if path != excluded
                ],
            }
        )

    def bind_region(self, path: str, region: dict, column_kind: str) -> dict:
        path = repo_path(path)
        require(path in self.entries)
        require(column_kind in {"utf16CodeUnits", "unicodeCodePoints"})
        require(
            not (
                set(region)
                - {"startLine", "endLine", "startColumn", "endColumn", "snippet", "message"}
            )
        )
        content = self.blobs[path]
        lines = content.splitlines(keepends=True)
        start = region.get("startLine")
        end = region.get("endLine", start)
        require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines))

        def width(number):
            text = lines[number - 1].decode("utf-8").rstrip("\r\n")
            return (
                len(text.encode("utf-16-le")) // 2 if column_kind == "utf16CodeUnits" else len(text)
            )

        first = region.get("startColumn", 1)
        last = region.get("endColumn", width(end) + 1)
        require(
            type(first) is int
            and type(last) is int
            and 1 <= first <= width(start) + 1
            and 1 <= last <= width(end) + 1
        )
        require(end > start or last > first)
        return {
            "mode": self.entries[path]["mode"],
            "sha256": self.entries[path]["sha256"],
            "line_sha256": hashlib.sha256(b"".join(lines[start - 1 : end])).hexdigest(),
        }

    def verify_checkout(self) -> None:
        require(self.git("rev-parse", "--verify", "HEAD^{commit}").decode().strip() == self.commit)
        # Fresh build-mode-none CI must not introduce even ignored source inputs.
        require(not self.git("ls-files", "--others", "-z", limit=8 * 1024 * 1024))
        for path, entry in self.entries.items():
            data, mode = bounded_regular(self.root, path)
            require(hashlib.sha256(data).hexdigest() == entry["sha256"])
            require(bool(mode & 0o111) == (entry["mode"] == "100755"))

    def receipt(self) -> dict:
        return {
            "schema": 1,
            "commit": self.commit,
            "context_sha256": self.context_digest(),
            "tracked_files": len(self.entries),
            "tree_sha256": digest(self.entries),
        }

    def verify_receipt(self, value: dict) -> None:
        require(value == self.receipt())
        self.verify_checkout()
