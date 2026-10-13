"""Actual local writers; only tmp_path files and one synthetic child execute."""

from __future__ import annotations

import contextlib
import importlib.util
import inspect
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Mac local jobs use POSIX flock")


def source_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "local_writer_fixture_" + name, ROOT / "scripts" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return {
        name: source_module(name)
        for name in ["pool_usage", "configure_claude_pool", "roll_pool_status", "push_pool_status"]
    }


@pytest.fixture
def private_job(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return source_module("private_job")


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def snapshot() -> dict[str, Any]:
    return {"source": "claude", "observed_at": 1700000000, "windows": [], "extra": {}}


def test_pool_save_tightens_owned_cache_without_changing_public_parent(
    modules: dict[str, Any], tmp_path: Path
) -> None:
    parent = tmp_path / "public"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    cache = parent / "cache"
    cache.mkdir(mode=0o755)
    cache.chmod(0o755)
    destination = cache / "claude.json"
    destination.write_text("old")
    destination.chmod(0o644)
    modules["pool_usage"].save(snapshot(), cache)
    assert json.loads(destination.read_text()) == snapshot()
    assert mode(destination) == 0o600 and mode(cache) == 0o700
    assert mode(parent) == 0o755
    assert list(cache.iterdir()) == [destination]


@pytest.mark.parametrize("link_position", ["cache", "ancestor", "file"])
def test_pool_save_refuses_links_before_changing_outside_files(
    modules: dict[str, Any], tmp_path: Path, link_position: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "claude.json"
    sentinel.write_bytes(b"synthetic outside sentinel")
    sentinel.chmod(0o644)
    if link_position == "cache":
        cache = tmp_path / "cache"
        cache.symlink_to(outside, target_is_directory=True)
    elif link_position == "ancestor":
        link = tmp_path / "ancestor"
        link.symlink_to(outside, target_is_directory=True)
        (outside / "cache").mkdir()
        sentinel = outside / "cache" / "claude.json"
        sentinel.write_bytes(b"synthetic outside sentinel")
        sentinel.chmod(0o644)
        cache = link / "cache"
    else:
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "claude.json").symlink_to(sentinel)
    with pytest.raises((OSError, ValueError)):
        modules["pool_usage"].save(snapshot(), cache)
    assert sentinel.read_bytes() == b"synthetic outside sentinel"
    assert mode(sentinel) == 0o644


def test_atomic_settings_detaches_regular_hardlink_and_tightens_only_destination(
    modules: dict[str, Any], tmp_path: Path
) -> None:
    peer = tmp_path / "peer.json"
    peer.write_bytes(b'{"original":true}')
    peer.chmod(0o644)
    target = tmp_path / "settings.json"
    os.link(peer, target)
    modules["configure_claude_pool"].atomic_json(target, {"updated": True})
    assert json.loads(target.read_text()) == {"updated": True}
    assert peer.read_bytes() == b'{"original":true}' and mode(peer) == 0o644
    assert mode(target) == 0o600 and target.stat().st_nlink == 1


@pytest.mark.parametrize("install", [False, True])
def test_settings_symlink_refused_before_preview_or_backup(
    modules: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    install: bool,
) -> None:
    outside = tmp_path / "outside.json"
    marker = "SYNTHETIC_LINKED_STATUSLINE_MUST_NOT_PRINT"
    outside.write_text(json.dumps({"statusLine": {"type": "command", "command": marker}}))
    original = outside.read_bytes()
    target = tmp_path / "settings.json"
    target.symlink_to(outside)
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        sys,
        "argv",
        ["configure", "--settings", str(target), "--cache", str(cache)]
        + (["--install"] if install else []),
    )
    with pytest.raises((OSError, ValueError)):
        modules["configure_claude_pool"].main()
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
    assert outside.read_bytes() == original and target.is_symlink()
    assert not cache.exists()


