"""Shared test fixtures.

Keeps the in-repo bundled data (``src/roadmodel/data/``) in sync with its
``docs/`` source before any test runs.

Why this exists: several tests compare what the package SHIPS (the bundled
copy the CLI/MCP actually read at runtime) against the ``docs/`` source of
truth — e.g. ``test_catalog_show_bytes_match_source`` and
``test_context_init_creates_file_and_respects_force``. That bundled copy is
build output, produced by ``hatch_build.py`` copying ``docs/`` across at wheel
build, and it is gitignored.

Nothing refreshed it deterministically. It happened to be refreshed as a SIDE
EFFECT of ``test_packaging.py::test_data_dir_in_wheel``, which shells out to
``python -m build`` and thereby triggers the hatch hook. So after any edit to a
bundled doc, whether the comparison tests passed depended on whether the
packaging test had already run — and this suite uses ``pytest-randomly``, so
that order is not fixed. The observable symptom was a suite that failed once
and passed on an immediate re-run, with no code change in between.

A test passing because a different test mutated the working tree is a false
green: it hides real drift exactly when the docs have just changed, which is
when the check matters most. Sync explicitly instead, so the comparison tests
assert against a freshly-derived copy no matter what else ran.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _bundled_docs() -> dict[str, str]:
    """Read hatch_build.BUNDLED_DOCS STATICALLY, without executing the module.

    hatch_build.py imports ``hatchling`` at module scope, and hatchling is a
    build-time dependency that is absent from the test venv — importing it here
    would raise ModuleNotFoundError for every test. Parse the source instead and
    literal-eval just the mapping, so the single source of truth for what ships
    stays in hatch_build.py rather than being duplicated here.
    """
    source = (REPO_ROOT / "hatch_build.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "BUNDLED_DOCS" for t in targets):
            value = node.value
            if value is not None:
                parsed: dict[str, str] = ast.literal_eval(value)
                return parsed
    return {}


@pytest.fixture(scope="session", autouse=True)
def _sync_bundled_data() -> None:
    """Mirror docs/ -> src/roadmodel/data/ exactly as the wheel build does.

    Session-scoped and autouse so it lands before the first test regardless of
    ordering. Best-effort: a missing source doc is left to the test that
    actually asserts on it, which produces a far clearer failure than an
    exception raised out of a fixture.
    """
    dest_dir = REPO_ROOT / "src" / "roadmodel" / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for source_relpath, dest_name in _bundled_docs().items():
        source = REPO_ROOT / "docs" / source_relpath
        if not source.is_file():
            # Templates live under docs/templates/; fall back to a recursive
            # lookup so the mapping's shape can change without breaking this.
            matches = list((REPO_ROOT / "docs").rglob(Path(source_relpath).name))
            if not matches:
                continue
            source = matches[0]
        shutil.copy2(source, dest_dir / dest_name)
