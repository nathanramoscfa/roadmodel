"""Exercise updater dispatch and local/fleet failure propagation in isolation."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def updater(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    spec = importlib.util.spec_from_file_location(
        "update_shared_integration", ROOT / "scripts" / "update_projects.py"
    )
    assert spec and spec.loader
    up = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = up
    spec.loader.exec_module(up)
    real_home = Path.home()
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    # Constants were initialized at module load. Redirect every user-home
    # path before exercising main, in addition to Path.home()/expanduser().
    for name, value in vars(up).items():
        if isinstance(value, Path) and value.is_relative_to(real_home):
            monkeypatch.setattr(up, name, home / value.relative_to(real_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(up, "tolerate_unencodable_output", lambda: None)
    monkeypatch.setattr(up, "should_self_update", lambda: True)
    monkeypatch.setattr(up, "detect_agents", lambda: ["codex"])

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("readonly/sync-only mode invoked package, command, model or configuration work")

    for name in (
        "self_update",
        "update_project",
        "update_mcp_env",
        "refresh_commands",
        "sync_agent_runtime",
        "sync_user_context",
        "refresh_roadmaps",
        "install_schedule",
        "uninstall_schedule",
        "configure_context_sync",
        "_open_log",
    ):
        monkeypatch.setattr(up, name, forbidden)
    calls: list[tuple[str, object]] = []

    def shared(entries: list[object], *_args: object, **kwargs: object) -> bool:
        calls.append(("shared", ([entry.path for entry in entries], kwargs)))
        return True

    def peers(args: object) -> bool:
        calls.append(("peers", args))
        return True

    original_shared = up.sync_shared_context
    original_peers = up.upgrade_peers
    monkeypatch.setattr(up, "sync_shared_context", shared)
    monkeypatch.setattr(up, "upgrade_peers", peers)
    return SimpleNamespace(
        up=up,
        home=home,
        project=project,
        calls=calls,
        original_shared=original_shared,
        original_peers=original_peers,
    )


@pytest.mark.parametrize("flag", ["--check", "--sync-only"])
def test_offline_modes_never_upgrade_or_call_models(updater: SimpleNamespace, flag: str) -> None:
    assert updater.up.main([flag, str(updater.project)]) == 0
    assert [name for name, _ in updater.calls] == ["shared", "peers"]
    paths, kwargs = updater.calls[0][1]
    assert paths == [updater.project]
    assert kwargs["check"] == (flag == "--check")
    files = [p.relative_to(updater.home).as_posix() for p in updater.home.rglob("*") if p.is_file()]
    assert files == ([] if flag == "--check" else [".config/roadmodel/update.lock"])


def test_busy_updater_does_not_begin_work(updater, monkeypatch, capsys):
    def busy(_config):
        raise RuntimeError("Another roadmodel updater is already running on this machine")

    monkeypatch.setattr(updater.up, "_support", lambda _name: SimpleNamespace(machine_lock=busy))
    assert updater.up.main(["--sync-only", str(updater.project)]) == 1
    assert not updater.calls
    assert "already running" in capsys.readouterr().err


@pytest.mark.parametrize(
    "flags",
    [
        ["--add", "ignored"],
        ["--install-schedule"],
        ["--uninstall-schedule"],
        ["--context-sync", "owner/private"],
        ["--auto-refresh", "on"],
        ["--commands-only"],
    ],
)
def test_check_rejects_configuration_mutation(updater: SimpleNamespace, flags: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        updater.up.main(["--check", *flags])
    assert exc.value.code == 2
    assert not list(updater.home.iterdir())
    assert not updater.calls


def test_check_log_does_not_write_a_log(updater: SimpleNamespace) -> None:
    try:
        result = updater.up.main(["--check", "--log", str(updater.project)])
    except SystemExit as exc:
        # Rejecting the contradictory flags or treating logging as disabled
        # are both safe; opening a log before validation is not.
        assert exc.code == 2
    else:
        assert result == 0
    assert not list(updater.home.iterdir())


def test_sync_only_cannot_bypass_into_commands_only(updater: SimpleNamespace) -> None:
    with pytest.raises(SystemExit) as exc:
        updater.up.main(["--sync-only", "--commands-only", str(updater.project)])
    assert exc.value.code == 2
    assert not updater.calls


def test_dry_run_add_does_not_mutate_registry(updater: SimpleNamespace) -> None:
    registry = updater.home / "new-config" / "projects.txt"
    assert (
        updater.up.main(
            [
                "--sync-only",
                "--dry-run",
                "--projects-file",
                str(registry),
                "--add",
                str(updater.project),
            ]
        )
        == 0
    )
    assert not registry.parent.exists()
    paths, kwargs = updater.calls[0][1]
    assert paths == [updater.project] and kwargs["dry_run"] is True


def test_sync_only_add_registers_project(updater: SimpleNamespace) -> None:
    registry = updater.home / "config" / "projects.txt"
    assert (
        updater.up.main(
            ["--sync-only", "--projects-file", str(registry), "--add", str(updater.project)]
        )
        == 0
    )
    assert registry.read_text().splitlines() == [str(updater.project.resolve())]


def test_fleet_still_runs_after_local_context_failure(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updater.up, "sync_shared_context", lambda *_a, **_k: False)
    assert updater.up.main(["--sync-only", str(updater.project)]) == 1
    assert [name for name, _ in updater.calls] == ["peers"]


def test_peer_failure_sets_exit_status(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updater.up, "upgrade_peers", lambda *_a, **_k: False)
    assert updater.up.main(["--check", str(updater.project)]) == 1


def test_fleet_still_runs_after_local_package_failure(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    up = updater.up
    monkeypatch.setattr(up, "should_self_update", lambda: False)
    monkeypatch.setattr(up, "sync_user_context", lambda **_kwargs: [])
    monkeypatch.setattr(up, "_roadmodel_mcp_command", lambda: None)
    monkeypatch.setattr(up, "update_mcp_env", lambda *_args, **_kwargs: ("unchanged", True))
    monkeypatch.setattr(
        up,
        "update_project",
        lambda entry, **_kwargs: up.Result(entry, None, "fixture missing env", error="missing env"),
    )
    assert up.main(["--no-commands", "--no-parity", str(updater.project)]) == 1
    assert [name for name, _ in updater.calls] == ["peers"]


def test_local_only_never_imports_fleet(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("local-only mode must not load fleet support")

    monkeypatch.setattr(updater.up, "_support", forbidden)
    monkeypatch.setattr(updater.up, "upgrade_peers", updater.original_peers)
    assert updater.up.main(["--check", "--local-only", str(updater.project)]) == 0


def test_fleet_receives_modes_and_private_config(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def run_fleet(path: Path, **kwargs: object) -> tuple[list[str], bool]:
        calls.append((path, kwargs))
        return ["fleet peer: OK"], True

    monkeypatch.setattr(updater.up, "_support", lambda name: SimpleNamespace(run_fleet=run_fleet))
    args = SimpleNamespace(local_only=False, dry_run=True, sync_only=True, check=False)
    assert updater.original_peers(args)
    assert calls == [
        (
            updater.home / ".config" / "roadmodel" / "fleet.json",
            {"dry_run": True, "sync_only": True, "check": False},
        )
    ]


def test_project_failure_does_not_skip_other_contexts(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []
    other = updater.project.with_name("other")
    other.mkdir()

    def sync_project(path: Path, **_kwargs: object) -> tuple[list[str], bool]:
        seen.append(path)
        if path == updater.project:
            raise OSError("fixture project inaccessible")
        return ["context OK"], True

    helpers = {
        "agent_rules": SimpleNamespace(sync_global_rules=lambda *_a, **_k: ([], True)),
        "agent_context": SimpleNamespace(sync_project=sync_project),
    }
    monkeypatch.setattr(updater.up, "_support", helpers.__getitem__)
    entries = [updater.up.Entry(updater.project), updater.up.Entry(other)]
    assert updater.original_shared(entries, ["codex"], check=True) is False
    assert seen == [updater.project, other]


def test_support_helpers_load_from_installed_siblings(
    updater: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "site-packages" / "roadmodel"
    package.mkdir(parents=True)
    monkeypatch.setattr(updater.up, "__file__", str(package / "update_projects.py"))
    for name in updater.up.SUPPORT_MODULES:
        shutil.copyfile(ROOT / "scripts" / f"{name}.py", package / f"{name}.py")
        helper = updater.up._support(name)
        assert isinstance(helper, ModuleType)
        assert Path(helper.__file__).parent == package


def test_missing_helper_is_explicit(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updater.up, "__file__", str(updater.home / "update_projects.py"))
    with pytest.raises(RuntimeError, match="Missing updater companion"):
        updater.up._support("agent_context")


def test_install_launcher_copies_all_companions(
    updater: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(updater.up.DELEGATED_ENV, raising=False)
    launcher = updater.home / "installed" / "update_projects.py"
    monkeypatch.setattr(updater.up, "LAUNCHER", launcher)
    assert updater.up._install_launcher(False) == launcher
    assert launcher.is_file()
    for name in updater.up.SUPPORT_MODULES:
        assert (launcher.parent / f"{name}.py").read_bytes() == (
            ROOT / "scripts" / f"{name}.py"
        ).read_bytes()


def released_child(updater, monkeypatch):
    """An old parent copied only its newly installed release's updater."""
    up = updater.up
    package = updater.home / "site-packages/roadmodel"
    package.mkdir(parents=True)
    for name in ("update_projects", *up.SUPPORT_MODULES):
        shutil.copyfile(ROOT / "scripts" / f"{name}.py", package / f"{name}.py")
    up.LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package / "update_projects.py", up.LAUNCHER)
    monkeypatch.setattr(up, "__file__", str(package / "update_projects.py"))
    monkeypatch.setattr(up, "__package__", "roadmodel")
    monkeypatch.setattr(up, "should_self_update", lambda: False)
    monkeypatch.setenv(up.DELEGATED_ENV, sys.executable)
    monkeypatch.setattr(up, "sync_user_context", lambda **_kwargs: [])
    monkeypatch.setattr(up, "_roadmodel_mcp_command", lambda: None)
    monkeypatch.setattr(up, "update_mcp_env", lambda *_args, **_kwargs: ("unchanged", True))
    monkeypatch.setattr(
        up,
        "update_project",
        lambda entry, **_kwargs: up.Result(
            entry, up.Env("venv", ".venv", entry.path / ".venv"), "fixture", ok=True
        ),
    )
    return package


