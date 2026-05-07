#!/usr/bin/env python3
"""Refresh docs/model-selector.txt and docs/model-tier-cost-scale.md from
upstream pricing and benchmark sources using Opus 4.7."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic

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
            content = fetch(src["url"])
        except Exception as exc:
            errors.append(f"{src['url']}: fetch failed: {exc}")
            return
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
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1 :] if first_nl != -1 else text
        if text.endswith("```"):
            text = text[: -len("```")].rstrip()
    return json.loads(text)


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("ANTHROPIC_API_KEY is not set\n")
        return 1

    system_prompt = (UPDATE_DIR / "prompt.md").read_text()
    selector_text = SELECTOR_PATH.read_text()
    cost_scale_text = COST_SCALE_PATH.read_text()

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

    SELECTOR_PATH.write_text(result["model_selector_txt"])
    COST_SCALE_PATH.write_text(result["model_tier_cost_scale_md"])

    summary = result.get("summary") or "Refresh model docs"
    (UPDATE_DIR / ".last-summary.txt").write_text(summary)

    warnings = list(result.get("warnings") or [])
    if fetch_errors:
        warnings.extend(f"Fetch error: {err}" for err in fetch_errors)
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
