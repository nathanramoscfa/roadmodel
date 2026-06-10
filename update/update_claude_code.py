#!/usr/bin/env python3
"""Refresh the Claude Code surface-parameter blocks of
``docs/model-selector.txt`` from the upstream
``anthropics/claude-code`` CHANGELOG using Opus 4.7.

Scope is narrow: only `<thinking-context>`, `<max-mode-context>`, and
the `<method id="claude-code">` element in `<access-methods>` may be
mutated — see ``update/prompt-claude-code.md`` for the full rules.
This script is deliberately isolated from ``update/update_models.py``
(the Cursor pricing cron) per the blast-radius-isolation principle:
the two crons run on different cadences against different sources and
own non-overlapping slices of the selector.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
UPDATE_DIR = REPO_ROOT / "update"
CACHE_DIR = UPDATE_DIR / ".cache"

SELECTOR_PATH = DOCS_DIR / "model-selector.txt"
SOURCES_PATH = UPDATE_DIR / "sources-claude-code.json"
PROMPT_PATH = UPDATE_DIR / "prompt-claude-code.md"
PENDING_BULLETS_PATH = CACHE_DIR / "pending-bullets.json"
LAST_VERSION_PATH = CACHE_DIR / "claude-code-last-version"
CONSUMED_VERSIONS_PATH = CACHE_DIR / "consumed-versions.json"
LAST_SUMMARY_PATH = UPDATE_DIR / ".last-claude-code-summary.txt"
LAST_WARNINGS_PATH = UPDATE_DIR / ".last-claude-code-warnings.txt"
# The committed docs-facts snapshot (refreshed by extract_claude_code_effort.py
# before this step). Fed to Opus as authoritative for effort/thinking content.
EFFORT_JSON_PATH = UPDATE_DIR / "claude-code-effort.json"
DOCS_URL = "https://code.claude.com/docs/en/model-config.md"

MODEL_ID = "claude-opus-4-7"
MAX_TOKENS = 64000
USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Matches a Markdown H2 version header such as `## 2.1.158`. Tolerates
# leading whitespace and an optional trailing date/note in parentheses,
# but the captured group is the bare semver-ish version string.
_VERSION_HEADER_RE = re.compile(r"^\s*##\s+(\d+\.\d+\.\d+)\b", re.MULTILINE)
# Matches a Markdown bullet (`-` or `*`) with at least one space and
# captures the bullet text. Multi-line bullets are collapsed to the
# first line — this cron only inspects bullet text for keyword
# triggers, not full paragraph context.
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)(?:\n|$)", re.MULTILINE)


def fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain, text/markdown, */*",
        },
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def parse_versions(changelog: str) -> list[tuple[str, list[str]]]:
    """Return [(version, [bullet, ...]), ...] in newest-first order.

    Uses the CHANGELOG's own ordering — `anthropics/claude-code`
    keeps newest at top — rather than sorting semver ourselves. That
    keeps the contract simple: the file's natural reading order
    determines what's "new".
    """
    matches = list(_VERSION_HEADER_RE.finditer(changelog))
    if not matches:
        return []
    out: list[tuple[str, list[str]]] = []
    for idx, m in enumerate(matches):
        version = m.group(1)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(changelog)
        section = changelog[start:end]
        bullets = [b.strip() for b in _BULLET_RE.findall(section)]
        out.append((version, bullets))
    return out


def new_versions(
    parsed: list[tuple[str, list[str]]], last_version: str | None
) -> list[tuple[str, list[str]]]:
    """Slice `parsed` to entries newer than `last_version`.

    `parsed` is newest-first; everything BEFORE the entry matching
    `last_version` is new. If `last_version` is not found (cache miss
    or a CHANGELOG history rewrite), treat the most-recent 5 entries
    as new — bounded to keep first-run / cache-loss scenarios from
    paging the entire CHANGELOG into a single Opus call.
    """
    if last_version is None:
        return parsed[:5]
    for idx, (version, _) in enumerate(parsed):
        if version == last_version:
            return parsed[:idx]
    # Cache miss: bounded backstop.
    return parsed[:5]


def write_pending_bullets(new_entries: list[tuple[str, list[str]]]) -> None:
    """Persist the pre-Opus version+bullet snapshot for the validator.

    The post-step validator (`update/validate_claude_code_diff.py`)
    reads this file to (a) verify Opus's `consumed_versions` covers
    every version we asked it about, and (b) cross-check that bullets
    containing trigger keywords produce matching tokens in the diff.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_BULLETS_PATH.write_text(
        json.dumps(
            [{"version": v, "bullets": bs} for v, bs in new_entries],
            indent=2,
        )
    )


def read_last_version() -> str | None:
    if not LAST_VERSION_PATH.exists():
        return None
    value = LAST_VERSION_PATH.read_text().strip()
    return value or None


def read_docs_facts() -> str | None:
    """The committed docs-facts snapshot (update/claude-code-effort.json), or
    None if it has not been generated yet."""
    if not EFFORT_JSON_PATH.exists():
        return None
    return EFFORT_JSON_PATH.read_text()


def build_user_message(
    selector_text: str,
    changelog_url: str,
    changelog_text: str,
    new_entries: list[tuple[str, list[str]]],
    docs_facts: str | None = None,
) -> str:
    versions_only = [v for v, _ in new_entries]
    blocks = [
        f'<current_file path="docs/model-selector.txt">\n{selector_text}\n</current_file>',
        (f'<source type="changelog" url="{changelog_url}">\n{changelog_text}\n</source>'),
        (
            "<new_versions_since_last_run>\n"
            f"{json.dumps(versions_only)}\n"
            "</new_versions_since_last_run>"
        ),
    ]
    if docs_facts:
        blocks.append(f'<docs_facts source="{DOCS_URL}">\n{docs_facts}\n</docs_facts>')
    return "\n\n".join(blocks)