def test_restore_refuses_linked_backup_without_changing_settings(
    modules: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "settings.json"
    target.write_bytes(
        b'{"statusLine":{"type":"command","command":"synthetic-current"},"other":true}'
    )
    before = target.read_bytes()
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b'{"type":"command","command":"synthetic-outside"}')
    (cache / "claude-statusline-original.json").symlink_to(outside)
    monkeypatch.setattr(
        sys, "argv", ["configure", "--settings", str(target), "--cache", str(cache), "--restore"]
    )
    with pytest.raises((OSError, ValueError)):
        modules["configure_claude_pool"].main()
    assert target.read_bytes() == before


def test_missing_settings_preview_creates_no_parent_or_cache(
    modules: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "absent-parent" / "settings.json"
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        sys, "argv", ["configure", "--settings", str(target), "--cache", str(cache)]
    )
    assert modules["configure_claude_pool"].main() == 0
    assert not target.parent.exists() and not cache.exists()


def inject_after_staging_close(
    monkeypatch: pytest.MonkeyPatch, index: int, mutation: Any
) -> list[int]:
    """Both old tempfile writers and new private writer use fdopen at this boundary."""
    original = os.fdopen
    closed: list[int] = []

    @contextlib.contextmanager
    def fdopen(fd: int, open_mode: str = "r", *args: Any, **kwargs: Any):
        with original(fd, open_mode, *args, **kwargs) as stream:
            yield stream
        if "w" in open_mode:
            closed.append(fd)
            if len(closed) == index:
                mutation()

    monkeypatch.setattr(os, "fdopen", fdopen)
    return closed


@pytest.mark.parametrize("initially_present", [False, True])
@pytest.mark.parametrize("mutation", ["bytes", "link"])
def test_settings_last_moment_change_refused_after_backup_and_staging(
    modules: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    initially_present: bool,
    mutation: str,
) -> None:
    target = tmp_path / "settings.json"
    if initially_present:
        target.write_bytes(b'{"other":"original"}')
    cache = tmp_path / "cache"
    outside = tmp_path / "outside.json"
    concurrent = b'{"other":"synthetic-concurrent-edit"}'
    outside.write_bytes(concurrent)

    def change() -> None:
        if mutation == "bytes":
            target.write_bytes(concurrent)
        else:
            target.unlink(missing_ok=True)
            target.symlink_to(outside)

    # Backup is write1; final settings staging is write2. Inject before replace.
    closed = inject_after_staging_close(monkeypatch, 2, change)
    monkeypatch.setattr(
        sys, "argv", ["configure", "--settings", str(target), "--cache", str(cache), "--install"]
    )
    with pytest.raises((RuntimeError, OSError, ValueError)):
        modules["configure_claude_pool"].main()
    assert len(closed) == 2
    assert target.read_bytes() == concurrent and outside.read_bytes() == concurrent
    assert target.is_symlink() is (mutation == "link")
    assert not list(tmp_path.glob(".*.tmp"))


