"""Tests for update/sync_static_availability.py.

Two jobs:
  1. Pure-function behaviour of the cold-start fallback regenerator.
  2. A DRIFT GUARD asserting the committed static <availability-context>
     fallback agrees with infra/model-availability.json — the exact silent
     drift that left Fable 5 benched offline for two weeks after the runtime
     layer un-benched it. If this fails: python update/sync_static_availability.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_ROOT = REPO_ROOT / "update"
if str(UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(UPDATE_ROOT))

import sync_static_availability as sync  # noqa: E402

# --- the drift guard (the reason this module exists) -----------------------


def test_committed_selector_matches_json() -> None:
    selector = sync.SELECTOR_TXT.read_text(encoding="utf-8")
    data = json.loads(sync.AVAILABILITY_JSON.read_text(encoding="utf-8"))
    assert sync.ids_in_selector(selector) == sync.ids_in_json(data), (
        "static <availability-context> fallback is out of sync with "
        "infra/model-availability.json — run: "
        "python update/sync_static_availability.py"
    )


def test_check_mode_passes_on_committed_repo() -> None:
    assert sync.main(["--check"]) == 0


# --- render_region ---------------------------------------------------------


def test_render_region_empty_is_self_documenting() -> None:
    region = sync.render_region([], name_of=lambda m: m)
    assert "auto-generated" in region
    assert "EMPTY" in region
    assert "- `" not in region  # no bullets
    assert not sync._BULLET_ID_RE.findall(region)


def test_render_region_lists_benched_models() -> None:
    entries = [{"id": "claude-fable-5", "reason": "Export-control gate as of 2026-06-12."}]
    region = sync.render_region(entries, name_of=lambda m: "Fable 5")
    assert "- `claude-fable-5` (Fable 5) — Export-control gate" in region
    assert sync._BULLET_ID_RE.findall(region) == ["claude-fable-5"]


def test_render_region_falls_back_on_missing_reason() -> None:
    region = sync.render_region([{"id": "some-model"}], name_of=lambda m: m)
    assert "Provider access restricted." in region


# --- apply_region ----------------------------------------------------------


def test_apply_region_is_idempotent() -> None:
    selector = sync.SELECTOR_TXT.read_text(encoding="utf-8")
    data = json.loads(sync.AVAILABILITY_JSON.read_text(encoding="utf-8"))
    once = sync.rewrite_selector_text(selector, data)
    twice = sync.rewrite_selector_text(once, data)
    assert once == twice


def test_apply_region_preserves_surrounding_prose() -> None:
    selector = sync.SELECTOR_TXT.read_text(encoding="utf-8")
    out = sync.rewrite_selector_text(selector, {"unavailable": []})
    # The two static paragraphs survive, and the anchors stay unique.
    assert "Authoritative source — the runtime override." in out
    assert "disclose the substitution in the" in out
    assert out.count(sync._START) == 1
    assert out.count(sync._END) == 1


def test_ids_survive_a_render_apply_roundtrip() -> None:
    selector = sync.SELECTOR_TXT.read_text(encoding="utf-8")
    data = {"unavailable": [{"id": "claude-fable-5", "reason": "x"}]}
    out = sync.rewrite_selector_text(selector, data)
    assert sync.ids_in_selector(out) == {"claude-fable-5"}


def test_apply_region_rejects_ambiguous_anchors() -> None:
    with pytest.raises(ValueError):
        sync.apply_region("no anchors here", "region\n")


# --- main --check drift detection ------------------------------------------


def test_check_mode_flags_drift(tmp_path, monkeypatch, capsys) -> None:
    # Selector says nothing benched; JSON benches a model -> drift.
    j = tmp_path / "availability.json"
    j.write_text(json.dumps({"unavailable": [{"id": "claude-fable-5", "reason": "x"}]}))
    monkeypatch.setattr(sync, "AVAILABILITY_JSON", j)
    assert sync.main(["--check"]) == 1
    assert "out of sync" in capsys.readouterr().err
