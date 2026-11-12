"""ROADMODEL_DATA_DIR: a newer set of data files, read in place of the bundle.

The hosted service points it at main's catalog (service/app/live_data.py),
so the guarantees here are what that relies on:

- a file the directory holds is read from there, any other from the bundle;
- the directory is looked up at read time: the module constants made at
  import read the new set as soon as the variable changes, and the bundle
  again once it is gone;
- the set is used only when its catalog's schema and output contract, and the
  schema of every other versioned file in it, are ones this package reads;
  otherwise every file comes from the bundle;
- ROADMODEL_CATALOG_PATH still wins for catalog.json;
- no cache keeps the first set read: the effort-token tables, the ladder
  table and ``catalog path`` all follow the directory.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from roadmodel import cli, cost, data_files, mcp_server, recommend, scoring

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
SET = (
    "catalog.json",
    "model-selector.txt",
    "model-tier-cost-scale.md",
    "benchmarks.json",
    "context-windows.json",
    "effort-tokens.json",
)


def _bundled(name: str) -> str:
    return data_files._bundled(name).read_text(encoding="utf-8")


def _edit_json(path: Path, edit: Callable[[dict[str, object]], None]) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    edit(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def newer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A copy of main's set with a marker in each file a test reads back; the
    variable is not set yet."""
    directory = tmp_path / "data"
    directory.mkdir()
    for name in SET:
        shutil.copyfile(DOCS / name, directory / name)
    _edit_json(
        directory / "catalog.json", lambda d: d.update(generated_at_utc="2099-01-01T00:00:00Z")
    )
    with (directory / "model-selector.txt").open("a", encoding="utf-8") as out:
        out.write("\n<!-- newer selector -->\n")
    monkeypatch.delenv("ROADMODEL_DATA_DIR", raising=False)
    monkeypatch.delenv("ROADMODEL_CATALOG_PATH", raising=False)
    recommend._TABLE_CACHE.clear()
    data_files.reset()
    yield directory
    recommend._TABLE_CACHE.clear()
    data_files.reset()