def test_first_delegated_release_run_repairs_legacy_launchers_missing_companions(
    updater, monkeypatch
):
    up = updater.up
    package = released_child(updater, monkeypatch)
    assert all(not up.LAUNCHER.with_name(f"{name}.py").exists() for name in up.SUPPORT_MODULES)
    assert up.main(["--no-commands", "--no-parity", str(updater.project)]) == 0
    for name in ("update_projects", *up.SUPPORT_MODULES):
        assert (
            up.LAUNCHER.with_name(f"{name}.py").read_bytes()
            == (package / f"{name}.py").read_bytes()
        )
    # The repaired offline launcher resolves companions itself, without pip or
    # a second self-update. This is the behavior the legacy parent omitted.
    monkeypatch.setattr(up, "__file__", str(up.LAUNCHER))
    monkeypatch.setattr(up, "__package__", "")
    assert up.main(["--sync-only", str(updater.project)]) == 0
    assert [name for name, _ in updater.calls].count("shared") == 1


@pytest.mark.parametrize("flag", ["--check", "--dry-run", "--help", "--self-check", "--sync-only"])
def test_delegated_nonupgrade_modes_do_not_install_release_files(updater, monkeypatch, flag):
    up = updater.up
    released_child(updater, monkeypatch)
    before = up.LAUNCHER.read_bytes()
    args = [flag, "--no-commands", "--no-parity", str(updater.project)]
    if flag == "--help":
        with pytest.raises(SystemExit) as exc:
            up.main(args)
        assert exc.value.code == 0
    else:
        assert up.main(args) == 0
    assert up.LAUNCHER.read_bytes() == before
    assert all(not up.LAUNCHER.with_name(f"{name}.py").exists() for name in up.SUPPORT_MODULES)


