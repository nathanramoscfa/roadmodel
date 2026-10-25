"""Fast-forward each registered project checkout to its remote default branch.

The operator reads roadmaps in each project's own checkout. A roadmap change
merged on GitHub (a fleet `roadmodel relayout`, a refresh, a step run on the
other machine) reached that checkout only after a manual `git pull`, so the
editor kept showing the old version (2026-10-25). The updater runs this on
its own schedule, every 15 minutes, and at the end of every run.

It only ever fast-forwards, and only where nothing can be lost:

- a checkout must sit on its default branch (main or master); a feature
  branch, an agent's step, is left alone and gets main when it rebases;
- the update is `git merge --ff-only`: never a merge commit, a rebase, a
  stash, a reset or a clean, and untracked files are never touched;
- a checkout with commits of its own, a merge, rebase or cherry-pick in
  progress, or uncommitted changes to a file the update changes, is left as
  it is and reported.

Standard library only: the updater runs it under each machine's own Python,
Windows included.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

GIT_TIMEOUT = 120
# Files whose presence in the git dir means an operation is under way.
_BUSY_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


@dataclass(frozen=True)
class Outcome:
    """What one checkout's sync did: `updated`, `current`, `skipped` (left
    alone on purpose) or `failed` (git could not do what was asked)."""

    path: Path
    state: str
    detail: str

    def line(self) -> str:
        return f"{self.path.name}: {self.state} — {self.detail}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed git argv, paths from the registry
        ["git", "-C", str(repo), *args],  # noqa: S607 — git resolved on PATH, as everywhere
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )


def _first_line(cp: subprocess.CompletedProcess[str]) -> str:
    text = (cp.stderr or cp.stdout or "").strip()
    return text.splitlines()[0] if text else f"exit {cp.returncode}"


def default_branch(repo: Path) -> Optional[str]:
    """The remote's default branch as this clone knows it (`origin/HEAD`),
    else whichever of main and master origin has; None when neither."""
    cp = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    name = cp.stdout.strip()
    if cp.returncode == 0 and name.startswith("origin/"):
        return name.removeprefix("origin/")
    for branch in ("main", "master"):
        if (
            _git(
                repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"
            ).returncode
            == 0
        ):
            return branch
    return None


def _busy(repo: Path) -> bool:
    cp = _git(repo, "rev-parse", "--git-dir")
    if cp.returncode != 0:
        return False
    git_dir = Path(cp.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    return (
        any((git_dir / marker).exists() for marker in _BUSY_MARKERS)
        or (git_dir / "index.lock").exists()
    )


def sync_checkout(repo: Path, *, dry_run: bool = False) -> Outcome:
    """Fast-forward ``repo`` to ``origin/<default branch>`` when it is on that
    branch and nothing of its own would be lost; otherwise leave it and say
    why."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        return Outcome(repo, "skipped", "not a git checkout")
    head = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head.returncode != 0:
        return Outcome(repo, "skipped", "detached HEAD")
    branch = head.stdout.strip()
    if _busy(repo):
        return Outcome(repo, "skipped", "a merge, rebase or cherry-pick is in progress")
    default = default_branch(repo)
    if default is None:
        return Outcome(repo, "skipped", "origin has no main or master")
    if branch != default:
        return Outcome(repo, "skipped", f"on {branch}; it gets {default} when it rebases")
    fetched = _git(repo, "fetch", "--quiet", "origin", default)
    if fetched.returncode != 0:
        return Outcome(repo, "failed", f"fetch failed: {_first_line(fetched)}")
    counts = _git(repo, "rev-list", "--left-right", "--count", f"HEAD...origin/{default}")
    if counts.returncode != 0:
        return Outcome(repo, "failed", f"cannot compare with origin: {_first_line(counts)}")
    ahead, behind = (int(n) for n in counts.stdout.split())
    if behind == 0:
        return Outcome(repo, "current", f"{default} is up to date")
    if ahead:
        return Outcome(
            repo, "skipped", f"{ahead} local commit(s) on {default} not on origin; not touched"
        )
    if dry_run:
        return Outcome(repo, "updated", f"would fast-forward {behind} commit(s)")
    merged = _git(repo, "merge", "--ff-only", "--quiet", f"origin/{default}")
    if merged.returncode != 0:
        return Outcome(
            repo,
            "skipped",
            f"{behind} commit(s) behind, but local changes block a fast-forward: "
            f"{_first_line(merged)}",
        )
    sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    return Outcome(repo, "updated", f"fast-forwarded {behind} commit(s) to {sha}")


def sync_all(repos: list[Path], *, dry_run: bool = False) -> list[Outcome]:
    """:func:`sync_checkout` for each repo; a git that hangs or is missing
    fails that repo only."""
    out = []
    for repo in repos:
        try:
            out.append(sync_checkout(repo, dry_run=dry_run))
        except (OSError, subprocess.SubprocessError) as exc:
            out.append(Outcome(Path(repo), "failed", f"git did not run: {exc}"))
    return out
