"""Tests for update/probe_availability.py (Phase 4.9 B4 + multi-provider).

Live API calls are integration (verified via the workflow dispatch dry-run); these
pin the pure logic — invocation classification, the longest-prefix list match, the
results-driven reconcile — and that every watched id is a real catalog model.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_ROOT = REPO_ROOT / "update"
if str(UPDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(UPDATE_ROOT))

from probe_availability import (  # noqa: E402
    _best_match,
    availability_from_list,
    classify_probe,
    reconcile,
    watch_ids,
)

SELECTOR = REPO_ROOT / "docs" / "model-selector.txt"


def test_classify_probe_only_not_found_is_unavailable() -> None:
    assert classify_probe(200, "") == "available"
    assert classify_probe(404, '{"error":{"type":"not_found_error"}}') == "unavailable"
    assert classify_probe(400, "model: claude-x does not exist") == "unavailable"
    for status in (401, 403, 429, 500, 529):
        assert classify_probe(status, "overloaded") == "ambiguous"


def test_best_match_longest_prefix_disambiguates() -> None:
    openai = ["gpt-5", "gpt-5-mini", "gpt-5.4", "gpt-5.4-mini"]
    assert _best_match("gpt-5", openai) == "gpt-5"
    assert _best_match("gpt-5-2026-01-01", openai) == "gpt-5"  # date variant of gpt-5
    assert _best_match("gpt-5-mini", openai) == "gpt-5-mini"
    assert _best_match("gpt-5-mini-2026", openai) == "gpt-5-mini"  # NOT gpt-5
    assert _best_match("gpt-5.4-mini-preview", openai) == "gpt-5.4-mini"  # longest wins
    assert _best_match("gpt-4o", openai) is None  # unrelated
    gemini = ["gemini-3-flash", "gemini-3-pro", "gemini-3.1-pro", "gemini-2.5-flash"]
    assert _best_match("gemini-3-pro-preview", gemini) == "gemini-3-pro"
    assert _best_match("gemini-3.1-pro-preview-customtools", gemini) == "gemini-3.1-pro"
    assert _best_match("gemini-3-flash-preview", gemini) == "gemini-3-flash"
    assert _best_match("gemini-2.5-flash-lite", gemini) == "gemini-2.5-flash"


def test_availability_from_list() -> None:
    catalog = ["gpt-5", "gpt-5-mini", "gpt-5.5"]
    listed = {"gpt-5-2026", "gpt-5-mini", "gpt-4o"}  # gpt-5.5 absent
    out = availability_from_list(catalog, listed)
    assert out == {"gpt-5": "available", "gpt-5-mini": "available", "gpt-5.5": "unavailable"}


def test_reconcile_adds_newly_unavailable() -> None:
    results = {"opus-4.8": "unavailable", "gpt-5": "available"}
    new, added, removed = reconcile(results, [], "2026-06-15")
    assert added == ["opus-4.8"]
    assert removed == []
    entry = next(e for e in new if e["id"] == "opus-4.8")
    assert entry["source"] == "probe"
    assert entry["since"] == "2026-06-15"


def test_reconcile_removes_re_enabled() -> None:
    results = {"claude-fable-5": "available"}
    current = [{"id": "claude-fable-5", "reason": "x", "since": "2026-06-12", "source": "manual"}]
    new, added, removed = reconcile(results, current, "2026-06-15")
    assert removed == ["claude-fable-5"]
    assert new == []


def test_reconcile_leaves_unprobed_ambiguous_and_nonwatch() -> None:
    results = {"opus-4.8": "ambiguous"}  # claude-fable-5 not probed (e.g. no key)
    current = [
        {"id": "claude-fable-5", "reason": "x", "source": "manual"},
        {"id": "some-cn-model", "reason": "y", "source": "manual"},
    ]
    new, added, removed = reconcile(results, current, "2026-06-15")
    assert added == []
    assert removed == []
    assert {e["id"] for e in new} == {"claude-fable-5", "some-cn-model"}


def test_watch_ids_are_real_catalog_models() -> None:
    """A new watched model must be a real catalog id; a typo would never match."""
    catalog_ids = set(re.findall(r'<model\s+id="([^"]+)"', SELECTOR.read_text()))
    unknown = [mid for mid in watch_ids() if mid not in catalog_ids]
    assert not unknown, f"watched ids not in <model-options>: {unknown}"