def call_opus(system_prompt: str, user_message: str, api_key: str) -> str:
    """Return assistant text from Opus via streaming (long-request policy).

    No tools — this prompt's inputs are fully self-contained in the
    user message. Web search is intentionally NOT enabled because
    citations from outside the provided inputs would invite drift; the
    CHANGELOG (change trigger) and the deterministically-extracted
    <docs_facts> (authoritative for effort/thinking content) are the
    only authoritative inputs.
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
    with client.messages.stream(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        messages=user_blocks,
    ) as stream:
        response = stream.get_final_message()
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )


_FENCED_BLOCK_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.DOTALL)


def parse_result(raw: str) -> dict[str, Any]:
    """Parse the model's JSON response, tolerating prose preamble/epilogue.

    Mirrors the strategy in ``update/update_models.py::parse_result``.
    Both crons share the ``roadmodel_txt`` JSON key so the parser
    selection heuristic (longest plausible payload wins) generalizes.
    """
    text = raw.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if text.startswith("```") and text.endswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            inner = text[first_nl + 1 : -3].rstrip()
            try:
                return json.loads(inner)
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
    return json.loads(text[start : end + 1])


def write_dry_run_report(
    selector_before: str,
    selector_after: str,
    summary: str,
    warnings: list[str],
    new_entries: list[tuple[str, list[str]]],
) -> None:
    print("=== New versions since last run ===")
    for v, bullets in new_entries:
        print(f"  - {v}  ({len(bullets)} bullets)")
    print()
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
            "Don't write to disk or update .last-claude-code-summary / "
            ".last-claude-code-warnings. Print the proposed diff against "
            "the current selector plus the summary and warnings. Useful "
            "for previewing what the next refresh would change."
        ),
    )
    parser.add_argument(
        "--docs-changed",
        action="store_true",
        help=(
            "Set by the workflow when the in-scope model-config docs span "
            "changed. Forces the Opus reconciliation to run even when there "
            "are no new CHANGELOG versions, so <thinking-context> and the "
            "claude-code best-for can be brought in line with the docs."
        ),
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("ANTHROPIC_API_KEY is not set\n")
        return 1

    system_prompt = PROMPT_PATH.read_text()
    selector_text = SELECTOR_PATH.read_text()
    source_cfg = json.loads(SOURCES_PATH.read_text())["changelog"]
    changelog_url = source_cfg["url"]

    try:
        changelog_text = fetch(changelog_url)
    except Exception as exc:
        sys.stderr.write(
            f"Failed to fetch Claude Code CHANGELOG ({exc!r}); refusing to call Opus.\n"
        )
        return 3

    parsed = parse_versions(changelog_text)
    if not parsed:
        sys.stderr.write(
            "CHANGELOG parse produced zero version entries; refusing to "
            "call Opus (likely an upstream format change).\n"
        )
        return 4

    last_version = read_last_version()
    new_entries = new_versions(parsed, last_version)
    write_pending_bullets(new_entries)

    docs_facts = read_docs_facts()

    if not new_entries and not args.docs_changed:
        msg = (
            f"No new Claude Code releases since {last_version} and the "
            "in-scope docs span is unchanged; nothing to do."
        )
        print(msg)
        if not args.dry_run:
            LAST_SUMMARY_PATH.write_text("No changes detected.\n")
            if LAST_WARNINGS_PATH.exists():
                LAST_WARNINGS_PATH.unlink()
        return 0

    if not new_entries:
        print(
            f"No new CHANGELOG releases since {last_version}, but the in-scope "
            "docs span changed — running Opus to reconcile <thinking-context> "
            "and the claude-code best-for with the docs."
        )

    user_message = build_user_message(
        selector_text, changelog_url, changelog_text, new_entries, docs_facts
    )

    raw = call_opus(system_prompt, user_message, api_key)
    try:
        result = parse_result(raw)
    except json.JSONDecodeError:
        sys.stderr.write("Model did not return valid JSON. Raw output:\n")
        sys.stderr.write(raw)
        sys.stderr.write("\n")
        return 2

    new_selector = result["roadmodel_txt"]
    summary = result.get("summary") or "Refresh Claude Code surface parameters"
    warnings = list(result.get("warnings") or [])
    consumed_versions = list(result.get("consumed_versions") or [])

    if args.dry_run:
        write_dry_run_report(selector_text, new_selector, summary, warnings, new_entries)
        print("\n=== consumed_versions ===")
        for v in consumed_versions:
            print(f"  - {v}")
        return 0

    SELECTOR_PATH.write_text(new_selector)
    LAST_SUMMARY_PATH.write_text(summary + "\n")
    if warnings:
        LAST_WARNINGS_PATH.write_text("\n".join(warnings) + "\n")
    elif LAST_WARNINGS_PATH.exists():
        LAST_WARNINGS_PATH.unlink()

    # Persist Opus's consumed_versions verbatim for the validator.
    # The validator's coverage check compares this list against the
    # pending-bullets.json that was written PRE-Opus, so a missing
    # version surfaces as a hard FAIL. Writing this from a separate
    # step (e.g. echoing the pending list) would defeat the check.
    CONSUMED_VERSIONS_PATH.write_text(json.dumps({"consumed_versions": consumed_versions}) + "\n")

    # Stage the newest version processed as the next "last_version".
    # The workflow promotes the stage file → canonical after the
    # validator and PR-open steps both succeed.
    newest_processed = new_entries[0][0]
    (CACHE_DIR / "claude-code-last-version.new").write_text(newest_processed + "\n")

    print(summary)
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
