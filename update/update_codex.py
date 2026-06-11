#!/usr/bin/env python3
"""Reconcile the Codex/OpenAI reasoning-effort blocks of
``docs/model-selector.txt`` with OpenAI's official Codex config-reference docs
using Opus 4.7.

Codex has no usable changelog, so this cron is purely docs-driven: the
deterministically-extracted ``<docs_facts>`` (``update/codex-reasoning.json``)
is the authoritative input, and the change trigger is the in-scope reasoning
span hash (``update/check_codex_source.py``). Scope is narrow: only the OpenAI
bullet + output mapping in ``<thinking-context>`` and the ``codex-cli`` /
``openai-api`` ``best-for`` text may be mutated — see ``update/prompt-codex.md``
for the full rules. The offline conformance gate
(``update/validate_effort_conformance.py`` check D) is the deterministic
backstop that hard-fails a non-conformant Opus edit.

This script is deliberately isolated from ``update/update_claude_code.py`` and
``update/update_models.py`` per the blast-radius-isolation principle: the crons
own non-overlapping slices of the selector and run on staggered cadences.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import TextBlock

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
UPDATE_DIR = REPO_ROOT / "update"

SELECTOR_PATH = DOCS_DIR / "model-selector.txt"
PROMPT_PATH = UPDATE_DIR / "prompt-codex.md"
# The committed docs-facts snapshot (refreshed by extract_codex_reasoning.py
# before this step). Fed to Opus as authoritative for reasoning-effort content.
REASONING_JSON_PATH = UPDATE_DIR / "codex-reasoning.json"
LAST_SUMMARY_PATH = UPDATE_DIR / ".last-codex-summary.txt"
LAST_WARNINGS_PATH = UPDATE_DIR / ".last-codex-warnings.txt"
DOCS_URL = "https://developers.openai.com/codex/config-reference.md"

MODEL_ID = "claude-opus-4-7"
MAX_TOKENS = 64000


def read_docs_facts() -> str | None:
    """The committed docs-facts snapshot (update/codex-reasoning.json), or None
    if it has not been generated yet."""
    if not REASONING_JSON_PATH.exists():
        return None
    return REASONING_JSON_PATH.read_text()


def build_user_message(selector_text: str, docs_facts: str | None) -> str:
    blocks = [
        f'<current_file path="docs/model-selector.txt">\n{selector_text}\n</current_file>',
    ]
    if docs_facts:
        blocks.append(f'<docs_facts source="{DOCS_URL}">\n{docs_facts}\n</docs_facts>')
    return "\n\n".join(blocks)


def call_opus(system_prompt: str, user_message: str, api_key: str) -> str:
    """Return assistant text from Opus via streaming (long-request policy).

    No tools / no web search: the deterministically-extracted ``<docs_facts>``
    is the only authoritative input, so citations from outside the provided
    inputs would only invite drift.
    """
    client = Anthropic(api_key=api_key)
    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    user_blocks = [{"role": "user", "content": user_message}]
    # The SDK accepts these plain dict shapes at runtime; its param types
    # (TextBlockParam / MessageParam) are stricter than what we pass.
    with client.messages.stream(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        system=system_blocks,  # type: ignore[arg-type]
        messages=user_blocks,  # type: ignore[arg-type]
    ) as stream:
        response = stream.get_final_message()
    return "".join(block.text for block in response.content if isinstance(block, TextBlock))


_FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.DOTALL)


def parse_result(raw: str) -> dict[str, Any]:
    """Parse the model's JSON response, tolerating prose preamble/epilogue.

    Mirrors ``update/update_claude_code.py::parse_result`` — the longest
    plausible ``roadmodel_txt`` payload wins.
    """
    text = raw.strip()

    try:
        return cast("dict[str, Any]", json.loads(text))
    except json.JSONDecodeError:
        pass

    if text.startswith("```") and text.endswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            inner = text[first_nl + 1 : -3].rstrip()
            try:
                return cast("dict[str, Any]", json.loads(inner))
            except json.JSONDecodeError:
                pass

    candidates: list[tuple[int, dict[str, Any]]] = []

    def _try_add(candidate_text: str) -> None:
        try:
            parsed = json.loads(candidate_text.strip())
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            roadmodel_txt = parsed.get("roadmodel_txt", "")
            length = len(roadmodel_txt) if isinstance(roadmodel_txt, str) else 0
            candidates.append((length, parsed))

    for block in _FENCED_BLOCK_RE.findall(text):
        _try_add(block)

    text_no_fences = _FENCED_BLOCK_RE.sub("", text).strip()
    if text_no_fences:
        _try_add(text_no_fences)
        start = text_no_fences.find("{")
        end = text_no_fences.rfind("}")
        if 0 <= start < end:
            _try_add(text_no_fences[start : end + 1])

    if candidates:
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise json.JSONDecodeError("could not extract JSON object from model output", text, 0)
    return cast("dict[str, Any]", json.loads(text[start : end + 1]))


def write_dry_run_report(
    selector_before: str, selector_after: str, summary: str, warnings: list[str]
) -> None:
    print(f"=== Summary ===\n{summary}\n")
    if warnings:
        print("=== Warnings ===")
        for w in warnings:
            print(f"  - {w}")
        print()
    print("=== Diff: docs/model-selector.txt ===")
    sys.stdout.writelines(
        difflib.unified_diff(
            selector_before.splitlines(keepends=True),
            selector_after.splitlines(keepends=True),
            fromfile="current/docs/model-selector.txt",
            tofile="proposed/docs/model-selector.txt",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't write to disk. Print the proposed diff against the current "
            "selector plus the summary and warnings."
        ),
    )
    parser.add_argument(
        "--docs-changed",
        action="store_true",
        help=(
            "Accepted for workflow symmetry with the Claude Code cron. This cron "
            "is always docs-driven, so reconciliation runs regardless."
        ),
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("ANTHROPIC_API_KEY is not set\n")
        return 1

    system_prompt = PROMPT_PATH.read_text()
    selector_text = SELECTOR_PATH.read_text()
    docs_facts = read_docs_facts()
    if docs_facts is None:
        sys.stderr.write(
            "codex-reasoning.json snapshot missing; run extract_codex_reasoning.py "
            "before this step.\n"
        )
        return 4

    user_message = build_user_message(selector_text, docs_facts)

    raw = call_opus(system_prompt, user_message, api_key)
    try:
        result = parse_result(raw)
    except json.JSONDecodeError:
        sys.stderr.write("Model did not return valid JSON. Raw output:\n")
        sys.stderr.write(raw)
        sys.stderr.write("\n")
        return 2

    new_selector = result["roadmodel_txt"]
    summary = result.get("summary") or "Reconcile Codex reasoning-effort with the docs"
    warnings = list(result.get("warnings") or [])

    if args.dry_run:
        write_dry_run_report(selector_text, new_selector, summary, warnings)
        return 0

    SELECTOR_PATH.write_text(new_selector)
    LAST_SUMMARY_PATH.write_text(summary + "\n")
    if warnings:
        LAST_WARNINGS_PATH.write_text("\n".join(warnings) + "\n")
    elif LAST_WARNINGS_PATH.exists():
        LAST_WARNINGS_PATH.unlink()

    print(summary)
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
