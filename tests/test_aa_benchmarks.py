"""update/fetch_aa_benchmarks.py — the structured benchmark layer.

Pure tests over build(): the join from catalog ids to Artificial Analysis
rows through update/aa-model-map.json, and the two failure-tolerant edges
(a catalog id missing from the map, a mapped slug AA no longer serves) that
must be REPORTED, not fatal, so a cron-added model degrades to dashes on
/models instead of stalling the refresh.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "fetch_aa_benchmarks", REPO_ROOT / "update" / "fetch_aa_benchmarks.py"
)
assert _spec is not None and _spec.loader is not None
fab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fab)

NOW = dt.datetime(2026, 9, 21, 22, 0, tzinfo=dt.timezone.utc)

AA = [
    {
        "id": "u1",
        "name": "Claude Opus 5 (Adaptive Reasoning, Max Effort)",
        "slug": "claude-opus-5",
        "release_date": "2026-08-05",
        "model_creator": {"name": "Anthropic"},
        "evaluations": {"artificial_analysis_intelligence_index": 50.8, "hle": 0.549, "lcr": None},
        "median_output_tokens_per_second": 58.29,
        "median_time_to_first_token_seconds": 30.1,
    },
    {
        "id": "u2",
        "name": "Some other model",
        "slug": "other-model",
        "model_creator": {"name": "X"},
        "evaluations": {"artificial_analysis_intelligence_index": 10.0},
        "median_output_tokens_per_second": 0,
        "median_time_to_first_token_seconds": 0,
    },
]


def test_build_joins_mapped_rows_and_keeps_every_evaluation() -> None:
    doc = fab.build(["claude-opus-5"], {"claude-opus-5": "claude-opus-5"}, AA, now=NOW)
    assert doc["schema_version"] == fab.SCHEMA_VERSION
    assert doc["generated_at_utc"] == "2026-09-21T22:00:00Z"
    assert doc["model_count"] == 1
    row = doc["models"]["claude-opus-5"]
    assert row["aa_slug"] == "claude-opus-5"
    assert row["aa_creator"] == "Anthropic"
    # Nulls are preserved (a column the web may add later, without a re-fetch).
    assert row["evaluations"] == {
        "artificial_analysis_intelligence_index": 50.8,
        "hle": 0.549,
        "lcr": None,
    }
    assert row["median_output_tokens_per_second"] == 58.29
    assert doc["source"]["url"] == "https://artificialanalysis.ai/"
    assert doc["unmapped"] == [] and doc["missing_slugs"] == []


def test_null_map_entry_means_confirmed_unmeasured_not_unmapped() -> None:
    doc = fab.build(["codestral"], {"codestral": None}, AA, now=NOW)
    assert doc["models"] == {}
    assert doc["unmapped"] == []


def test_missing_map_entry_is_reported_not_fatal() -> None:
    doc = fab.build(
        ["brand-new-model", "claude-opus-5"], {"claude-opus-5": "claude-opus-5"}, AA, now=NOW
    )
    assert doc["unmapped"] == ["brand-new-model"]
    assert set(doc["models"]) == {"claude-opus-5"}


def test_retired_slug_is_reported_not_fatal() -> None:
    doc = fab.build(["opus-4.7"], {"opus-4.7": "claude-opus-4-7"}, AA, now=NOW)
    assert doc["models"] == {}
    assert doc["missing_slugs"] == ["opus-4.7 -> claude-opus-4-7"]


def test_stable_fields_ignore_the_timestamp_only() -> None:
    a = fab.build(["claude-opus-5"], {"claude-opus-5": "claude-opus-5"}, AA, now=NOW)
    b = fab.build(
        ["claude-opus-5"],
        {"claude-opus-5": "claude-opus-5"},
        AA,
        now=NOW + dt.timedelta(days=1),
    )
    assert a != b
    assert fab.stable_fields(a) == fab.stable_fields(b)


def test_committed_layer_matches_the_committed_map_and_catalog() -> None:
    """docs/benchmarks.json must be keyed by CURRENT catalog ids through the
    committed map — a renamed catalog id would otherwise ship a silent gap."""
    doc = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())
    mapping = json.loads((REPO_ROOT / "update" / "aa-model-map.json").read_text())
    catalog_ids = {
        m["id"] for m in json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())["models"]
    }
    assert set(doc["models"]) <= catalog_ids
    for cid, row in doc["models"].items():
        assert mapping.get(cid) == row["aa_slug"]
    assert doc["model_count"] == len(doc["models"]) > 0
    assert doc["source"]["url"] == "https://artificialanalysis.ai/"


# --------------------------------------------------------------------------- #
# Auto-map: a new catalog id links itself to an exact AA slug match
# --------------------------------------------------------------------------- #

_AA = [
    {"slug": "claude-opus-5-5"},
    {"slug": "grok-4-7"},
    {"slug": "gpt-5-high"},
    {"slug": "codestral-2508"},
]


def test_a_new_id_with_an_exact_slug_match_is_mapped() -> None:
    added = fab.auto_map(["claude-opus-5-5", "grok-4.7"], {}, _AA)
    assert added == {"claude-opus-5-5": "claude-opus-5-5", "grok-4.7": "grok-4-7"}


def test_anything_short_of_exact_stays_unmapped() -> None:
    """`gpt-5` is not `gpt-5-high`, and `codestral` is not `codestral-2508`:
    close is a person's call, so those stay on the unmapped list."""
    assert fab.auto_map(["gpt-5", "codestral"], {}, _AA) == {}


def test_an_existing_entry_is_never_touched() -> None:
    """A deliberate `null` (AA has not measured it) and an explicit slug both
    stand, even when an exact match exists."""
    mapping = {"claude-opus-5-5": None, "grok-4.7": "grok-4-6"}
    assert fab.auto_map(["claude-opus-5-5", "grok-4.7"], mapping, _AA) == {}


def test_save_map_keeps_the_files_layout(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "aa-model-map.json"
    path.write_text(json.dumps({"_comment": "keep me", "b": "b", "a": None}, indent=2) + "\n")
    monkeypatch.setattr(fab, "MAP_PATH", path)
    fab.save_map({"b": "b", "a": None, "c": "c-1"})
    assert list(json.loads(path.read_text())) == ["_comment", "a", "b", "c"]
    assert json.loads(path.read_text())["_comment"] == "keep me"
