"""Credential transport contracts use synthetic values and no native services."""

from __future__ import annotations

import getpass
import importlib.util
import inspect
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize("value", [" synthetic 'quoted' \\ value ", "é space "])
def test_seed_uses_only_stdin_and_verifies_without_printing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    seed = module("seed-prod-secret")
    monkeypatch.setattr(seed.getpass, "getpass", lambda prompt: value)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    signature = inspect.signature(subprocess.run)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        signature.bind(argv, **kwargs)
        assert value not in repr(argv)
        assert "env" not in kwargs
        assert argv[0] == "/usr/bin/security"
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=(value + "\n").encode())

    monkeypatch.setattr(seed.subprocess, "run", run)
    assert seed.seed("SITE_PASSWORD") is True
    assert calls[0][0] == ["/usr/bin/security", "-i"]
    assert shlex.split(calls[0][1]["input"])[-1] == value
    assert calls[1][0][-1] == "-w"
    assert value not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["", "bad\nline", "bad\rline", "bad\x00value"])
def test_seed_refuses_parser_control_characters_before_keychain(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    seed = module("seed-prod-secret")
    monkeypatch.setattr(seed.getpass, "getpass", lambda prompt: value)
    monkeypatch.setattr(seed.subprocess, "run", lambda *a, **kw: pytest.fail("Keychain called"))
    assert seed.seed("SITE_PASSWORD") is False
    assert seed.seed("UNREVIEWED_NAME") is False


def test_seed_refuses_echo_fallback_and_failed_readback(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = module("seed-prod-secret")

    def unavailable(prompt: str) -> str:
        raise getpass.GetPassWarning("synthetic warning")

    monkeypatch.setattr(seed.getpass, "getpass", unavailable)
    monkeypatch.setattr(seed.subprocess, "run", lambda *a, **kw: pytest.fail("Keychain called"))
    assert seed.seed("SITE_PASSWORD") is False
    monkeypatch.setattr(seed.getpass, "getpass", lambda prompt: "synthetic-marker")
    monkeypatch.setattr(
        seed.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"different\n"),
    )
    assert seed.seed("SITE_PASSWORD") is False


@pytest.fixture
def wrapper(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    # Substitute only the fixed native executable in a disposable script copy.
    # Production has no PATH/env escape hatch for the Keychain executable.
    stub = tmp_path / "security"
    stub.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\n"
        "with open(os.environ['LOOKUPS'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[-2] == os.environ.get('MISSING',''):sys.exit(1)\n"
        "print('synthetic-value')\n"
    )
    stub.chmod(0o700)
    source = (ROOT / "scripts/with-prod-secrets.sh").read_text()
    assert "/usr/bin/security find-generic-password" in source
    path = tmp_path / "wrapper.sh"
    path.write_text(source.replace("/usr/bin/security", shlex.quote(str(stub))))
    lookups = tmp_path / "lookups"
    env = {**os.environ, "LOOKUPS": str(lookups)}
    return path, env, lookups


@pytest.mark.parametrize("options", [["--extra"], ["--extra", "PATH"], ["--bad"], ["--"]])
def test_wrapper_validates_before_credential_reads(
    wrapper: tuple[Path, dict[str, str], Path], options: list[str]
) -> None:
    path, env, lookups = wrapper
    result = subprocess.run(["bash", str(path), *options], env=env, capture_output=True)
    assert result.returncode == 64
    assert not lookups.exists()


def test_wrapper_scopes_extras_preserves_argv_and_exit(
    wrapper: tuple[Path, dict[str, str], Path], tmp_path: Path
) -> None:
    path, env, lookups = wrapper
    child = tmp_path / "child.py"
    child.write_text(
        "import json,os,sys\nassert os.environ['ROADMODEL_IP_SALT']=='synthetic-value'\n"
        "assert os.environ['GOOGLE_API_KEY']=='synthetic-value'\n"
        "print(json.dumps(sys.argv[1:]))\nsys.exit(7)\n"
    )
    args = ["literal $(command)", "two words", ""]
    result = subprocess.run(
        [
            "bash",
            str(path),
            "--extra",
            "ROADMODEL_IP_SALT",
            "--extra",
            "GOOGLE_API_KEY",
            "--extra",
            "ROADMODEL_IP_SALT",
            "--",
            "python3",
            str(child),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 7
    assert json.loads(result.stdout) == args
    names = [json.loads(line)[2] for line in lookups.read_text().splitlines()]
    assert len(names) == len(set(names)) == 11
    assert "roadmodel/POOL_SYNC_REFRESH_TOKEN" not in names


def test_wrapper_default_secret_set_is_unchanged(
    wrapper: tuple[Path, dict[str, str], Path],
) -> None:
    path, env, lookups = wrapper
    result = subprocess.run(
        ["bash", str(path), "python3", "-c", "pass"], env=env, capture_output=True
    )
    assert result.returncode == 0
    names = [json.loads(line)[2] for line in lookups.read_text().splitlines()]
    assert len(names) == len(set(names)) == 10
    assert "roadmodel/ROADMODEL_IP_SALT" not in names
    assert "roadmodel/POOL_SYNC_REFRESH_TOKEN" not in names


@pytest.mark.parametrize("name", ["SITE_PASSWORD", "ROADMODEL_IP_SALT"])
def test_wrapper_missing_secret_never_starts_child(
    wrapper: tuple[Path, dict[str, str], Path], tmp_path: Path, name: str
) -> None:
    path, env, _ = wrapper
    child_marker = tmp_path / "child-started"
    result = subprocess.run(
        ["bash", str(path), "--extra", "ROADMODEL_IP_SALT", "--", "touch", str(child_marker)],
        env={**env, "MISSING": f"roadmodel/{name}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not child_marker.exists()
    assert "synthetic-value" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["timeout", "exit", "missing"])
def test_watcher_notification_data_stays_out_of_argv_and_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    watcher = module("gate-alert-watcher")
    marker = 'synthetic-notification "quoted" \\ data'
    called = False
    signature = inspect.signature(subprocess.run)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        signature.bind(argv, **kwargs)
        assert argv == ["/usr/bin/osascript", "-"]
        assert marker not in repr(argv)
        assert kwargs["input"] == marker
        assert kwargs["text"] is True and kwargs["check"] is True
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 15, output=marker)
        if failure == "exit":
            raise subprocess.CalledProcessError(1, argv, output=marker)
        raise OSError(marker)

    monkeypatch.setattr(watcher.subprocess, "run", run)
    watcher._osa(marker)
    assert called
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[gate-watcher] osascript failed\n"


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        "42",
        '"marker"',
        "not JSON",
        '{"attempts":{}}',
        '{"ua":[]}',
        '{"lock_seconds":"bad"}',
    ],
)
def test_watcher_malformed_event_has_bounded_fixed_fallback(raw: str) -> None:
    assert module("gate-alert-watcher").format_event(raw) == (
        "Invalid gate alert event",
        "A gate alert could not be decoded.",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://queue.test",
        "https://user:pass@queue.test",
        "https://queue.test/path",
        "https://queue.test?q=x",
        "https://queue.test#x",
        "https://queue.test:444",
        "https://queue.test\n",
        "rediss://queue.test:80",
        "file:///tmp/queue",
        "https://bad..test",
    ],
)
def test_watcher_rejects_ambiguous_rest_origins(url: str) -> None:
    assert module("gate-alert-watcher")._rest_base(url) == ""


@pytest.mark.parametrize(
    "url",
    [
        "https://queue.test",
        "https://queue.test/",
        "https://queue.test:443",
        "rediss://default:synthetic@queue.test:6379",
    ],
)
def test_watcher_canonical_rest_origin(url: str) -> None:
    assert module("gate-alert-watcher")._rest_base(url) == "https://queue.test"
