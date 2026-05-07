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
    """Each source must fetch, normalize, and pass its validate rules.

    This is the canonical "is the data being obtained" check — it runs
    the exact same pipeline the weekly refresh runs, so a pass here
    means Monday's refresh will receive non-empty content for this
    source.
    """
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