def test_context_last_moment_change_refused_without_temp_leak(
    modules: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "context.md"
    target.write_text("before")
    closed = inject_after_staging_close(monkeypatch, 1, lambda: target.write_text("concurrent"))
    with pytest.raises(RuntimeError, match="context changed"):
        modules["roll_pool_status"].write_context(target, "before", "lost-edit")
    assert len(closed) == 1 and target.read_text() == "concurrent"
    assert list(tmp_path.iterdir()) == [target]


def test_context_direct_link_refused_but_explicit_main_target_and_crlf_work(
    modules: dict[str, Any], tmp_path: Path
) -> None:
    target = tmp_path / "context.md"
    text = "## Usage-pool status\r\n\r\n| Pool | Window | State | Resets | Notes |\r\n| x | 5 hours | `exhausted` | 2000-01-01 01:00 UTC | synthetic |\r\n"
    target.write_bytes(text.encode())
    link = tmp_path / "selected.md"
    link.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        modules["roll_pool_status"].write_context(link, text, "must-not-write")
    assert target.read_bytes() == text.encode()
    assert (
        modules["roll_pool_status"].main(
            ["--file", str(link), "--cache", str(tmp_path / "cache"), "--no-collect"]
        )
        == 0
    )
    assert link.is_symlink() and "`headroom`" in target.read_text()
    assert mode(target) == 0o600


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "cache-link"])
def test_sync_lock_refuses_link_without_touching_peer_or_credentials(
    modules: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    push = modules["push_pool_status"]
    outside = tmp_path / "outside"
    outside.mkdir()
    peer = outside / "peer"
    peer.write_bytes(b"synthetic sentinel")
    peer.chmod(0o644)
    cache = tmp_path / "cache"
    if kind == "cache-link":
        cache.symlink_to(outside, target_is_directory=True)
    else:
        cache.mkdir()
        if kind == "symlink":
            (cache / ".sync.lock").symlink_to(peer)
        else:
            os.link(peer, cache / ".sync.lock")
    monkeypatch.setattr(push, "keychain", lambda *a: pytest.fail("Keychain must not run"))
    monkeypatch.setattr(push, "credentials", lambda *a: pytest.fail("authentication must not run"))
    monkeypatch.setattr(push, "request", lambda *a, **kw: pytest.fail("network must not run"))
    monkeypatch.setattr(sys, "argv", ["push", "--cache", str(cache), "--dry-run"])
    assert push.main() == 1
    assert peer.read_bytes() == b"synthetic sentinel" and mode(peer) == 0o644
    if kind == "cache-link":
        assert not (outside / ".sync.lock").exists()


def test_sync_lock_keeps_inode_and_honors_existing_lock(
    modules: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import fcntl

    push = modules["push_pool_status"]
    cache = tmp_path / "cache"
    cache.mkdir()
    lock = cache / ".sync.lock"
    lock.write_bytes(b"existing-inode")
    before = lock.stat().st_ino
    monkeypatch.setattr(push, "keychain", lambda *a: pytest.fail("Keychain must not run"))
    monkeypatch.setattr(sys, "argv", ["push", "--cache", str(cache), "--dry-run"])
    with lock.open("rb") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert push.main() == 1
    assert push.main() == 0
    assert lock.stat().st_ino == before and lock.read_bytes() == b"existing-inode"
    assert mode(lock) == 0o600


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "ancestor", "open-error"])
def test_private_job_never_starts_child_when_output_is_unsafe(
    private_job: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    kind: str,
) -> None:
    logs = tmp_path / "logs"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "gate.log"
    sentinel.write_bytes(b"synthetic sentinel")
    sentinel.chmod(0o644)
    if kind == "ancestor":
        logs.symlink_to(outside, target_is_directory=True)
    else:
        logs.mkdir()
        if kind == "symlink":
            (logs / "gate.log").symlink_to(sentinel)
        elif kind == "hardlink":
            os.link(sentinel, logs / "gate.log")
        else:

            def refused(*args: Any, **kwargs: Any) -> Any:
                raise OSError("SYNTHETIC_OUTPUT_PATH_MUST_NOT_PRINT")

            monkeypatch.setattr(private_job.private_files(), "open_private_append", refused)
    monkeypatch.setattr(
        private_job.subprocess, "run", lambda *a, **kw: pytest.fail("real job must not start")
    )
    assert private_job.run_job("gate", logs) == 1
    captured = capsys.readouterr()
    assert (
        captured.out == ""
        and captured.err == "Local job could not open its private log or start safely.\n"
    )
    assert sentinel.read_bytes() == b"synthetic sentinel" and mode(sentinel) == 0o644


