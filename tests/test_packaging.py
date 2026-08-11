"""Packaging invariants for the roadmodel wheel.

Tier 1: pyproject.toml declares the expected name/version/scripts entry.
Tier 2: a freshly built wheel contains the three bundled docs at the
        canonical roadmodel/data/<filename> paths.
Tier 3: src/roadmodel/data/ is gitignored (it is build output; committing
        would create a second source of truth alongside docs/).
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

BUNDLED_DOCS = (
    "model-selector.txt",
    "model-tier-cost-scale.md",
    "user-context.example.md",
)


def test_pyproject_parses() -> None:
    with PYPROJECT_PATH.open("rb") as f:
        data = tomllib.load(f)
    project = data["project"]
    assert project["name"] == "roadmodel"
    assert project["version"] == "0.2.30"
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"]["roadmodel"] == "roadmodel.cli:main"


def test_data_dir_in_wheel(tmp_path: Path) -> None:
    with PYPROJECT_PATH.open("rb") as f:
        version = tomllib.load(f)["project"]["version"]
    outdir = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir)],
        cwd=REPO_ROOT,
        check=True,
    )
    wheels = list(outdir.glob(f"roadmodel-{version}-*.whl"))
    assert len(wheels) == 1, f"Expected exactly one wheel; got {wheels}"
    with zipfile.ZipFile(wheels[0]) as zf:
        members = set(zf.namelist())
    for name in BUNDLED_DOCS:
        expected = f"roadmodel/data/{name}"
        assert expected in members, (
            f"{expected!r} missing from wheel; members starting with "
            f"'roadmodel/data/': {sorted(m for m in members if m.startswith('roadmodel/data/'))}"
        )


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
