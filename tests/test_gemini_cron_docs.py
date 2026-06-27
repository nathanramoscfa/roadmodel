"""Tests for the Gemini docs-freshness cron (T2).

Covers the deterministic pieces of the docs-source gate, the Opus wiring, and
the robustness guarantees that matter for an HTML / dynamic-site source:

- ``check_gemini_source.validate_docs`` enforces min_bytes + the server-rendered
  table anchors (so a JS shell / interstitial is rejected, not parsed).
- ``check_gemini_source.facts_signature`` hashes the EXTRACTED FACTS, so a
  cosmetic HTML edit (whitespace, surrounding prose) does NOT change the
  signature, while a real fact change (a budget range) does.
- ``update_gemini.build_user_message`` includes a ``<docs_facts>`` block when
  given, and ``read_docs_facts`` reads the committed snapshot.
- The Opus prompt documents ``<docs_facts>``, the conformance gate, and fences
  off model lists / the other providers' bullets.

The end-to-end main() flow (live Opus) is exercised by the workflow_dispatch
dry-run, not mocked here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
SAMPLE_HTML = REPO_ROOT / "tests" / "fixtures" / "gemini-thinking-sample.html"


def _load(name: str) -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def test_validate_docs_enforces_server_rendered_anchors() -> None:
    mod = _load("check_gemini_source")
    cfg = {
        "validate": {
            "min_bytes": 20,
            "must_contain_all": ["Model", "Levels Supported"],
        }
    }
    mod.validate_docs("Model ... Levels Supported ... padded out here.", cfg)
    with pytest.raises(ValueError):
        mod.validate_docs("tiny", cfg)  # below min_bytes + missing anchors
    # A client-rendered shell that lacks the server-rendered table anchors.
    with pytest.raises(ValueError):
        mod.validate_docs("<div id='app'></div>" + "x" * 200, cfg)


def test_facts_signature_ignores_cosmetic_html_but_catches_fact_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load("check_gemini_source")
    base = SAMPLE_HTML.read_text()
    # Cosmetic churn: surrounding prose + whitespace, NO table-fact change.
    cosmetic = base.replace("<body>", "<body>\n<p>Unrelated re-render blurb.</p>\n")
    # Real fact change: a per-model level edit (Gemini 3 Pro gains `medium`).
    fact_change = base.replace("low, high</td>", "low, medium, high</td>", 1)

    # The fixture is a small slice; supply a permissive cfg (the real min_bytes
    # floor guards the 219 KB live page, not this offline slice). The anchors
    # still apply — the fixture carries them.
    real_anchors = mod.sources()["thinking_docs"]["validate"]["must_contain_all"]
    monkeypatch.setattr(
        mod,
        "sources",
        lambda: {
            "thinking_docs": {
                "url": "file://x",
                "validate": {"min_bytes": 500, "must_contain_all": real_anchors},
            }
        },
    )
    monkeypatch.setattr(mod, "fetch_html", lambda url: base)
    sig_base = mod.facts_signature()
    monkeypatch.setattr(mod, "fetch_html", lambda url: cosmetic)
    sig_cosmetic = mod.facts_signature()
    monkeypatch.setattr(mod, "fetch_html", lambda url: fact_change)
    sig_fact = mod.facts_signature()

    assert sig_base == sig_cosmetic, "cosmetic HTML churn must NOT change the facts signature"
    assert sig_base != sig_fact, "a real per-model level change MUST change the facts signature"


def test_facts_signature_fails_open_on_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A degenerate (JS-shell) page must raise, so check_source fails OPEN
    (changed=true) and the workflow's extractor step then fails loud."""
    mod = _load("check_gemini_source")
    monkeypatch.setattr(mod, "fetch_html", lambda url: "<div id='app'></div>")
    changed = mod.check_source(
        mod.facts_signature, mod.DOCS_HASH_PATH, mod.DOCS_HASH_STAGING_PATH, "thinking facts"
    )
    assert changed is True


def test_build_user_message_includes_docs_facts() -> None:
    mod = _load("update_gemini")
    msg = mod.build_user_message("SELECTOR", docs_facts='{"thinking_levels": ["low", "high"]}')
    assert "<docs_facts" in msg
    assert "thinking_levels" in msg

    msg_none = mod.build_user_message("S", docs_facts=None)
    assert "<docs_facts" not in msg_none


def test_read_docs_facts_reads_committed_snapshot() -> None:
    mod = _load("update_gemini")
    facts = mod.read_docs_facts()
    assert facts is not None  # the committed snapshot exists
    assert "thinking_levels" in facts


def test_prompt_documents_docs_facts_and_scope() -> None:
    prompt = (UPDATE_DIR / "prompt-gemini.md").read_text()
    assert "<docs_facts" in prompt
    assert "validate_effort_conformance" in prompt
    # The Gemini methods are in scope; model lists are fenced off.
    assert "google-api" in prompt
    assert "gemini-cli" in prompt
    assert "supports-models" in prompt


def test_sources_gemini_has_thinking_docs_entry() -> None:
    import json

    sources = json.loads((UPDATE_DIR / "sources-gemini.json").read_text())
    assert "thinking" in sources["thinking_docs"]["url"]
    anchors = sources["thinking_docs"]["validate"]["must_contain_all"]
    for needle in ("Model", "Default Thinking", "Levels Supported"):
        assert needle in anchors


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
