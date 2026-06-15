"""Tests for update/probe_availability.py (Phase 4.9 B4).

The live Anthropic invocation is integration (verified via the workflow dispatch
dry-run); these pin the pure logic — response classification + the reconcile that
edits the source-of-truth JSON — and that every WATCH id is a real catalog model.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_ROOT = REPO_ROOT / "update"
if str(UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(UPDATE_ROOT))

from probe_availability import WATCH, classify_probe, reconcile  # noqa: E402

SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"


def test_classify_probe_only_not_found_is_unavailable() -> None:
    assert classify_probe(200, "") == "available"
    assert classify_probe(404, '{"error":{"type":"not_found_error"}}') == "unavailable"
    assert classify_probe(400, "model: claude-x does not exist") == "unavailable"
    # Auth / rate-limit / 5xx / overloaded -> never bench (fail-safe).
    for status in (401, 403, 429, 500, 529):
        assert classify_probe(status, "overloaded") == "ambiguous"


def test_reconcile_adds_newly_unavailable() -> None:
    results = {k: "available" for k in WATCH}
    results["opus-4.8"] = "unavailable"
    new, added, removed = reconcile(results, [], "2026-06-15")
    assert added == ["opus-4.8"]
    assert removed == []
    entry = next(e for e in new if e["id"] == "opus-4.8")
    assert entry["source"] == "probe"
    assert entry["since"] == "2026-06-15"


def test_reconcile_removes_re_enabled() -> None:
    results = {k: "available" for k in WATCH}  # claude-fable-5 is callable again
    current = [{"id": "claude-fable-5", "reason": "x", "since": "2026-06-12", "source": "manual"}]
    new, added, removed = reconcile(results, current, "2026-06-15")
    assert removed == ["claude-fable-5"]
    assert new == []


def test_reconcile_keeps_ambiguous_and_nonwatch_entries() -> None:
    results = {k: "ambiguous" for k in WATCH}
    current = [
        {"id": "claude-fable-5", "reason": "x", "source": "manual"},  # WATCH + ambiguous -> kept
        {"id": "some-cn-model", "reason": "y", "source": "manual"},  # non-WATCH -> kept
    ]
    new, added, removed = reconcile(results, current, "2026-06-15")
    assert added == []
    assert removed == []
    assert {e["id"] for e in new} == {"claude-fable-5", "some-cn-model"}


def test_watch_ids_are_real_catalog_models() -> None:
    """A new Anthropic catalog model must be added to WATCH (else it goes unprobed);
    a WATCH typo would silently never match. Pin both."""
    catalog_ids = set(re.findall(r'<model\s+id="([^"]+)"', SELECTOR.read_text()))
    unknown = [mid for mid in WATCH if mid not in catalog_ids]
    assert not unknown, f"WATCH ids not in <model-options>: {unknown}"
