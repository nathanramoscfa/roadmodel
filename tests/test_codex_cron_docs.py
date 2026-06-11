"""Tests for the Codex docs-freshness cron (T2).

Covers the deterministic pieces of the docs-source gate, the Opus wiring, and
the model-flag helper:

- ``check_codex_source.validate_docs`` enforces min_bytes + must_contain.
- ``check_codex_source.docs_signature`` hashes ONLY the in-scope reasoning span —
  an out-of-scope docs edit must NOT change it; an in-scope edit must.
- ``update_codex.build_user_message`` includes a ``<docs_facts>`` block when
  given, and ``read_docs_facts`` reads the committed snapshot.
- The Opus prompt documents ``<docs_facts>``, the conformance gate, and fences
  off model lists / the Claude bullets.
- ``extract_codex_models`` parses the recommended slugs and flags only the
  unexpected ones (deprecated models excluded).

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
REASONING_SAMPLE = REPO_ROOT / "tests" / "fixtures" / "codex-config-reference-sample.md"
MODELS_SAMPLE = REPO_ROOT / "tests" / "fixtures" / "codex-models-sample.md"


def _load(name: str) -> Any:
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def test_validate_docs_enforces_rules() -> None:
    mod = _load("check_codex_source")
    cfg = {
        "validate": {
            "min_bytes": 20,
            "must_contain_all": ["model_reasoning_effort", "config.toml"],
        }
    }
    mod.validate_docs("model_reasoning_effort lives in config.toml, padded out here.", cfg)
    with pytest.raises(ValueError):
        mod.validate_docs("tiny", cfg)  # below min_bytes + missing substrings
    with pytest.raises(ValueError):
        mod.validate_docs("x" * 100, cfg)  # long enough but missing substrings


def test_docs_signature_hashes_only_in_scope_span(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load("check_codex_source")
    base = REASONING_SAMPLE.read_text()
    out_of_scope = base + "\n\nUnrelated paragraph about providers and telemetry.\n"
    in_scope = base.replace(
        '"minimal | low | medium | high | xhigh"',
        '"minimal | low | medium | high | xhigh | ultra"',
        1,
    )

    monkeypatch.setattr(mod, "fetch_text", lambda url: base)
    sig_base = mod.docs_signature()
    monkeypatch.setattr(mod, "fetch_text", lambda url: out_of_scope)
    sig_out = mod.docs_signature()
    monkeypatch.setattr(mod, "fetch_text", lambda url: in_scope)
    sig_in = mod.docs_signature()

    assert sig_base == sig_out, "out-of-scope docs edit must NOT change the gate signature"
    assert sig_base != sig_in, "in-scope docs edit MUST change the gate signature"


def test_build_user_message_includes_docs_facts() -> None:
    mod = _load("update_codex")
    msg = mod.build_user_message("SELECTOR", docs_facts='{"reasoning_effort": ["low", "xhigh"]}')
    assert "<docs_facts" in msg
    assert "reasoning_effort" in msg

    msg_none = mod.build_user_message("S", docs_facts=None)
    assert "<docs_facts" not in msg_none


def test_read_docs_facts_reads_committed_snapshot() -> None:
    mod = _load("update_codex")
    facts = mod.read_docs_facts()
    assert facts is not None  # the committed snapshot exists
    assert "reasoning_effort" in facts


def test_prompt_documents_docs_facts_and_scope() -> None:
    prompt = (UPDATE_DIR / "prompt-codex.md").read_text()
    assert "<docs_facts" in prompt
    assert "validate_effort_conformance" in prompt
    # The Codex methods are in scope; model lists are fenced off.
    assert "codex-cli" in prompt
    assert "openai-api" in prompt
    assert "supports-models" in prompt


def test_sources_codex_has_reasoning_and_models_entries() -> None:
    import json

    sources = json.loads((UPDATE_DIR / "sources-codex.json").read_text())
    assert "config-reference.md" in sources["reasoning_docs"]["url"]
    assert "model_reasoning_effort" in sources["reasoning_docs"]["validate"]["must_contain_all"]
    assert "models.md" in sources["models_docs"]["url"]


# --------------------------------------------------------------------------- #
# Model flag
# --------------------------------------------------------------------------- #


def test_recommended_slugs_parsed_from_section() -> None:
    mod = _load("extract_codex_models")
    slugs = mod.recommended_slugs(MODELS_SAMPLE.read_text())
    assert slugs == ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"]
    # Deprecated models must not leak into the recommended list.
    assert "gpt-5.2" not in slugs
    assert "gpt-5.3-codex" not in slugs


def test_unexpected_models_flags_only_new_slugs() -> None:
    mod = _load("extract_codex_models")
    base = MODELS_SAMPLE.read_text()
    # No surprises against the known baseline.
    assert mod.unexpected_models(base) == []
    # A brand-new recommended model is flagged.
    drifted = base.replace(
        'slug="gpt-5.3-codex-spark"',
        'slug="gpt-5.6"',
    )
    assert "gpt-5.6" in mod.unexpected_models(drifted)


def test_models_parse_raises_on_restructure() -> None:
    mod = _load("extract_codex_models")
    with pytest.raises(mod.ModelsParseError):
        mod.recommended_slugs("# Some other page\n\nNo recommended models heading.\n")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
