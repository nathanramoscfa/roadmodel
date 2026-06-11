"""Tests for the DeepSeek docs-freshness cron (T2).

Covers the deterministic pieces of the docs-source gate, the flag-only models
extractor, the Opus wiring, and the robustness guarantees that matter for an
HTML / dynamic-site source:

- ``check_deepseek_source.validate_docs`` enforces min_bytes + the server-rendered
  table anchors (so a JS shell / interstitial is rejected, not parsed).
- ``check_deepseek_source.facts_signature`` hashes the EXTRACTED FACTS, so a
  cosmetic HTML edit does NOT change the signature, while a real fact change (a
  new native effort tier) does.
- ``extract_deepseek_models`` parses the pricing-page MODEL row and flags an
  unexpected model; it fails open on a restructured page.
- ``update_deepseek.build_user_message`` includes a ``<docs_facts>`` block when
  given, and ``read_docs_facts`` reads the committed snapshot.
- The Opus prompt documents ``<docs_facts>``, the conformance gate, and fences
  off model lists / methods / the other providers' bullets.

The end-to-end main() flow (live Opus) is exercised by the workflow_dispatch
dry-run, not mocked here.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
THINKING_HTML = REPO_ROOT / "tests" / "fixtures" / "deepseek-thinking-sample.html"
PRICING_HTML = REPO_ROOT / "tests" / "fixtures" / "deepseek-pricing-sample.html"
MODELS_EXTRACTOR = UPDATE_DIR / "extract_deepseek_models.py"


def _load(name: str) -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


# --------------------------------------------------------------------------- #
# Docs-source gate
# --------------------------------------------------------------------------- #


def test_validate_docs_enforces_server_rendered_anchors() -> None:
    mod = _load("check_deepseek_source")
    cfg = {
        "validate": {
            "min_bytes": 20,
            "must_contain_all": ["Control Parameter", "reasoning_effort"],
        }
    }
    mod.validate_docs("Control Parameter ... reasoning_effort ... padded out here.", cfg)
    with pytest.raises(ValueError):
        mod.validate_docs("tiny", cfg)  # below min_bytes + missing anchors
    # A client-rendered shell that lacks the server-rendered table anchors.
    with pytest.raises(ValueError):
        mod.validate_docs("<div id='app'></div>" + "x" * 200, cfg)


def test_facts_signature_ignores_cosmetic_html_but_catches_fact_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load("check_deepseek_source")
    base = THINKING_HTML.read_text()
    # Cosmetic churn: surrounding prose + whitespace, NO table-fact change.
    cosmetic = base.replace("<body>", "<body>\n<p>Unrelated re-render blurb.</p>\n")
    # Real fact change: a new native effort tier in the reasoning-effort cell.
    fact_change = base.replace('"high/max"', '"high/max/ultra"', 1)

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
    assert sig_base != sig_fact, "a real effort-tier change MUST change the facts signature"


def test_facts_signature_fails_open_on_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A degenerate (JS-shell) page must raise, so check_source fails OPEN
    (changed=true) and the workflow's extractor step then fails loud."""
    mod = _load("check_deepseek_source")
    monkeypatch.setattr(mod, "fetch_html", lambda url: "<div id='app'></div>")
    changed = mod.check_source(
        mod.facts_signature, mod.DOCS_HASH_PATH, mod.DOCS_HASH_STAGING_PATH, "thinking facts"
    )
    assert changed is True


# --------------------------------------------------------------------------- #
# Flag-only models extractor (pricing page)
# --------------------------------------------------------------------------- #


def test_models_extractor_parses_pricing_row() -> None:
    mod = _load("extract_deepseek_models")
    models = mod.pricing_models(PRICING_HTML.read_text())
    assert models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert mod.unexpected_models(PRICING_HTML.read_text()) == []


def test_models_extractor_flags_unexpected_model() -> None:
    mod = _load("extract_deepseek_models")
    html = PRICING_HTML.read_text().replace("deepseek-v4-pro", "deepseek-v5-pro")
    assert "deepseek-v5-pro" in mod.unexpected_models(html)


def test_models_extractor_fails_open_on_restructure() -> None:
    """A pricing page with no MODEL row raises ModelsParseError; the CLI swallows
    it (fail-open, returns 0) so model flagging never breaks the refresh."""
    mod = _load("extract_deepseek_models")
    with pytest.raises(mod.ModelsParseError):
        mod.pricing_models("<html><body><table><tr><td>x</td></tr></table></body></html>")
    result = subprocess.run(
        [sys.executable, str(MODELS_EXTRACTOR), "--input", str(THINKING_HTML)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0  # fail-open even when the page has no MODEL row
    assert result.stdout.strip() == ""


# --------------------------------------------------------------------------- #
# Opus wiring + prompt
# --------------------------------------------------------------------------- #


def test_build_user_message_includes_docs_facts() -> None:
    mod = _load("update_deepseek")
    msg = mod.build_user_message("SELECTOR", docs_facts='{"reasoning_effort": ["high", "max"]}')
    assert "<docs_facts" in msg
    assert "reasoning_effort" in msg

    msg_none = mod.build_user_message("S", docs_facts=None)
    assert "<docs_facts" not in msg_none


def test_read_docs_facts_reads_committed_snapshot() -> None:
    mod = _load("update_deepseek")
    facts = mod.read_docs_facts()
    assert facts is not None  # the committed snapshot exists
    assert "reasoning_effort" in facts


def test_prompt_documents_docs_facts_and_scope() -> None:
    prompt = (UPDATE_DIR / "prompt-deepseek.md").read_text()
    assert "<docs_facts" in prompt
    assert "validate_effort_conformance" in prompt
    assert "reasoning_effort" in prompt
    assert "thinking_toggle" in prompt
    # Model lists + methods are fenced off (tracked-only, decision B).
    assert "supports-models" in prompt
    assert "<model-options>" in prompt


def test_sources_deepseek_has_thinking_and_models_entries() -> None:
    sources = json.loads((UPDATE_DIR / "sources-deepseek.json").read_text())
    assert "thinking_mode" in sources["thinking_docs"]["url"]
    anchors = sources["thinking_docs"]["validate"]["must_contain_all"]
    for needle in ("Control Parameter", "reasoning_effort", "Thinking Mode Toggle"):
        assert needle in anchors
    assert "pricing" in sources["models_docs"]["url"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
