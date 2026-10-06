"""Fleet dispatch must preserve exact paths and keep check/dry runs read-only."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def fleet() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "upgrade_fleet.py"
    spec = importlib.util.spec_from_file_location("upgrade_fleet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _config(tmp_path: Path, **updates: object) -> Path:
    peer = {
        "host": "user@work-pc",
        "platform": "windows",
        "python": r"C:\Program Files\Python\python.exe",
        "projects": [r"E:\Code\Project A", r"E:\Code\Project B"],
        **updates,
    }
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps({"version": 1, "peers": {"pc": peer}}), encoding="utf-8")
    return path


def test_missing_config_is_noop(fleet: ModuleType, tmp_path: Path) -> None:
    assert fleet.run_fleet(tmp_path / "missing.json") == ([], True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("host", ["-oProxyCommand=evil", "good;touch x", "good\nmalicious", "a b"])
def test_hosts_cannot_inject_ssh_options(fleet: ModuleType, tmp_path: Path, host: str) -> None:
    lines, ok = fleet.run_fleet(_config(tmp_path, host=host))
    assert not ok
    assert "invalid configuration" in lines[0]
    assert host not in lines[0]


@pytest.mark.parametrize(
    "updates",
    [
        {"platform": "unix"},
        {"python": "python"},
        {"projects": "E:\\Code"},
        {"projects": []},
        {"projects": [123]},
        {"launcher": "relative.py"},
        {"unknown": True},
        {"python": 'C:\\bad"\\python.exe'},
    ],
)
def test_invalid_peer_is_rejected(
    fleet: ModuleType, tmp_path: Path, updates: dict[str, object]
) -> None:
    assert fleet.run_fleet(_config(tmp_path, **updates))[1] is False


@pytest.mark.parametrize(
    "data",
    [
        "{",
        "[]",
        '{"version":true,"peers":{}}',
        '{"version":1,"version":1,"peers":{}}',
        '{"version":1,"peers":[]}',
    ],
)
def test_invalid_config_is_reported(fleet: ModuleType, tmp_path: Path, data: str) -> None:
    path = tmp_path / "fleet.json"
    path.write_text(data)
    assert fleet.run_fleet(path)[1] is False


def test_dry_run_opens_no_ssh_and_changes_nothing(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    before = config.read_bytes()
    monkeypatch.setattr(fleet.subprocess, "run", lambda *_a, **_k: pytest.fail("must not open SSH"))
    lines, ok = fleet.run_fleet(config, dry_run=True)
    assert ok and "would upgrade 2" in lines[0]
    assert config.read_bytes() == before
    assert list(tmp_path.iterdir()) == [config]


def test_posix_command_keeps_metacharacters_as_data(fleet: ModuleType, tmp_path: Path) -> None:
    project = "/srv/space and 'quote';$(touch nope) `echo x`"
    peer = fleet.load_peers(
        _config(tmp_path, host="posix", platform="posix", python="/bin/python3", projects=[project])
    )[0]
    command = fleet.build_command(peer)
    assert command[-2] == "posix" and command[-3] == "--"
    python, flag, code = shlex.split(command[-1])
    assert python == "/bin/python3" and flag == "-c"
    payload = code.split("b64decode('", 1)[1].split("'", 1)[0]
    data = json.loads(base64.b64decode(payload))
    assert data == {
        "launcher": "~/.config/roadmodel/update_projects.py",
        "args": ["--local-only", "--skip-roadmap-refresh", "--log", "--add", project],
    }
    assert project not in code


def test_windows_command_is_encoded_and_quotes_executable(
    fleet: ModuleType, tmp_path: Path
) -> None:
    python = r"C:\O'Brien;$(not-a-command)\python.exe"
    project = r"E:\space & 'quote';$(not-a-command)"
    peer = fleet.load_peers(_config(tmp_path, python=python, projects=[project]))[0]
    command = fleet.build_command(peer)
    script = base64.b64decode(command[-1].split()[-1]).decode("utf-16-le")
    assert "& 'C:\\O''Brien;$(not-a-command)\\python.exe' '-c'" in script
    assert "$ErrorActionPreference='Stop'" in script
    assert "exit $LASTEXITCODE" in script
    assert project not in script
    # Recover the doubled-quote Python literal, then inspect its JSON payload.
    code = script.split(" '-c' '", 1)[1].rsplit("';if ", 1)[0].replace("''", "'")
    payload = code.split("b64decode('", 1)[1].split("'", 1)[0]
    assert json.loads(base64.b64decode(payload))["args"][-1] == project


def test_posix_bootstrap_runs_installed_launcher_and_sibling(
    fleet: ModuleType, tmp_path: Path
) -> None:
    launcher = tmp_path / "launcher's folder" / "updater.py"
    launcher.parent.mkdir()
    launcher.write_text(
        "import json, sys, sibling\nprint(json.dumps([sys.argv[1:], sibling.VALUE]))\n"
    )
    (launcher.parent / "sibling.py").write_text("VALUE = 'loaded'\n")
    project = "/srv/space and 'quote';$(touch nope)"
    peer = fleet.load_peers(
        _config(
            tmp_path,
            host="posix",
            platform="posix",
            python=sys.executable,
            launcher=str(launcher),
            projects=[project],
        )
    )[0]
    argv = shlex.split(fleet.build_command(peer, check=True)[-1])
    result = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(result.stdout) == [["--local-only", "--check", project], "loaded"]


def test_check_passes_projects_without_registration_or_logging(
    fleet: ModuleType, tmp_path: Path
) -> None:
    peer = fleet.load_peers(_config(tmp_path))[0]
    assert fleet._updater_args(peer, sync_only=True, check=True) == [
        "--local-only",
        "--check",
        *peer.projects,
    ]


def test_sync_only_registers_and_stops_recursion(fleet: ModuleType, tmp_path: Path) -> None:
    peer = fleet.load_peers(_config(tmp_path))[0]
    args = fleet._updater_args(peer, sync_only=True, check=False)
    assert args == ["--local-only", "--sync-only", "--log", "--add", *peer.projects]


@pytest.mark.parametrize("returncode", [0, 1, 2, 255])
def test_result_is_accurate_and_private_output_is_suppressed(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    calls = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(fleet.subprocess, "run", run)
    lines, ok = fleet.run_fleet(_config(tmp_path))
    assert ok == (returncode == 0)
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "BatchMode=yes" in command and "StrictHostKeyChecking=yes" in command
    assert "ConnectTimeout=10" in command
    assert kwargs["timeout"] == fleet.EXECUTION_TIMEOUT_SECONDS
    assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    assert "E:\\Code" not in lines[0]


@pytest.mark.parametrize(
    "error", [OSError("no executable"), subprocess.TimeoutExpired("ssh", 1800)]
)
def test_connection_failures_are_reported(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def run(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(fleet.subprocess, "run", run)
    lines, ok = fleet.run_fleet(_config(tmp_path))
    assert not ok and "FAILED" in lines[0]


def test_bad_peer_does_not_prevent_next_peer(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    data = json.loads(config.read_text())
    data["peers"]["other"] = dict(data["peers"]["pc"], host="other")
    config.write_text(json.dumps(data))
    results = iter([255, 0])
    monkeypatch.setattr(
        fleet.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=next(results))
    )
    lines, ok = fleet.run_fleet(config)
    assert not ok and len(lines) == 2
    assert "pc: FAILED" in lines[0] and "other: OK" in lines[1]


def _with_rules(tmp_path: Path, content: bytes = b"Shared rules.\n") -> tuple[Path, Path]:
    config = _config(tmp_path)
    source = tmp_path / "source-rules.md"
    source.write_bytes(content)
    data = json.loads(config.read_text())
    data["global_rules_source"] = str(source)
    config.write_text(json.dumps(data))
    return config, source


def _snapshot(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def _run_rules(
    fleet: ModuleType,
    tmp_path: Path,
    content: bytes,
    *,
    check: bool = False,
    digest: str | None = None,
    concurrent_edit: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    home = tmp_path / "remote-home"
    home.mkdir(exist_ok=True)
    launcher = tmp_path / "fake-updater.py"
    launcher.write_text("import sys\nprint('updater executed')\nsys.exit(0)\n")
    peer = fleet.Peer("remote", "unused", "posix", sys.executable, str(launcher), ("/srv/project",))
    rules = {
        "text": content.decode("utf-8"),
        "sha256": digest or hashlib.sha256(content).hexdigest(),
    }
    command = shlex.split(fleet.build_command(peer, check=check, stdin_script=True)[-1])
    script = fleet.build_input(peer, rules, check=check)
    if concurrent_edit is not None:
        # A competing editor changes the destination while our replacement is
        # being staged. Instrument the child filesystem boundary, so the real
        # remote bootstrap still performs every comparison and write itself.
        race = (
            "import os\nfrom pathlib import Path\n"
            "_original_fsync = os.fsync\n"
            "def _concurrent_editor(fd):\n"
            "    _original_fsync(fd)\n"
            "    destination = Path.home() / '.claude' / 'CLAUDE.md'\n"
            "    destination.parent.mkdir(parents=True, exist_ok=True)\n"
            f"    destination.write_bytes({concurrent_edit!r})\n"
            "    os.fsync = _original_fsync\n"
            "os.fsync = _concurrent_editor\n"
        )
        script = race.encode("utf-8") + script
    return subprocess.run(
        command,
        input=script,
        env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_global_rules_seed_then_update_unchanged_replica(fleet: ModuleType, tmp_path: Path) -> None:
    original = "Rule with unicode café.\r\nKeep exact newlines.\r\n".encode()
    assert _run_rules(fleet, tmp_path, original).returncode == 0
    home = tmp_path / "remote-home"
    target = home / ".claude" / "CLAUDE.md"
    state_file = home / ".config" / "roadmodel" / "fleet-global-rules.json"
    assert target.read_bytes() == original
    assert json.loads(state_file.read_text())["sha256"] == hashlib.sha256(original).hexdigest()
    revised = b"New global rules.\n"
    result = _run_rules(fleet, tmp_path, revised)
    assert result.returncode == 0 and result.stdout == b"updater executed\n"
    assert target.read_bytes() == revised
    assert json.loads(state_file.read_text())["sha256"] == hashlib.sha256(revised).hexdigest()
    assert not list(home.rglob(".fleet-*"))


def test_identical_rules_adopt_state_without_rewriting_target(
    fleet: ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "remote-home" / ".claude" / "CLAUDE.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"Identical\n")
    before = target.stat().st_mtime_ns
    assert _run_rules(fleet, tmp_path, target.read_bytes()).returncode == 0
    assert target.stat().st_mtime_ns == before
    assert (target.parents[1] / ".config" / "roadmodel" / "fleet-global-rules.json").is_file()


@pytest.mark.parametrize("tracked", [False, True])
def test_edit_while_staging_preserves_concurrent_content_and_prior_state(
    fleet: ModuleType, tmp_path: Path, tracked: bool
) -> None:
    home = tmp_path / "remote-home"
    state = home / ".config" / "roadmodel" / "fleet-global-rules.json"
    if tracked:
        assert _run_rules(fleet, tmp_path, b"Originally applied rules\n").returncode == 0
    before_state = state.read_bytes() if state.exists() else None
    other_edit = b"A concurrent user's new rule\n"
    result = _run_rules(fleet, tmp_path, b"Incoming revision\n", concurrent_edit=other_edit)
    assert result.returncode == fleet.GLOBAL_RULES_CONFLICT
    assert result.stdout == result.stderr == b""
    assert (home / ".claude" / "CLAUDE.md").read_bytes() == other_edit
    assert (state.read_bytes() if state.exists() else None) == before_state
    assert not list(home.rglob(".fleet-*"))


@pytest.mark.parametrize("tracked", [False, True])
def test_divergent_rules_preserve_remote_and_coordinator(
    fleet: ModuleType, tmp_path: Path, tracked: bool
) -> None:
    incoming = b"Coordinator's next rules.\n"
    _, source = _with_rules(tmp_path, incoming)
    home = tmp_path / "remote-home"
    target = home / ".claude" / "CLAUDE.md"
    if tracked:
        assert _run_rules(fleet, tmp_path, b"Previous applied rules.\n").returncode == 0
    else:
        target.parent.mkdir(parents=True)
    target.write_bytes(b"PC-only new rules.\n")
    before = _snapshot(home)
    result = _run_rules(fleet, tmp_path, incoming)
    assert result.returncode == fleet.GLOBAL_RULES_CONFLICT
    assert result.stdout == result.stderr == b""
    assert _snapshot(home) == before
    assert source.read_bytes() == incoming


@pytest.mark.parametrize("existing", [None, b"Different\n", b"Expected\n"])
def test_global_rules_check_is_readonly(
    fleet: ModuleType, tmp_path: Path, existing: bytes | None
) -> None:
    home = tmp_path / "remote-home"
    home.mkdir()
    if existing is not None:
        target = home / ".claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_bytes(existing)
    before = _snapshot(home)
    result = _run_rules(fleet, tmp_path, b"Expected\n", check=True)
    assert result.returncode == (0 if existing == b"Expected\n" else fleet.GLOBAL_RULES_DRIFT)
    assert _snapshot(home) == before


def test_corrupt_replication_state_fails_without_changes(fleet: ModuleType, tmp_path: Path) -> None:
    assert _run_rules(fleet, tmp_path, b"Original\n").returncode == 0
    home = tmp_path / "remote-home"
    state_file = home / ".config" / "roadmodel" / "fleet-global-rules.json"
    state_file.write_text("corrupt private state")
    before = _snapshot(home)
    result = _run_rules(fleet, tmp_path, b"New\n")
    assert result.returncode == fleet.GLOBAL_RULES_ERROR
    assert _snapshot(home) == before and result.stderr == b""


def test_payload_digest_checked_before_writing(fleet: ModuleType, tmp_path: Path) -> None:
    result = _run_rules(fleet, tmp_path, b"Private rules", digest="0" * 64)
    assert result.returncode == fleet.GLOBAL_RULES_ERROR
    assert not list((tmp_path / "remote-home").iterdir())


def test_large_private_rules_travel_only_on_stdin(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"Very private rule; $(never execute) & quote ' \n" * 1000
    config, source = _with_rules(tmp_path, content)
    calls = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(fleet.subprocess, "run", run)
    lines, ok = fleet.run_fleet(config, sync_only=True)
    assert ok
    command, kwargs = calls[0]
    assert len(command[-1]) < 8191
    assert "stdin" not in kwargs and isinstance(kwargs["input"], bytes)
    assert "Very private" not in str(command) + str(lines)
    script = kwargs["input"].decode()
    encoded = script.split("b64decode('", 1)[1].split("'", 1)[0]
    payload = json.loads(base64.b64decode(encoded))
    assert payload["global_rules"]["text"].encode() == source.read_bytes()
    assert payload["global_rules"]["sha256"] == hashlib.sha256(content).hexdigest()


def test_rules_dry_run_writes_nothing_and_never_connects(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _with_rules(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(fleet.subprocess, "run", lambda *_a, **_k: pytest.fail("no SSH in dry run"))
    assert fleet.run_fleet(config, dry_run=True)[1]
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("source_value", ["relative.md", 42, None])
def test_invalid_global_rules_source_rejected(
    fleet: ModuleType, tmp_path: Path, source_value: object
) -> None:
    config = _config(tmp_path)
    data = json.loads(config.read_text())
    data["global_rules_source"] = source_value
    config.write_text(json.dumps(data))
    assert fleet.run_fleet(config, dry_run=True)[1] is False


@pytest.mark.parametrize("invalid", ["missing", "non-utf8"])
def test_unreadable_source_fails_before_connecting(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    config, source = _with_rules(tmp_path)
    if invalid == "missing":
        source.unlink()
    else:
        source.write_bytes(b"\xff")
    monkeypatch.setattr(fleet.subprocess, "run", lambda *_a, **_k: pytest.fail("invalid source"))
    lines, ok = fleet.run_fleet(config)
    assert not ok and "invalid configuration" in lines[0]


@pytest.mark.parametrize("code,word", [(73, "conflict"), (74, "differ"), (75, "validate")])
def test_remote_rule_failures_have_specific_private_status(
    fleet: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, word: str
) -> None:
    config, _ = _with_rules(tmp_path, b"A private source rule")
    monkeypatch.setattr(fleet.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=code))
    lines, ok = fleet.run_fleet(config)
    assert not ok and word in lines[0]
    assert "private source" not in lines[0]