@pytest.mark.parametrize("job", ["../gate", "gate;echo injected", "unknown"])
def test_private_job_rejects_non_allowlisted_job_before_output(
    private_job: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, job: str
) -> None:
    monkeypatch.setattr(
        private_job, "private_files", lambda: pytest.fail("unknown job must not open output")
    )
    monkeypatch.setattr(
        private_job.subprocess, "run", lambda *a, **kw: pytest.fail("child must not run")
    )
    assert private_job.run_job(job, tmp_path / "logs") == 64
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize(
    "job,script,arguments",
    [("gate", "gate-alert-watcher.py", []), ("pools", "roll_pool_status.py", ["--sync-web"])],
)
def test_private_job_child_argv_and_append_contract(
    private_job: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    job: str,
    script: str,
    arguments: list[str],
) -> None:
    import fcntl

    parent = tmp_path / "public"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    logs = parent / "logs"
    logs.mkdir(mode=0o755)
    logs.chmod(0o755)
    captured: list[list[str]] = []
    signature = inspect.signature(subprocess.run)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        signature.bind(argv, **kwargs)
        assert argv == [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            str(ROOT / "scripts" / script),
            *arguments,
        ]
        assert kwargs["stderr"] == subprocess.STDOUT and kwargs["check"] is False
        assert not kwargs.get("shell")
        stream = kwargs["stdout"]
        assert fcntl.fcntl(stream.fileno(), fcntl.F_GETFL) & os.O_APPEND
        assert os.fstat(stream.fileno()).st_mode & 0o777 == 0o600
        stream.write("synthetic job output\n")
        captured.append(argv)
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(private_job.subprocess, "run", run)
    assert private_job.run_job(job, logs) == 7
    assert private_job.run_job(job, logs) == 7
    assert len(captured) == 2
    assert (logs / f"{job}.log").read_text() == "synthetic job output\n" * 2
    assert mode(logs) == 0o700 and mode(parent) == 0o755


def test_private_job_real_synthetic_child_ignores_cwd_and_pythonpath(
    private_job: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = tmp_path / "fixed-source"
    fixture.mkdir()
    # Only this temporary child can execute: the actual job map is unchanged.
    (fixture / "gate-alert-watcher.py").write_text(
        "import json,sys\nprint(json.dumps({'isolated':sys.flags.isolated,'utf8':sys.flags.utf8_mode,'args':sys.argv[1:]}),flush=True)\nprint('synthetic stderr',file=sys.stderr,flush=True)\nsys.exit(7)\n"
    )
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "json.py").write_text("raise RuntimeError('untrusted json imported')\n")
    (poison / "sitecustomize.py").write_text("raise RuntimeError('untrusted startup imported')\n")
    monkeypatch.chdir(poison)
    monkeypatch.setenv("PYTHONPATH", str(poison))
    monkeypatch.setattr(private_job, "__file__", str(fixture / "private_job.py"))
    logs = tmp_path / "logs"
    assert private_job.run_job("gate", logs) == 7
    lines = (logs / "gate.log").read_text().splitlines()
    assert json.loads(lines[0]) == {"isolated": 1, "utf8": 1, "args": []}
    assert lines[1:] == ["synthetic stderr"]


def test_static_launchd_jobs_preserve_labels_cadence_and_avoid_preopened_logs() -> None:
    for job, stem, cadence in [
        ("gate", "gate-alert-watcher", 60),
        ("pools", "roll-pool-status", 3600),
    ]:
        plist = plistlib.loads((ROOT / "scripts" / f"com.roadmodel.{stem}.plist").read_bytes())
        assert plist["Label"] == f"com.roadmodel.{stem}"
        assert plist["StartInterval"] == cadence and plist["RunAtLoad"] is True
        assert plist["StandardOutPath"] == plist["StandardErrorPath"] == "/dev/null"
        assert plist["ProgramArguments"][:2] == ["/bin/sh", "-c"]
        command = plist["ProgramArguments"][2]
        assert (
            ' -I -X utf8 "$HOME/roadmodel/scripts/private_job.py" ' + job
            == command[command.index(" -I") :]
        )