def test_source_checkout_full_run_does_not_install_itself(updater, monkeypatch):
    up = updater.up
    released_child(updater, monkeypatch)
    monkeypatch.setattr(up, "__package__", "")
    monkeypatch.setattr(up, "__file__", str(ROOT / "scripts/update_projects.py"))
    assert up.main(["--no-commands", "--no-parity", str(updater.project)]) == 0
    assert all(not up.LAUNCHER.with_name(f"{name}.py").exists() for name in up.SUPPORT_MODULES)


def test_downloaded_launcher_without_lock_helper_can_reach_release_handover(updater, monkeypatch):
    up = updater.up
    up.LAUNCHER.parent.mkdir(parents=True)
    up.LAUNCHER.write_text("legacy bootstrap")
    monkeypatch.setattr(up, "__file__", str(up.LAUNCHER))
    handed = []
    monkeypatch.setattr(up, "self_update", lambda raw, _registry: handed.append(raw) or 7)
    assert up.main(["--new-release-flag"]) == 7
    assert handed == [["--new-release-flag"]]


def test_missing_lock_helper_never_turns_sync_only_into_full_upgrade(updater, monkeypatch, capsys):
    up = updater.up
    monkeypatch.setattr(up, "__file__", str(up.LAUNCHER))
    assert up.main(["--sync-only", str(updater.project)]) == 1
    assert "Missing updater companion" in capsys.readouterr().err
    assert not updater.calls
