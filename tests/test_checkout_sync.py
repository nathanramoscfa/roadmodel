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
