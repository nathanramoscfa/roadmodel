"""The updater keeps each project checkout on its default branch current.

On 2026-10-25 the operator opened a roadmap whose new layout was merged on
GitHub and still saw the old one: the checkout had not pulled. The updater now
fast-forwards every registered checkout that sits on its default branch, every
15 minutes and at the end of each run (update_projects.sync_checkout), and never
anything that could lose work: a feature branch, local commits, an operation
in progress, or uncommitted changes to a file the update changes (regenerated
planning/ kit files excepted).

Each test drives real git: a bare origin, a clone that pushes, and the
operator's checkout.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


up_module = _load("update_projects")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", name)


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """(the operator's checkout, a clone that pushes to the same origin)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    _commit(seed, "docs.md", "v1\n")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    return checkout, seed


def _advance(seed: Path, name: str = "docs.md", text: str = "v2\n") -> None:
    _commit(seed, name, text)
    _git(seed, "push", "-q", "origin", "HEAD:main")


def test_a_checkout_behind_on_main_is_fast_forwarded(repos: tuple[Path, Path]) -> None:
    checkout, seed = repos
    _advance(seed)
    got = up_module.sync_checkout(checkout)
    assert got.state == "updated" and "fast-forwarded 1 commit(s)" in got.detail
    assert (checkout / "docs.md").read_text(encoding="utf-8") == "v2\n"
    assert up_module.sync_checkout(checkout).state == "current"


def test_untracked_files_and_unrelated_edits_survive(repos: tuple[Path, Path]) -> None:
    checkout, seed = repos
    _commit(seed, "other.md", "x\n")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    _git(checkout, "pull", "-q")
    _advance(seed)
    (checkout / "scratch.txt").write_text("mine\n", encoding="utf-8")
    (checkout / "other.md").write_text("edited\n", encoding="utf-8")
    assert up_module.sync_checkout(checkout).state == "updated"
    assert (checkout / "scratch.txt").read_text(encoding="utf-8") == "mine\n"
    assert (checkout / "other.md").read_text(encoding="utf-8") == "edited\n"
    assert (checkout / "docs.md").read_text(encoding="utf-8") == "v2\n"


def test_an_uncommitted_edit_to_a_changed_file_blocks_and_is_kept(
    repos: tuple[Path, Path],
) -> None:
    checkout, seed = repos
    _advance(seed)
    (checkout / "docs.md").write_text("my edit\n", encoding="utf-8")
    got = up_module.sync_checkout(checkout)
    assert got.state == "skipped" and "local changes block a fast-forward" in got.detail
    assert (checkout / "docs.md").read_text(encoding="utf-8") == "my edit\n"


def test_regenerated_kit_edits_give_way_and_other_edits_do_not(
    repos: tuple[Path, Path],
) -> None:
    """A merged roadmap refresh commits its kit export, and the checkout holds
    the daily run's newer one: only regenerated text differs (2026-10-29)."""
    checkout, seed = repos
    (seed / "planning").mkdir()
    _commit(seed, "planning/model-selector.txt", "speed 141.5\n")
    _commit(seed, "planning/user-context.md", "mine\n")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    _git(checkout, "pull", "-q")
    _commit(seed, "planning/model-selector.txt", "speed 130.0\n")
    _advance(seed, "phase01-roadmap.md", "Status: Complete\n")
    (checkout / "planning" / "model-selector.txt").write_text("speed 121.8\n", encoding="utf-8")
    (checkout / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    dry = up_module.sync_checkout(checkout, dry_run=True)
    assert "1 regenerated planning/ kit file(s)" in dry.detail
    assert (checkout / "planning" / "model-selector.txt").read_text() == "speed 121.8\n"

    got = up_module.sync_checkout(checkout)
    assert got.state == "updated" and "fast-forwarded 2 commit(s)" in got.detail
    assert "1 regenerated planning/ kit file(s) took the merged copy" in got.detail
    assert (checkout / "planning" / "model-selector.txt").read_text() == "speed 130.0\n"
    assert (checkout / "phase01-roadmap.md").exists()
    assert (checkout / "scratch.txt").read_text() == "untracked\n"

    # A kit clash beside any other clash: nothing gives way.
    _commit(seed, "planning/model-selector.txt", "speed 99.0\n")
    _advance(seed)
    (checkout / "planning" / "model-selector.txt").write_text("speed 98.0\n", encoding="utf-8")
    (checkout / "docs.md").write_text("my edit\n", encoding="utf-8")
    got = up_module.sync_checkout(checkout)
    assert got.state == "skipped" and "local changes block" in got.detail
    assert (checkout / "planning" / "model-selector.txt").read_text() == "speed 98.0\n"
    _git(checkout, "checkout", "--", "docs.md", "planning/model-selector.txt")
    _git(checkout, "pull", "-q")

    # The personal user-context copy never gives way.
    _advance(seed, "planning/user-context.md", "theirs\n")
    (checkout / "planning" / "user-context.md").write_text("my edit\n", encoding="utf-8")
    got = up_module.sync_checkout(checkout)
    assert got.state == "skipped"
    assert (checkout / "planning" / "user-context.md").read_text() == "my edit\n"


def test_a_feature_branch_is_left_alone(repos: tuple[Path, Path]) -> None:
    checkout, seed = repos
    _git(checkout, "checkout", "-q", "-b", "feature/phase7-step2")
    _advance(seed)
    head = _git(checkout, "rev-parse", "HEAD")
    got = up_module.sync_checkout(checkout)
    assert got.state == "skipped" and "on feature/phase7-step2" in got.detail
    assert _git(checkout, "rev-parse", "HEAD") == head


def test_local_commits_on_main_are_not_touched(repos: tuple[Path, Path]) -> None:
    checkout, seed = repos
    _commit(checkout, "local.md", "unpushed\n")
    _advance(seed)
    head = _git(checkout, "rev-parse", "HEAD")
    got = up_module.sync_checkout(checkout)
    assert got.state == "skipped" and "1 local commit(s)" in got.detail
    assert _git(checkout, "rev-parse", "HEAD") == head


def test_an_operation_in_progress_is_left_alone(repos: tuple[Path, Path]) -> None:
    checkout, seed = repos
    _advance(seed)
    (checkout / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
    got = up_module.sync_checkout(checkout)
    assert got.state == "skipped" and "in progress" in got.detail


def test_dry_run_changes_nothing(repos: tuple[Path, Path]) -> None:
    checkout, seed = repos
    _advance(seed)
    head = _git(checkout, "rev-parse", "HEAD")
    got = up_module.sync_checkout(checkout, dry_run=True)
    assert got.state == "updated" and got.detail.startswith("would fast-forward")
    assert _git(checkout, "rev-parse", "HEAD") == head


def test_a_folder_that_is_not_a_checkout_or_cannot_fetch(tmp_path: Path) -> None:
    assert up_module.sync_checkout(tmp_path).state == "skipped"
    lone = tmp_path / "lone"
    subprocess.run(["git", "init", "-q", "-b", "main", str(lone)], check=True)
    _commit(lone, "a.md", "a\n")
    _git(lone, "remote", "add", "origin", str(tmp_path / "missing.git"))
    _git(lone, "update-ref", "refs/remotes/origin/main", "HEAD")
    got = up_module.sync_checkout(lone)
    assert got.state == "failed" and got.detail.startswith("fetch failed")
    lines = up_module.sync_checkouts([tmp_path, lone])
    assert [line.split(" — ")[0].split(": ")[1] for line in lines] == ["skipped", "failed"]


@pytest.fixture(scope="module")
def up() -> ModuleType:
    return up_module


def test_the_updater_schedules_the_sync_every_15_minutes(up: ModuleType) -> None:
    python, script = Path("/usr/bin/python3"), Path("/home/u/.config/roadmodel/update_projects.py")
    plist = up.sync_launchd_plist(python, script, up.SYNC_MINUTES)
    assert "<key>StartInterval</key><integer>900</integer>" in plist
    assert "<string>--sync-checkouts</string>" in plist and up.SYNC_LABEL in plist
    argv = up.sync_schtasks_argv(python, script, 15)
    assert argv[argv.index("/SC") + 1] == "MINUTE" and argv[argv.index("/MO") + 1] == "15"
    assert "--sync-checkouts" in argv[argv.index("/TR") + 1]
    assert up.sync_cron_line(python, script, 15).startswith("*/15 * * * * ")


def test_the_updater_syncs_the_checkouts_it_is_given(
    up: ModuleType, repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    checkout, seed = repos
    _advance(seed)
    monkeypatch.setattr(up, "should_self_update", lambda self_path=None: False)
    assert up._main(["--sync-checkouts", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert "Checkouts:" in out and "checkout: updated" in out
    assert (checkout / "docs.md").read_text(encoding="utf-8") == "v2\n"


def _windows(up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand in for the PC: a Python install with both interpreters, whose
    schedule calls are recorded instead of run."""
    install = tmp_path / "Python311"
    install.mkdir()
    for name in ("python.exe", "pythonw.exe"):
        (install / name).write_bytes(b"")
    monkeypatch.setattr(up, "WINDOWS", True)
    monkeypatch.setattr(up.sys, "platform", "win32")
    monkeypatch.setattr(up, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(up, "_launcher_python", lambda: install / "python.exe")
    monkeypatch.setattr(up, "_install_launcher", lambda dry_run: tmp_path / "update_projects.py")
    return install


def test_a_windows_task_starts_pythonw_so_no_window_opens(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Console python.exe in a Task Scheduler task opened a window every 15
    minutes that took focus from full-screen games; pythonw.exe opens none."""
    install = _windows(up, tmp_path, monkeypatch)
    pythonw = install / "pythonw.exe"
    assert up._windowless(install / "python.exe") == pythonw
    assert up._windowless(pythonw) == pythonw
    assert up._windowless(Path("/usr/bin/python3")) == Path("/usr/bin/python3")

    calls: list[list[str]] = []
    definitions: list[str] = []

    def fake_sys(argv: list[str], stdin: object = None) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "/XML" in argv:
            definitions.append(Path(argv[argv.index("/XML") + 1]).read_text(encoding="utf-16"))
        return subprocess.CompletedProcess(argv, 0, "SUCCESS", "")

    monkeypatch.setattr(up, "_sys", fake_sys)
    desc = up.install_sync_schedule(15)
    command = calls[0][calls[0].index("/TR") + 1]
    assert command.startswith(f"{pythonw} -I -X utf8 ") and command.endswith(
        "--sync-checkouts --log"
    )
    assert "python.exe" not in command and str(pythonw) in desc

    calls.clear()
    desc = up.install_schedule("09:30", keep_pins=True, skip_refresh=True)
    assert "/XML" in calls[0] and str(pythonw) in desc
    assert f"<Command>{pythonw}</Command>" in definitions[0]
    assert "python.exe" not in definitions[0]

    # Without a pythonw.exe beside it, the task still runs, on python.exe.
    pythonw.unlink()
    assert up._windowless(install / "python.exe") == install / "python.exe"


def test_pythonw_reruns_the_updater_in_a_console_with_no_window(
    up: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under pythonw.exe, every console child (git, gh, claude, pip) would
    open a window of its own. The run re-starts under python.exe with
    CREATE_NO_WINDOW, so its children share one windowless console, and the
    task records the run's exit code rather than the launcher's."""
    install = _windows(up, tmp_path, monkeypatch)
    started: list[tuple[list[str], dict[str, object]]] = []

    def fake_call(argv: list[str], **kw: object) -> int:
        started.append((argv, kw))
        return 3

    monkeypatch.setattr(up.subprocess, "call", fake_call)

    def no_lock(name: str) -> ModuleType:
        raise AssertionError("the windowless child takes the lock, not its launcher")

    monkeypatch.setattr(up, "_support", no_lock)
    monkeypatch.setattr(up.sys, "executable", str(install / "pythonw.exe"))
    assert up.main(["--sync-checkouts", "--log"]) == 3
    [(argv, kw)] = started
    assert argv[:4] == [str(install / "python.exe"), "-I", "-X", "utf8"]
    assert argv[4] == str(Path(up.__file__).resolve())
    assert argv[5:] == ["--sync-checkouts", "--log"]
    assert kw == {"creationflags": 0x08000000}  # CREATE_NO_WINDOW

    # The windowless python.exe child itself runs the job, as does any
    # non-Windows run.
    monkeypatch.setattr(up.sys, "executable", str(install / "python.exe"))
    assert up._windowless_relaunch(["--sync-checkouts"]) is None
    monkeypatch.setattr(up.sys, "executable", str(install / "pythonw.exe"))
    monkeypatch.setattr(up, "WINDOWS", False)
    assert up._windowless_relaunch(["--sync-checkouts"]) is None
    assert len(started) == 1


def test_the_log_tee_skips_a_missing_console_stream(up: ModuleType, tmp_path: Path) -> None:
    import io

    log = io.StringIO()
    tee = up._Tee(None, log)  # pythonw.exe: sys.__stdout__ is None
    tee.write("Checkouts:\n")
    tee.flush()
    assert log.getvalue() == "Checkouts:\n"
