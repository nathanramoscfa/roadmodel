"""Offline regression test for the LMArena transform's snapshot selection.

LMArena publishes each subset as a parquet of every historical leaderboard,
so the transform has to pick which publish date to keep. It used to take one
latest date per SUBSET. That assumes every publish refreshes every category
in that subset, and LMArena does not work that way: on 2026-09-13 the
`webdev` subset published only `image_to_webdev`, while its `overall` board
had last published on 2026-09-11.

The result was silent data loss. "Latest date for the subset" became
2026-09-13, every `overall` row was filtered out as stale, `image_to_webdev`
was not in the keep map — so the transform emitted the webdev leaderboard
EMPTY and raised nothing, because an empty subset is not an error. The whole
"LMArena WebDev Elo" evidence line quietly vanished from the payload.

The fix is what the docstring always claimed: the latest publish date per
(subset, category) pair. These tests pin it without touching the network.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "update" / "update_models.py"

# (category, publish date) per subset, mirroring the real shape: `webdev`
# publishes a NEW, narrower board on a LATER date than its `overall` board.
_FIXTURE: dict[str, list[tuple[str, str]]] = {
    "text": [("overall", "2026-09-13"), ("coding", "2026-09-13")],
    "webdev": [("overall", "2026-09-11"), ("image_to_webdev", "2026-09-13")],
    "search": [("overall", "2026-08-24")],
}


@pytest.fixture(scope="module")
def um() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_models", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parquet(subset: str) -> bytes:
    """A parquet table with the columns the transform reads, two models per
    (category, date) pair so rank filtering has something to bite on."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = []
    for category, date in _FIXTURE[subset]:
        for rank in (1, 2):
            rows.append(
                {
                    "model_name": f"{subset}-{category}-{rank}",
                    "organization": "org",
                    "rating": 1500.0 - rank,
                    "rank": rank,
                    "category": category,
                    "vote_count": 100,
                    "leaderboard_publish_date": date,
                }
            )
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buf)
    return buf.getvalue()


@pytest.fixture
def payload(um: ModuleType, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    url = "https://example.invalid/lmarena/text/latest-00000-of-00001.parquet"

    def fake_fetch(u: str) -> bytes:
        for subset in _FIXTURE:
            if f"/{subset}/" in u:
                return _parquet(subset)
        raise AssertionError(f"transform fetched an unconfigured subset: {u}")

    monkeypatch.setattr(um, "fetch_bytes", fake_fetch)
    return json.loads(um.TRANSFORMS["lmarena_parquet"](url))


def test_a_later_narrow_publish_does_not_erase_a_subsets_other_boards(
    payload: dict[str, Any],
) -> None:
    """The exact 2026-09 regression: `webdev` publishing only
    `image_to_webdev` on a later date must not drop `webdev/overall`."""
    pairs = {(r["subset"], r["category"]) for r in payload["leaderboard"]}
    assert ("webdev", "overall") in pairs, (
        "webdev/overall was dropped because a NARROWER webdev board published "
        "later — the per-subset latest-date bug this test exists to catch"
    )
    assert ("text", "overall") in pairs and ("search", "overall") in pairs


def test_each_pair_reports_its_own_publish_date(payload: dict[str, Any]) -> None:
    """A per-subset date would have to lie about at least one board. Keyed
    per pair, every date is the one that board actually published on."""
    assert payload["snapshot_dates"] == {
        "text/overall": "2026-09-13",
        "text/coding": "2026-09-13",
        "webdev/overall": "2026-09-11",
        "search/overall": "2026-08-24",
    }


def test_categories_outside_the_keep_map_are_still_excluded(
    payload: dict[str, Any],
) -> None:
    """Widening the date selection must not widen what ships: the keep map
    is what bounds the payload against the prompt budget."""
    categories = {(r["subset"], r["category"]) for r in payload["leaderboard"]}
    assert ("webdev", "image_to_webdev") not in categories
    assert all(r["rank"] <= 60 for r in payload["leaderboard"])