def _use(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    monkeypatch.setenv("ROADMODEL_DATA_DIR", str(directory))


def test_without_the_variable_every_file_is_bundled(newer: Path) -> None:
    assert data_files.override_dir() is None
    assert cost.BUNDLED_CATALOG_PATH.read_text(encoding="utf-8") == _bundled("catalog.json")
    assert data_files.stamp("catalog.json") == ("bundled",)


def test_the_directory_replaces_the_bundle_file_by_file(
    newer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (newer / "context-windows.json").unlink()
    _use(monkeypatch, newer)

    assert data_files.override_dir() == newer
    assert cost._load_catalog()["generated_at_utc"] == "2099-01-01T00:00:00Z"
    assert recommend.BUNDLED_SELECTOR_PATH.read_text(encoding="utf-8").endswith(
        "<!-- newer selector -->\n"
    )
    assert "<!-- newer selector -->" in mcp_server.BUNDLED_SELECTOR_PATH.read_text(encoding="utf-8")
    # A file the directory lacks still comes from the bundle.
    assert scoring.BUNDLED_CONTEXT_PATH.read_text(encoding="utf-8") == _bundled(
        "context-windows.json"
    )
    assert recommend.BUNDLED_SETTINGS_DISPLAY_PATH.read_text(encoding="utf-8") == _bundled(
        "settings-display.md"
    )


def test_it_is_looked_up_at_read_time(newer: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    selector = recommend.BUNDLED_SELECTOR_PATH  # made at import, before the variable
    assert "<!-- newer selector -->" not in selector.read_text(encoding="utf-8")
    _use(monkeypatch, newer)
    assert "<!-- newer selector -->" in selector.read_text(encoding="utf-8")

    # A newer set in a new directory (what the service publishes) reads at once.
    later = newer.parent / "later"
    shutil.copytree(newer, later)
    _edit_json(later / "catalog.json", lambda d: d.update(generated_at_utc="2099-02-02T00:00:00Z"))
    _use(monkeypatch, later)
    assert cost._load_catalog()["generated_at_utc"] == "2099-02-02T00:00:00Z"

    # A file rewritten in place reads on the next look (RECHECK_SECONDS).
    _edit_json(later / "catalog.json", lambda d: d.update(generated_at_utc="2099-03-03T00:00:00Z"))
    data_files.reset()
    assert cost._load_catalog()["generated_at_utc"] == "2099-03-03T00:00:00Z"

    monkeypatch.delenv("ROADMODEL_DATA_DIR")
    assert selector.read_text(encoding="utf-8") == _bundled("model-selector.txt")


def _catalog(**changes: object) -> Callable[[Path], None]:
    return lambda d: _edit_json(d / "catalog.json", lambda doc: doc.update(changes))


def _file(name: str, text: str) -> Callable[[Path], None]:
    return lambda d: (d / name).write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(_catalog(schema_version="99"), id="newer-catalog-schema"),
        pytest.param(_catalog(schema_version=5), id="catalog-schema-not-a-string"),
        pytest.param(_catalog(output_contract_version=3), id="newer-output-contract"),
        pytest.param(lambda d: (d / "catalog.json").unlink(), id="no-catalog"),
        pytest.param(_file("catalog.json", "{truncated"), id="catalog-not-json"),
        pytest.param(
            lambda d: _edit_json(d / "benchmarks.json", lambda doc: doc.update(schema_version=3)),
            id="newer-benchmarks-schema",
        ),
        pytest.param(
            lambda d: _edit_json(
                d / "effort-tokens.json", lambda doc: doc.update(schema_version=True)
            ),
            id="effort-tokens-schema-true",
        ),
        pytest.param(_file("context-windows.json", "[]"), id="context-windows-not-object"),
    ],
)
def test_a_set_this_package_cannot_read_falls_back_whole(
    newer: Path, monkeypatch: pytest.MonkeyPatch, spoil: Callable[[Path], None]
) -> None:
    spoil(newer)
    _use(monkeypatch, newer)

    assert data_files.usable(newer) is False
    assert data_files.override_dir() is None
    # Every file reads from the bundle, the good ones in the set included.
    for name in SET:
        assert data_files.data_file(name).read_text(encoding="utf-8") == _bundled(name)
    assert data_files.stamp(*SET) == ("bundled",) * len(SET)


def test_the_catalog_path_wins_for_the_catalog(
    newer: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pinned = tmp_path / "pinned.json"
    shutil.copyfile(newer / "catalog.json", pinned)
    _edit_json(pinned, lambda d: d.update(generated_at_utc="pinned"))
    _use(monkeypatch, newer)
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(pinned))

    assert cost._load_catalog()["generated_at_utc"] == "pinned"
    assert "<!-- newer selector -->" in recommend.BUNDLED_SELECTOR_PATH.read_text(encoding="utf-8")


def test_the_effort_token_tables_follow_the_directory(
    newer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = json.loads((newer / "effort-tokens.json").read_text(encoding="utf-8"))
    model = next(iter(doc["models"]))
    bundled = scoring.effort_token_multipliers()[model]["high"]
    doc["models"][model]["levels"]["high"]["multiplier"] = 9.5
    (newer / "effort-tokens.json").write_text(json.dumps(doc), encoding="utf-8")

    _use(monkeypatch, newer)
    assert scoring.effort_token_multipliers()[model]["high"] == 9.5
    assert scoring.token_use(model, "high") == (9.5, True)
    monkeypatch.delenv("ROADMODEL_DATA_DIR")
    assert scoring.effort_token_multipliers()[model]["high"] == bundled
    # The loader under the cache is still reachable.
    assert scoring.effort_token_multipliers.__wrapped__()[model]["high"] == bundled  # type: ignore[attr-defined]


def test_the_ladder_table_is_rebuilt_for_a_newer_set(
    newer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builds: list[str] = []
    real = scoring.ladder_table

    def counting(text: str, **kw: object) -> dict[str, scoring.Ladder]:
        builds.append(text)
        return real(text, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(scoring, "ladder_table", counting)
    context = _bundled("user-context.example.md")
    recommend._ladder_table_for(context, None)
    recommend._ladder_table_for(context, None)
    assert len(builds) == 1
    _use(monkeypatch, newer)
    recommend._ladder_table_for(context, None)
    recommend._ladder_table_for(context, None)
    assert len(builds) == 2


def test_catalog_path_prints_the_file_that_is_read(
    newer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, newer)
    result = CliRunner().invoke(cli.cli, ["catalog", "path"])
    assert result.exit_code == 0, result.output
    printed = Path(result.output.strip())
    # A real path that outlives the command, not a deleted temporary copy.
    assert printed == newer / "model-selector.txt" and printed.is_file()


def test_a_data_file_is_named_by_a_bare_file_name() -> None:
    for bad in ("", ".", "..", "../catalog.json", "sub/catalog.json"):
        with pytest.raises(ValueError):
            data_files.data_file(bad)
    assert data_files.data_file("catalog.json") == cost.BUNDLED_CATALOG_PATH
    assert data_files.data_file("catalog.json").name == "catalog.json"


def test_the_bundled_set_is_one_this_package_reads() -> None:
    """A schema or contract bump changes the supported sets in the same
    change; otherwise the live service would refuse main's data for good."""
    catalog = json.loads((DOCS / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["schema_version"] in data_files.CATALOG_SCHEMAS
    assert catalog["output_contract_version"] in data_files.OUTPUT_CONTRACTS
    assert recommend.OUTPUT_CONTRACT_VERSION in data_files.OUTPUT_CONTRACTS
    for name, versions in data_files.FILE_SCHEMAS.items():
        doc = json.loads((DOCS / name).read_text(encoding="utf-8"))
        assert doc["schema_version"] in versions, name
    build = (REPO_ROOT / "update" / "build_catalog.py").read_text(encoding="utf-8")
    declared = re.search(r'^SCHEMA_VERSION = "([^"]+)"', build, re.MULTILINE)
    assert declared and declared.group(1) in data_files.CATALOG_SCHEMAS
    assert data_files.usable(DOCS)
