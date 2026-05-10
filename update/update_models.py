#!/usr/bin/env python3
"""Refresh docs/model-selector.txt and docs/model-tier-cost-scale.md from
upstream pricing and benchmark sources using Opus 4.7."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any

import re

import requests
from anthropic import Anthropic
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
UPDATE_DIR = REPO_ROOT / "update"

SELECTOR_PATH = DOCS_DIR / "model-selector.txt"
COST_SCALE_PATH = DOCS_DIR / "model-tier-cost-scale.md"

MODEL_ID = "claude-opus-4-7"
MAX_TOKENS = 64000
USER_AGENT = (
    "model-selector-updater/1.0 "
    "(+https://github.com/nathanramoscfa/model-selector)"
)
FETCH_TIMEOUT = 30
DEFAULT_MAX_BYTES = 150_000
HTML_SNIFF_BYTES = 1024


def fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        },
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def looks_like_html(content: str) -> bool:
    head = content[:HTML_SNIFF_BYTES].lower()
    return "<!doctype html" in head or "<html" in head


def strip_html(content: str) -> str:
    """Reduce HTML to visible text plus inline-script contents.

    SPA leaderboards frequently inline benchmark data as JSON inside
    <script> tags (e.g. SWE-bench's per-instance results). BeautifulSoup's
    get_text() excludes script bodies, so we extract data-bearing scripts
    separately and append them, letting downstream truncation cap the size.
    Style/link/meta/noscript/svg carry no data and are dropped.
    """
    soup = BeautifulSoup(content, "html.parser")
    data_scripts: list[str] = []
    for s in soup.find_all("script"):
        body = s.string or s.get_text() or ""
        if len(body) > 500 and ("{" in body or "[" in body):
            data_scripts.append(body)
    for tag in soup(["style", "noscript", "svg", "link", "meta", "script"]):
        tag.decompose()
    visible = soup.get_text(separator=" ", strip=True)
    combined = visible + " " + " ".join(data_scripts)
    return re.sub(r"\s+", " ", combined).strip()


def normalize_content(content: str, max_bytes: int) -> str:
    if looks_like_html(content):
        content = strip_html(content)
    if len(content) > max_bytes:
        content = content[:max_bytes]
    return content


def validate_content(content: str, rules: dict[str, Any] | None) -> str | None:
    """Return None if content passes the rules, else a short failure reason.

    Guards against silently feeding empty SPA shells to Opus. A source whose
    fetched body is too small or missing expected markers is treated as a
    fetch failure rather than valid input.
    """
    if not rules:
        return None
    min_bytes = rules.get("min_bytes")
    if min_bytes is not None and len(content) < min_bytes:
        return f"content too small ({len(content)} bytes < {min_bytes})"
    must_contain = rules.get("must_contain_all") or []
    haystack = content.lower()
    missing = [m for m in must_contain if m.lower() not in haystack]
    if missing:
        return f"missing expected markers: {missing}"
    return None


def gather_sources() -> tuple[list[dict[str, str]], list[str]]:
    sources_config = json.loads((UPDATE_DIR / "sources.json").read_text())
    fetched: list[dict[str, str]] = []
    errors: list[str] = []

    def try_fetch(kind: str, src: dict[str, Any]) -> None:
        try:
            raw = fetch(src["url"])
        except Exception as exc:
            errors.append(f"{src['url']}: fetch failed: {exc}")
            return
        max_bytes = src.get("max_bytes", DEFAULT_MAX_BYTES)
        content = normalize_content(raw, max_bytes)
        reason = validate_content(content, src.get("validate"))
        if reason is not None:
            errors.append(f"{src['url']}: validation failed: {reason}")
            return
        fetched.append(
            {
                "type": kind,
                "name": src["name"],
                "url": src["url"],
                "content": content,
            }
        )

    try_fetch("pricing", sources_config["pricing"])
    for src in sources_config["benchmarks"]:
        try_fetch("benchmark", src)

    return fetched, errors


def build_user_message(
    selector_text: str,
    cost_scale_text: str,
    fetched: list[dict[str, str]],
    fetch_errors: list[str],
) -> str:
    blocks: list[str] = [
        f'<current_file path="docs/model-selector.txt">\n{selector_text}\n</current_file>',
        f'<current_file path="docs/model-tier-cost-scale.md">\n{cost_scale_text}\n</current_file>',
    ]
    for src in fetched:
        blocks.append(
            f'<source type="{src["type"]}" name="{src["name"]}" url="{src["url"]}">\n'
            f'{src["content"]}\n'
            f"</source>"
        )
    if fetch_errors:
        blocks.append("<fetch_errors>\n" + "\n".join(fetch_errors) + "\n</fetch_errors>")
    return "\n\n".join(blocks)


def call_opus(system_prompt: str, user_message: str, api_key: str) -> str:
    """Return assistant text from Opus via streaming (long-request policy)."""
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
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )


def parse_result(raw: str) -> dict[str, Any]:
    """Parse the model's JSON response, tolerating prose preamble/epilogue.

    The system prompt asks for a single JSON object with no surrounding
    text, but the model occasionally emits reasoning before the object.
    Try a strict parse first; on failure, fall back to extracting from the
    first `{` to the last `}`.
    """
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1 :] if first_nl != -1 else text
        if text.endswith("```"):
            text = text[: -len("```")].rstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def load_fixture(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a pre-fetched-sources fixture, bypassing network I/O.

    Shape: {"fetched": [{type, name, url, content}, ...],
            "fetch_errors": ["...", ...]}.
    Used by --fixture to exercise the lifecycle rules in update/prompt.md
    against synthetic Cursor pricing payloads (e.g. "what happens when
    GPT-5.6 appears at $40/M output?") without waiting for upstream
    changes.
    """
    payload = json.loads(path.read_text())
    fetched = payload.get("fetched", [])
    fetch_errors = payload.get("fetch_errors", [])
    return fetched, fetch_errors


def write_dry_run_report(
    selector_before: str,
    selector_after: str,
    cost_scale_before: str,
    cost_scale_after: str,
    summary: str,
    warnings: list[str],
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
            fromfile="current/model-selector.txt",
            tofile="proposed/model-selector.txt",
        )
    )
    print("\n=== Diff: docs/model-tier-cost-scale.md ===")
    sys.stdout.writelines(
        difflib.unified_diff(
            cost_scale_before.splitlines(keepends=True),
            cost_scale_after.splitlines(keepends=True),
            fromfile="current/model-tier-cost-scale.md",
            tofile="proposed/model-tier-cost-scale.md",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't write to disk or update .last-summary.txt / "
            ".last-warnings.txt. Print the proposed diff against the "
            "current docs plus the summary and warnings. Useful for "
            "previewing what the next refresh would change."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help=(
            "Path to a JSON file with pre-fetched source content "
            "(skips network fetching). Shape: "
            '{"fetched": [{"type": ..., "name": ..., "url": ..., '
            '"content": ...}, ...], "fetch_errors": [...]}. Useful for '
            "exercising Model lifecycle rules with synthetic pricing "
            "inputs (e.g. test that a hypothetical costlier successor "
            "does not displace the predecessor)."
        ),
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("ANTHROPIC_API_KEY is not set\n")
        return 1

    system_prompt = (UPDATE_DIR / "prompt.md").read_text()
    selector_text = SELECTOR_PATH.read_text()
    cost_scale_text = COST_SCALE_PATH.read_text()

    if args.fixture is not None:
        fetched, fetch_errors = load_fixture(args.fixture)
    else:
        fetched, fetch_errors = gather_sources()
    if not fetched:
        sys.stderr.write(
            "All source fetches failed; refusing to call Opus.\n"
            + "\n".join(fetch_errors)
            + "\n"
        )
        return 3

    user_message = build_user_message(
        selector_text, cost_scale_text, fetched, fetch_errors
    )

    raw = call_opus(system_prompt, user_message, api_key)
    try:
        result = parse_result(raw)
    except json.JSONDecodeError:
        sys.stderr.write("Model did not return valid JSON. Raw output:\n")
        sys.stderr.write(raw)
        sys.stderr.write("\n")
        return 2

    new_selector = result["model_selector_txt"]
    new_cost_scale = result["model_tier_cost_scale_md"]
    summary = result.get("summary") or "Refresh model docs"
    warnings = list(result.get("warnings") or [])
    if fetch_errors:
        warnings.extend(f"Fetch error: {err}" for err in fetch_errors)

    if args.dry_run:
        write_dry_run_report(
            selector_text, new_selector,
            cost_scale_text, new_cost_scale,
            summary, warnings,
        )
        return 0

    SELECTOR_PATH.write_text(new_selector)
    COST_SCALE_PATH.write_text(new_cost_scale)

    # Regenerate the human-readable mirror from the updated .txt so the two
    # files commit together. render_md.py imports without side effects.
    from render_md import render, SELECTOR_MD

    SELECTOR_MD.write_text(render(SELECTOR_PATH.read_text()))

    (UPDATE_DIR / ".last-summary.txt").write_text(summary)
    if warnings:
        (UPDATE_DIR / ".last-warnings.txt").write_text("\n".join(warnings))

    print(summary)
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
