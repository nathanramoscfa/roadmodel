"""docs/user-context.example.md is the file every new user copies. It says
what the user pays for and how they work, and leaves model versions to the
catalog: a version written there goes stale the day its successor ships. On
2026-10-01 the operator's own copy still routed Gemini work to Gemini 3.1 Pro,
a day after Gemini 3.8 Flash superseded it. The Local models (Ollama)
section is the exception: it records which models the user has pulled, by
catalog id."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "docs" / "user-context.example.md"

# A model family followed by a version ("Opus 5.5", "GPT-6", "Gemini 3.8"), or
# a versioned catalog id ("claude-opus-4-6", "gemini-3.1-pro"). A percentage is
# not a version ("Fable 50% sub-cap").
PINNED = re.compile(
    r"\b(?:Opus|Sonnet|Haiku|Fable|Mythos|Gemini|GPT|Grok|Kimi|GLM|DeepSeek)"
    r"[ -]?V?\d+(?:\.\d+)?(?![\d.]*%)"
    r"|\b(?:claude-(?:opus|sonnet|haiku|fable)|gemini|gpt|grok|kimi|glm|deepseek)-v?\d"
)


def _without_local_models(text: str) -> str:
    """The example minus its Local models (Ollama) section, which names pulled
    models by catalog id: user state, not a pinned pick."""
    return re.sub(r"\n## Local models \(Ollama\)\n.*?(?=\n## )", "\n", text, flags=re.S)


def test_the_example_pins_no_model_version() -> None:
    text = _without_local_models(EXAMPLE.read_text(encoding="utf-8"))
    hits = [line.strip() for line in text.splitlines() if PINNED.search(line)]
    assert hits == [], "the user-context example pins a model version: " + " | ".join(hits)
    assert "**Describe access, not models.**" in text


def test_the_check_catches_a_pinned_version() -> None:
    for line in (
        "3. Gemini-adequate work → Antigravity (Gemini 3.8 Flash / 3.1 Pro).",
        "- Phase roadmap: Opus 5.5 at `Max`, every phase.",
        "Codex → GPT-6 Astra · Medium.",
        "(`claude-opus-4-6-thinking`, `claude-sonnet-4-6`)",
    ):
        assert PINNED.search(line), line
    for line in (
        "| claude.ai Max — Fable 50% sub-cap | 7 days |",
        "the current Sonnet at `High`",
        "(e.g., an Opus Fast or a GPT Fast mode)",
    ):
        assert not PINNED.search(line), line
