"""Updater exclusion uses OS locks, including self-update child ownership."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import venv
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def locks() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "updater_lock_tests", ROOT / "scripts" / "updater_lock.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_inherited_lock(locks: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(locks.LOCK_TOKEN_ENV, raising=False)
    monkeypatch.delenv(locks.LOCK_PID_ENV, raising=False)


def _command(config: Path, *, hold: bool = False) -> list[str]:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
        "from pathlib import Path\n"
        "from updater_lock import machine_lock\n"
        "try:\n"
        f"    with machine_lock(Path({str(config)!r})):\n"
        "        print('acquired', flush=True)\n"
        + ("        sys.stdin.readline()\n" if hold else "")
        + "except RuntimeError:\n"
        "    print('busy', flush=True)\n"
        "    sys.exit(9)\n"
    )
    return [sys.executable, "-c", code]


def _child(config: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _command(config), env=env, capture_output=True, text=True, timeout=10, check=False
    )


def _metadata(config: Path) -> bytes:
    # Windows prevents another file handle from reading locked byte zero.
    # The owner record deliberately starts beyond that sentinel.
    with (config / "update.lock").open("rb") as stream:
        stream.seek(1)
        return stream.read()


def test_lock_records_only_owner_and_restores_environment(
    locks: ModuleType, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    with locks.machine_lock(config):
        state = json.loads(_metadata(config))
        assert set(state) == {"version", "pid", "token"}
        assert state["pid"] == os.getpid()
        assert len(state["token"]) == 64
        assert os.environ[locks.LOCK_TOKEN_ENV] == state["token"]
        assert os.environ[locks.LOCK_PID_ENV] == str(os.getpid())
    assert locks.LOCK_TOKEN_ENV not in os.environ
    assert locks.LOCK_PID_ENV not in os.environ
    assert (config / "update.lock").is_file()
    assert (config / "update.lock").read_bytes()[:1] == b"\0"


def test_independent_process_is_rejected_then_can_acquire(
    locks: ModuleType, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    clean_env = dict(os.environ)
    with locks.machine_lock(config):
        result = _child(config, env=clean_env)
        assert result.returncode == 9 and result.stdout.strip() == "busy"
    result = _child(config, env=clean_env)
    assert result.returncode == 0 and result.stdout.strip() == "acquired"


def test_direct_handover_child_keeps_parents_lock(locks: ModuleType, tmp_path: Path) -> None:
    config = tmp_path / "config"
    clean_env = dict(os.environ)
    with locks.machine_lock(config):
        before = _metadata(config)
        child = _child(config)
        assert child.returncode == 0 and child.stdout.strip() == "acquired"
        assert _metadata(config) == before
        assert _child(config, env=clean_env).returncode == 9


def test_handover_through_real_virtualenv_python(locks: ModuleType, tmp_path: Path) -> None:
    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    config = tmp_path / "config"
    clean_env = dict(os.environ)
    with locks.machine_lock(config):
        before = _metadata(config)
        command = [str(python), *_command(config)[1:]]
        child = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
        assert child.returncode == 0, child.stdout + child.stderr
        assert child.stdout.strip() == "acquired"
        assert _metadata(config) == before
        assert _child(config, env=clean_env).returncode == 9


@pytest.mark.parametrize(
    "parents,owner,expected",
    [
        ({30: 20, 20: 10, 10: 1}, 10, True),
        ({30: 20, 20: 10}, 10, False),  # recorded owner has exited
        ({30: 20, 20: 1, 10: 1}, 10, False),  # live, but unrelated
        ({30: 20, 20: 30, 10: 1}, 10, False),  # malformed/reused-PID cycle
        ({}, 10, False),
    ],
)
def test_windows_owner_must_be_present_in_ancestry(
    locks: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    parents: dict[int, int],
    owner: int,
    expected: bool,
) -> None:
    monkeypatch.setattr(locks, "_WINDOWS", True)
    monkeypatch.setattr(locks.os, "getpid", lambda: 30)
    monkeypatch.setattr(locks, "_windows_process_parents", lambda: parents)
    assert locks._owner_is_ancestor(owner) is expected


def test_ancestry_failure_does_not_allow_inherited_bypass(
    locks: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with locks.machine_lock(tmp_path):

        def unavailable(_pid: int) -> bool:
            raise OSError("process snapshot unavailable")

        monkeypatch.setattr(locks, "_owner_is_ancestor", unavailable)
        with pytest.raises(RuntimeError, match="already running"):
            with locks.machine_lock(tmp_path):
                pytest.fail("unverified owner must not bypass contention")


@pytest.mark.parametrize(
    "field,value", [("token", "wrong"), ("token", "non-ASCII é"), ("pid", "1")]
)
def test_mismatched_owner_cannot_bypass(
    locks: ModuleType, tmp_path: Path, field: str, value: str
) -> None:
    with locks.machine_lock(tmp_path):
        env = dict(os.environ)
        env[locks.LOCK_TOKEN_ENV if field == "token" else locks.LOCK_PID_ENV] = value
        assert _child(tmp_path, env=env).returncode == 9


def test_release_after_exception_and_restore_existing_values(
    locks: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(locks.LOCK_TOKEN_ENV, "previous-token")
    monkeypatch.setenv(locks.LOCK_PID_ENV, "123")
    with pytest.raises(ValueError, match="body failed"):
        with locks.machine_lock(tmp_path):
            raise ValueError("body failed")
    assert os.environ[locks.LOCK_TOKEN_ENV] == "previous-token"
    assert os.environ[locks.LOCK_PID_ENV] == "123"
    assert _child(tmp_path).returncode == 0


def test_nested_owner_keeps_outer_lock(locks: ModuleType, tmp_path: Path) -> None:
    clean_env = dict(os.environ)
    with locks.machine_lock(tmp_path):
        token = os.environ[locks.LOCK_TOKEN_ENV]
        with locks.machine_lock(tmp_path):
            assert os.environ[locks.LOCK_TOKEN_ENV] == token
        assert os.environ[locks.LOCK_TOKEN_ENV] == token
        assert _child(tmp_path, env=clean_env).returncode == 9


def test_stale_metadata_does_not_block_or_reuse_token(locks: ModuleType, tmp_path: Path) -> None:
    with locks.machine_lock(tmp_path):
        original = os.environ[locks.LOCK_TOKEN_ENV]
        stale_env = dict(os.environ)
    child = _child(tmp_path, env=stale_env)
    assert child.returncode == 0
    assert json.loads((tmp_path / "update.lock").read_bytes()[1:])["token"] != original


def test_os_releases_lock_when_holder_crashes(locks: ModuleType, tmp_path: Path) -> None:
    process = subprocess.Popen(
        _command(tmp_path, hold=True),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "acquired"
        with pytest.raises(RuntimeError, match="already running"):
            with locks.machine_lock(tmp_path):
                pytest.fail("independent process holds the lock")
        process.terminate()
        process.wait(timeout=10)
        with locks.machine_lock(tmp_path):
            assert os.environ[locks.LOCK_PID_ENV] == str(os.getpid())
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_windows_locks_and_unlocks_exact_byte_zero(
    locks: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def locking(fd: int, mode: int, length: int) -> None:
        calls.append((mode, length, os.lseek(fd, 0, os.SEEK_CUR), os.fstat(fd).st_size))

    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    )
    monkeypatch.setattr(locks, "_WINDOWS", True)
    with locks.machine_lock(tmp_path):
        assert os.environ[locks.LOCK_PID_ENV] == str(os.getpid())
    assert [(mode, length, offset) for mode, length, offset, _ in calls] == [(1, 1, 0), (2, 1, 0)]
    assert all(size >= 1 for _, _, _, size in calls)
