"""Tests for the docs-freshness extensions to the Claude Code cron (T2).

Covers the deterministic pieces of the docs-source gate + Opus wiring:

- ``check_claude_code_source.validate_docs`` enforces min_bytes + must_contain.
- ``check_claude_code_source.docs_signature`` hashes ONLY the in-scope span —
  an out-of-scope docs edit must NOT change it; an in-scope edit must.
- ``update_claude_code.build_user_message`` includes a ``<docs_facts>`` block
  when given, and ``read_docs_facts`` reads the committed snapshot.
- The Opus prompt documents ``<docs_facts>`` and the validator's
  ``TRIGGER_KEYWORDS`` gained the docs terms.

The end-to-end ``--docs-changed`` main() flow (Opus runs with no new CHANGELOG
versions) is exercised by the workflow_dispatch dry-run, not mocked here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
SAMPLE_MD = REPO_ROOT / "tests" / "fixtures" / "model-config-sample.md"


def _load(name: str):
    sys.path.insert(0, str(UPDATE_DIR))
    try:
        mod = importlib.import_module(name)
        return importlib.reload(mod)
    finally:
        sys.path.pop(0)


def test_validate_docs_enforces_rules() -> None:
    mod = _load("check_claude_code_source")
    cfg = {
        "validate": {
            "min_bytes": 20,
            "must_contain_all": ["ultrathink", "Extended thinking"],
        }
    }
    mod.validate_docs("ultrathink and Extended thinking are here, padded out.", cfg)
    with pytest.raises(ValueError):
        mod.validate_docs("tiny", cfg)  # below min_bytes + missing substrings
    with pytest.raises(ValueError):
        mod.validate_docs("x" * 100, cfg)  # long enough but missing substrings


def test_docs_signature_hashes_only_in_scope_span(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load("check_claude_code_source")
    base = SAMPLE_MD.read_text()
    out_of_scope = base + "\n\nUnrelated paragraph about prompt caching and env vars.\n"
    in_scope = base.replace(
        "`low`, `medium`, `high`, `xhigh`, `max`",
        "`low`, `medium`, `high`, `xhigh`, `max`, `ultra`",
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
    mod = _load("update_claude_code")
    msg = mod.build_user_message(
        "SELECTOR",
        "http://changelog",
        "CHANGELOG",
        [("2.1.158", ["x"])],
        docs_facts='{"effort_levels": ["low", "xhigh"]}',
    )
    assert "<docs_facts" in msg
    assert "effort_levels" in msg

    msg_none = mod.build_user_message("S", "u", "C", [], docs_facts=None)
    assert "<docs_facts" not in msg_none


def test_read_docs_facts_reads_committed_snapshot() -> None:
    mod = _load("update_claude_code")
    facts = mod.read_docs_facts()
    assert facts is not None  # the committed snapshot exists
    assert "per_model_effort" in facts


def test_prompt_documents_docs_facts() -> None:
    prompt = (UPDATE_DIR / "prompt-claude-code.md").read_text()
    assert "<docs_facts" in prompt
    assert "validate_effort_conformance" in prompt
    # The orchestration-context must be fenced off (not this cron's lane).
    assert "<orchestration-context>" in prompt


def test_trigger_keywords_extended() -> None:
    mod = _load("validate_claude_code_diff")
    for kw in ("ultrathink", "xhigh", "max effort", "adaptive reasoning"):
        assert kw in mod.TRIGGER_KEYWORDS
