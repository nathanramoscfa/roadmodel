"""Tests for update/sync_availability.py (Phase 4.9 B3).

The Supabase REST writes are integration (verified via the workflow dispatch
dry-run); these pin the pure logic — JSON parsing + the reconcile diff — plus that
the committed source of truth is well-formed and lists claude-fable-5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_ROOT = REPO_ROOT / "update"
if str(UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(UPDATE_ROOT))

from sync_availability import AVAILABILITY_JSON, load_unavailable, plan  # noqa: E402


def test_committed_source_of_truth_is_well_formed() -> None:
    """The committed source of truth loads and every entry has a non-empty id +
    reason. Deliberately NOT pinned to a specific model: the probe (B4) may add or
    remove entries (e.g. self-heal Fable 5 if Anthropic restores access), and that
    must not break CI on the auto-PR."""
    desired = load_unavailable(AVAILABILITY_JSON)
    for model_id, meta in desired.items():
        assert model_id
        assert meta["reason"], f"{model_id} has no reason"


def test_load_unavailable_skips_garbled_entries(tmp_path: Path) -> None:
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "unavailable": [
                    {"id": "good-model", "reason": "x", "source": "probe"},
                    {"id": "  ", "reason": "blank id dropped"},
                    {"reason": "no id dropped"},
                    "not-a-dict",
                    {"id": "defaults-source"},
                ]
            }
        )
    )
    out = load_unavailable(p)
    assert set(out) == {"good-model", "defaults-source"}
    assert out["good-model"] == {"reason": "x", "source": "probe"}
    assert out["defaults-source"]["source"] == "manual"  # default when omitted


def test_plan_upserts_desired_and_deletes_extras() -> None:
    desired = {
        "a": {"reason": "", "source": "manual"},
        "b": {"reason": "", "source": "manual"},
    }
    to_upsert, to_delete = plan(desired, {"b", "c"})
    assert to_upsert == ["a", "b"]  # all desired upserted (idempotent)
    assert to_delete == ["c"]  # in table, not desired -> re-enabled


def test_plan_empty_desired_deletes_all_current() -> None:
    to_upsert, to_delete = plan({}, {"x", "y"})
    assert to_upsert == []
    assert to_delete == ["x", "y"]
