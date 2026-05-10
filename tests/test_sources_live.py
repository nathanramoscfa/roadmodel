"""Live integration tests for each upstream source.

These tests hit real URLs. They guard against the highest-probability
project failure: an upstream provider changing how they serve data,
after which the Monday refresh would silently produce stale or empty
docs. A failure here means a real upstream regression, not a project
bug — the fix is usually adjusting `update/sources.json` or a parser
helper.

Network blips are absorbed by retry-with-backoff. Validation failures
are hard fails because they represent real shape changes.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "update"))

import update_models as um  # noqa: E402

SOURCES = json.loads((REPO_ROOT / "update" / "sources.json").read_text())
SOURCE_LIST: list[tuple[str, dict]] = [("pricing", SOURCES["pricing"])]
SOURCE_LIST.extend(("benchmark", s) for s in SOURCES["benchmarks"])


def _retry_fetch(url: str, attempts: int = 3) -> str:
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return um.fetch(url)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            time.sleep(2**i)
    assert last_exc is not None
    raise last_exc


@pytest.fixture(scope="module")
def cursor_md() -> str:
    return _retry_fetch(SOURCES["pricing"]["url"])


@pytest.fixture(scope="module")
def aider_yaml_raw() -> str:
    aider = next(s for s in SOURCES["benchmarks"] if "Aider" in s["name"])
    return _retry_fetch(aider["url"])


@pytest.mark.parametrize(
    "kind,src",
    SOURCE_LIST,
    ids=[src["name"] for _, src in SOURCE_LIST],
)
def test_source_passes_full_pipeline(kind: str, src: dict) -> None:
    """Each source must fetch, normalize/transform, and pass its
    validate rules.

    This is the canonical "is the data being obtained" check — it runs
    the exact same pipeline the weekly refresh runs (including any
    `transform` registered in update_models.TRANSFORMS), so a pass here
    means Monday's refresh will receive non-empty content for this
    source.
    """
    if src.get("transform") == "aa_api" and not os.environ.get("AA_API_KEY"):
        pytest.skip(
            "AA_API_KEY not set; skipping live AA API check. The weekly "
            "cron must have AA_API_KEY in its environment for this "
            "source to fetch."
        )
    transform_name = src.get("transform")
    if transform_name:
        content = um.TRANSFORMS[transform_name](src["url"])
    else:
        raw = _retry_fetch(src["url"])
        max_bytes = src.get("max_bytes", um.DEFAULT_MAX_BYTES)
        content = um.normalize_content(raw, max_bytes)
    reason = um.validate_content(content, src.get("validate"))
    assert reason is None, f"{src['name']} failed validation: {reason}"
    assert content.strip(), f"{src['name']} normalized to empty content"


def test_cursor_md_has_pricing_table_with_opus_47(cursor_md: str) -> None:
    """Anchor assertion on Cursor pricing — catches Mintlify route
    changes, table format changes, or Opus 4.7 being delisted.
    """
    assert "# Models & Pricing" in cursor_md, "H1 missing — Cursor docs page may have moved"
    assert re.search(
        r"\|\s*\[Claude 4\.7 Opus\][^|]*\|\s*Anthropic\s*\|\s*\$5",
        cursor_md,
    ), "Claude 4.7 Opus row at $5 input not found — pricing table schema may have changed"


def test_cursor_md_has_at_least_30_model_rows(cursor_md: str) -> None:
    """Sanity check on catalog size — drops below 30 means the pricing
    table is partially missing, e.g. a section failed to render.
    """
    rows = re.findall(
        r"^\|[^|\n]+\|\s*(?:Anthropic|Cursor|Google|OpenAI|xAI|Moonshot)\s*\|",
        cursor_md,
        re.MULTILINE,
    )
    assert len(rows) >= 30, f"Expected at least 30 model rows, found {len(rows)}"


def test_cursor_md_notes_column_populated(cursor_md: str) -> None:
    """Notes column must be present (7+ pipe-separated cells per row).
    Catches a future Cursor schema change that drops the notes column.
    """
    sample = re.search(
        r"^\|\s*\[Claude 4\.7 Opus\][^\n]+",
        cursor_md,
        re.MULTILINE,
    )
    assert sample, "Couldn't isolate the Opus 4.7 row to check notes column"
    cells = [c.strip() for c in sample.group(0).strip("|").split("|")]
    assert len(cells) >= 7, f"Opus 4.7 row has {len(cells)} cells; expected 7+ (incl. Notes)"
    assert cells[6], "Notes cell is empty for Opus 4.7"


def test_aider_yaml_loads_with_recent_entries(aider_yaml_raw: str) -> None:
    """Aider's YAML must load and contain the expected keys.
    Catches repo restructure or schema rename in the upstream YAML.
    """
    data = yaml.safe_load(aider_yaml_raw)
    assert isinstance(data, list), "Expected a YAML list of leaderboard entries"
    assert len(data) >= 50, f"Expected at least 50 entries, got {len(data)}"
    sample = data[0]
    for required in ("model", "pass_rate_2"):
        assert required in sample, f"Aider entry missing required key '{required}': {sample}"


# ---------------------------------------------------------------------------
# Anchor assertions for raw-data benchmark sources. These mirror the depth
# of the Cursor/Aider checks above: not just "did the URL respond" but "is
# the data shape we depend on still present." A failure here means the
# upstream file moved, was renamed, or had its schema changed — adjust the
# corresponding entry in update/sources.json or the matching transform in
# update/update_models.py.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mmmu_json() -> dict:
    src = next(s for s in SOURCES["benchmarks"] if "MMMU" in s["name"])
    return json.loads(_retry_fetch(src["url"]))


@pytest.fixture(scope="module")
def swebench_json() -> dict:
    src = next(s for s in SOURCES["benchmarks"] if "SWE-bench" in s["name"])
    return json.loads(_retry_fetch(src["url"]))


def test_mmmu_has_validation_overall_scores(mmmu_json: dict) -> None:
    """MMMU JSON must keep the `validation.overall` shape we read.
    Catches a schema rename or split rename in the github.io repo.
    """
    entries = mmmu_json.get("leaderboardData")
    assert isinstance(entries, list) and len(entries) >= 30, (
        f"Expected ≥30 leaderboard entries, got {len(entries) if entries else 0}"
    )
    sample = entries[0]
    assert "info" in sample and "validation" in sample, (
        f"Entry missing required keys (info/validation): {sample}"
    )
    assert "overall" in sample["validation"], (
        f"Entry validation missing 'overall' score: {sample['validation']}"
    )


def test_swebench_has_verified_split_with_resolved_field(swebench_json: dict) -> None:
    """SWE-bench's data file must keep the Verified split with `resolved`
    as the score field. Catches split renames or score-field renames.
    """
    boards = swebench_json.get("leaderboards")
    assert isinstance(boards, list), "Expected leaderboards list at top level"
    names = {lb.get("name") for lb in boards}
    assert "Verified" in names, f"'Verified' split missing; saw: {names}"
    verified = next(lb for lb in boards if lb["name"] == "Verified")
    results = verified.get("results", [])
    assert len(results) >= 50, f"Verified has only {len(results)} results"
    assert "resolved" in results[0], (
        f"Verified result missing 'resolved' field: {list(results[0].keys())}"
    )


def test_lmarena_parquet_loads_with_expected_schema() -> None:
    """LMArena's HF parquet must keep the columns we read in the
    transform. Catches a schema change in the dataset (e.g. rename of
    `model_name` or `rating`).
    """
    pq = pytest.importorskip("pyarrow.parquet")
    src = next(s for s in SOURCES["benchmarks"] if "LMArena" in s["name"])
    body = um.fetch_bytes(src["url"])
    table = pq.read_table(__import__("io").BytesIO(body))
    required = {
        "model_name",
        "organization",
        "rating",
        "rank",
        "category",
        "leaderboard_publish_date",
    }
    missing = required - set(table.column_names)
    assert not missing, f"LMArena parquet missing columns: {missing}"
    assert table.num_rows >= 100, f"LMArena parquet has only {table.num_rows} rows"


def test_lmarena_transform_produces_overall_and_siblings() -> None:
    """End-to-end smoke of the LMArena transform: text/overall,
    webdev/overall, and search/overall must all be present in the
    output. Catches a sibling-subset URL going 404.
    """
    src = next(s for s in SOURCES["benchmarks"] if "LMArena" in s["name"])
    content = um.TRANSFORMS[src["transform"]](src["url"])
    payload = json.loads(content)
    rows = payload.get("leaderboard", [])
    assert rows, "LMArena transform produced no leaderboard rows"
    pairs = {(r["subset"], r["category"]) for r in rows}
    for required in (("text", "overall"), ("webdev", "overall"), ("search", "overall")):
        assert required in pairs, f"LMArena transform missing {required}"
