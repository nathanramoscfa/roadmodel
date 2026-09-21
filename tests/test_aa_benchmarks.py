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
