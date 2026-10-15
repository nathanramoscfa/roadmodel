"""Packaging invariants for the roadmodel wheel.

Tier 1: pyproject.toml declares the expected name/version/scripts entry.
Tier 2: a freshly built wheel contains the three bundled docs at the
        canonical roadmodel/data/<filename> paths.
Tier 3: src/roadmodel/data/ is gitignored (it is build output; committing
        would create a second source of truth alongside docs/).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

BUNDLED_DOCS = (
    "model-selector.txt",
    "model-tier-cost-scale.md",
    "user-context.example.md",
    "catalog.json",
    "benchmarks.json",
    "context-windows.json",
    "effort-tokens.json",
)


def test_pyproject_parses() -> None:
    with PYPROJECT_PATH.open("rb") as f:
        data = tomllib.load(f)
    project = data["project"]
    assert project["name"] == "roadmodel"
    assert project["version"] == "0.2.86"
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"]["roadmodel"] == "roadmodel.cli:main"


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    config = tomllib.loads(PYPROJECT_PATH.read_text())
    names = set(config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])
    names.add("pyproject.toml")
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, target)
    return root


def test_dirty_tree_artifacts_and_sdist_rebuild(source_tree: Path, tmp_path: Path) -> None:
    marker = b"SYNTHETIC_PRIVATE_BUILD_CANARY"
    for name in (
        "private/notes.md",
        "docs/user-context.md",
        ".roadmodel/memory/secret.md",
        "src/roadmodel/credentials.py",
        "src/roadmodel/.env",
        "src/roadmodel/data/stale-secret.txt",
        "AUTHORS-private.txt",
        "NOTICE-private.txt",
        "LICENSE-private.txt",
    ):
        path = source_tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(marker)
    outdir = tmp_path / "dist"
    # Default build builds the wheel FROM the extracted sdist. This catches
    # omitted release resources and validates both artifact allowlists.
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(outdir)],
        cwd=source_tree,
        check=True,
        capture_output=True,
        text=True,
    )
    with tarfile.open(next(outdir.glob("*.tar.gz"))) as archive:
        for member in archive.getmembers():
            if member.isfile():
                assert marker not in archive.extractfile(member).read()
        assert any(
            m.name.endswith("docs/claude-commands/roadmodel-upgrade.md")
            for m in archive.getmembers()
        )
    # Also build directly from the dirty tree: rebuilding only from the sdist
    # could conceal a wheel backend's independent metadata-file discovery.
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir / "direct")],
        cwd=source_tree,
        check=True,
        capture_output=True,
        text=True,
    )
    with zipfile.ZipFile(next((outdir / "direct").glob("*.whl"))) as direct:
        assert all(marker not in direct.read(name) for name in direct.namelist())
        licenses = {name.rsplit("/", 1)[-1] for name in direct.namelist() if "/licenses/" in name}
        assert licenses == {"LICENSE", "NOTICE"}
    with zipfile.ZipFile(next(outdir.glob("*.whl"))) as archive:
        assert all(marker not in archive.read(name) for name in archive.namelist())
        for name in BUNDLED_DOCS:
            assert (
                archive.read(f"roadmodel/data/{name}") == (REPO_ROOT / "docs" / name).read_bytes()
            )
        for name in (
            "roadmap-project",
            "roadmap-phase",
            "roadmap-step",
            "roadmap-refresh",
            "roadmodel-upgrade",
        ):
            assert (
                archive.read(f"roadmodel/data/{name}.md")
                == (REPO_ROOT / f"docs/claude-commands/{name}.md").read_bytes()
            )
        for name in (
            "update_projects",
            "agent_context",
            "agent_rules",
            "upgrade_fleet",
            "worktree_memory",
            "updater_lock",
        ):
            assert (
                archive.read(f"roadmodel/{name}.py")
                == (REPO_ROOT / f"scripts/{name}.py").read_bytes()
            )
        assert (
            archive.read("roadmodel/private_files.py")
            == (REPO_ROOT / "src/roadmodel/private_files.py").read_bytes()
        )
        extracted = tmp_path / "installed"
        archive.extractall(extracted)  # noqa: S202 - wheel built from the test's allowlisted fixture
    subprocess.run(
        [sys.executable, "-I", str(extracted / "roadmodel/update_projects.py"), "--self-check"],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "name", ["README.md", "docs/model-selector.txt", "src/roadmodel/config.py"]
)
def test_allowlisted_symlink_input_refused(source_tree: Path, tmp_path: Path, name: str) -> None:
    outside = tmp_path / "private.txt"
    outside.write_text("SYNTHETIC_PRIVATE_BUILD_CANARY")
    source = source_tree / name
    source.unlink()
    try:
        source.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    output = tmp_path / "dist"
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(output)],
        cwd=source_tree,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must not be links" in result.stderr + result.stdout
    assert not list(output.glob("*.whl"))


def test_data_dir_not_in_git() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-v", "src/roadmodel/data/model-selector.txt"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "src/roadmodel/data/ is not gitignored — committing it would create "
        f"a second source of truth alongside docs/. git output: {result.stdout!r} "
        f"{result.stderr!r}"
    )
    tracked = subprocess.run(
        ["git", "ls-files", "src/roadmodel/data"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout.strip() == "", (
        f"src/roadmodel/data/ has tracked files (should be empty build output): {tracked.stdout!r}"
    )
