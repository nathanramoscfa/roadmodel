#!/usr/bin/env python3
"""Render ``docs/model-selector.txt`` -> ``docs/model-selector.md``.

The .txt is the single source of truth (XML-shaped spec consumed by AI
assistants via @model-selector.txt). The .md is a human-readable mirror
generated from the .txt by this script. Never hand-edit the .md.

Usage:
    python update/render_md.py            # write/update the .md
    python update/render_md.py --check    # exit 1 if .md is stale

The Monday refresh runs this after Opus updates the .txt so the .md is
always regenerated. Tests run --check to catch drift.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

# Sibling import (update/ is not a package) — ONE definition of how to match a
# selector element; see update/selector_re.py for why prose broke the old one.
_UPDATE_DIR = Path(__file__).resolve().parent
if str(_UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_UPDATE_DIR))
# E402/I001 are expected after the path guard above.
from selector_re import METHOD_RE as _METHOD_RE  # noqa: E402, I001
from selector_re import MODEL_RE as _MODEL_RE  # noqa: E402, I001

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_TXT = REPO_ROOT / "docs" / "model-selector.txt"
SELECTOR_MD = REPO_ROOT / "docs" / "model-selector.md"

TIER_LABELS = {
    "very-high": "Very High Cost Tier",
    "high": "High Cost Tier",
    "medium": "Medium Cost Tier",
    "low": "Low Cost Tier",
}
TIER_ORDER = ["very-high", "high", "medium", "low"]

RATING_FIELDS = [
    ("tier-coding", "Coding"),
    ("tier-planning", "Planning"),
    ("tier-agentic", "Agentic"),
    ("tier-multimodal", "Multimodal"),
    ("tier-long-context", "Long-context"),
    ("tier-knowledge", "Knowledge"),
    ("tier-speed", "Speed"),
]

PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "xai": "xAI",
    "cursor": "Cursor",
}

_TIER_RE = re.compile(r'<tier\s+cost="([^"]+)"\s*>(.*?)</tier>', re.DOTALL)
# Attribute values may embed BACKSLASH-ESCAPED quotes (the claude-code
# method's best-for quotes `\"ultracode\": true`). `"([^"]*)"` would stop at
# the first inner quote and render a value truncated mid-sentence, so match
# escape sequences explicitly and unescape them for the human-readable .md.
_ATTR_RE = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"', re.DOTALL)
_ESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)
_PRINCIPLE_RE = re.compile(r"<principle>(.*?)</principle>", re.DOTALL)


def _section(content: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", content, re.DOTALL)
    if not m:
        raise ValueError(f"<{tag}> not found in source")
    return textwrap.dedent(m.group(1)).strip()


def _parse_attrs(blob: str) -> dict[str, str]:
    return {name: _ESCAPE_RE.sub(r"\1", value) for name, value in _ATTR_RE.findall(blob)}


def render_header() -> str:
    return (
        "<!-- AUTO-GENERATED. DO NOT EDIT.\n"
        "Source of truth: docs/model-selector.txt\n"
        "Regenerate with: python update/render_md.py\n"
        "-->\n\n"
        "# roadmodel\n\n"
        "Human-readable rendering of "
        "[`docs/model-selector.txt`](model-selector.txt). The `.txt` is the\n"
        "single source of truth; this file is regenerated from it by\n"
        "[`update/render_md.py`](../update/render_md.py). Edit the `.txt` and\n"
        "rerun the renderer.\n"
    )


def render_instruction(content: str) -> str:
    body = _section(content, "instruction")
    return f"## Instruction\n\n{body}\n"


def render_usage(content: str) -> str:
    body = _section(content, "usage")
    return f"## Usage\n\n{body}\n"


def render_objective(content: str) -> str:
    body = _section(content, "objective")
    body = re.sub(r"^PRIMARY:", "**PRIMARY:**", body, flags=re.MULTILINE)
    body = re.sub(
        r"^SECONDARY \(tie-breaker only\):",
        "**SECONDARY (tie-breaker only):**",
        body,
        flags=re.MULTILINE,
    )
    return f"## Objective\n\n{body}\n"


def render_pricing_context(content: str) -> str:
    body = _section(content, "pricing-context")
    return f"## Pricing Context\n\n{body}\n"


def render_max_mode(content: str) -> str:
    body = _section(content, "max-mode-context")
    return f"## Max Mode Context\n\n{body}\n"


def render_thinking_context(content: str) -> str:
    body = _section(content, "thinking-context")
    return f"## Thinking Context\n\n{body}\n"


def render_benchmark_sources(content: str) -> str:
    body = _section(content, "benchmark-sources")
    return f"## Benchmark Sources\n\n{body}\n"


def render_task_categories(content: str) -> str:
    body = _section(content, "task-categories")
    return f"## Task Categories\n\n{body}\n"


def _format_price(price: str) -> str:
    """Append /M after a numeric price; leave non-numeric prices alone.

    "$5.00" -> "$5.00/M"
    "varies (routes to top-tier model)" -> "varies (routes to top-tier model)"
    "~$1.25 (Auto + Composer pool)" -> "~$1.25/M (Auto + Composer pool)"
    """
    m = re.match(r"^(~?\$\d+(?:\.\d+)?)(\s+.*)?$", price.strip())
    if not m:
        return price
    amount, suffix = m.group(1), m.group(2) or ""
    return f"{amount}/M{suffix}"


def _render_model_card(attrs: dict[str, str]) -> str:
    name = attrs["name"]
    mid = attrs["id"]
    in_price = _format_price(attrs["input-price-per-1m"])
    out_price = _format_price(attrs["output-price-per-1m"])

    ratings = " · ".join(f"{label} **{attrs[key]}**" for key, label in RATING_FIELDS)

    headline = attrs.get("headline-benchmarks", "").strip() or "-"
    pricing_notes = attrs.get("pricing-notes", "").strip() or "-"
    best_for = attrs.get("best-for", "").strip()

    return "\n".join(
        [
            f"#### {name} — `{mid}`",
            "",
            f"- **Pricing:** Input {in_price} · Output {out_price}",
            f"- **Tier ratings:** {ratings}",
            f"- **Headline benchmarks:** {headline}",
            f"- **Pricing notes:** {pricing_notes}",
            f"- **Best for:** {best_for}",
        ]
    )


def render_model_options(content: str) -> str:
    block = _section(content, "model-options")
    first_tier_idx = block.find("<tier")
    preamble = block[:first_tier_idx].strip() if first_tier_idx != -1 else ""

    lines: list[str] = ["## Model Options", ""]
    if preamble:
        lines.append(preamble)
        lines.append("")

    tier_blocks = {m.group(1): m.group(2) for m in _TIER_RE.finditer(block)}
    for cost in TIER_ORDER:
        if cost not in tier_blocks:
            continue
        lines.append(f"### {TIER_LABELS[cost]}")
        lines.append("")
        for model_match in _MODEL_RE.finditer(tier_blocks[cost]):
            attrs = _parse_attrs(model_match.group(1))
            lines.append(_render_model_card(attrs))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_method_card(attrs: dict[str, str]) -> str:
    name = attrs["name"]
    mid = attrs["id"]
    billing = attrs.get("billing", "-")
    requires = attrs.get("requires", "-")
    supports = attrs.get("supports-models", "-")
    max_mode = attrs.get("exposes-max-mode", "?")
    thinking = attrs.get("exposes-thinking", "?")
    # Output-contract v2 gates the ORCHESTRATION line on this attribute, so the
    # human-readable mirror lists it alongside the other two platform dials.
    orchestration = attrs.get("exposes-orchestration", "?")
    best_for = attrs.get("best-for", "").strip()

    return "\n".join(
        [
            f"#### {name} — `{mid}`",
            "",
            f"- **Billing:** {billing} (requires {requires})",
            f"- **Supports models:** {supports}",
            (
                f"- **Toggles:** Max Mode — {max_mode} · Thinking — {thinking} "
                f"· Orchestration — {orchestration}"
            ),
            f"- **Best for:** {best_for}",
        ]
    )


def render_access_methods(content: str) -> str:
    block = _section(content, "access-methods")
    first_idx = block.find("<method")
    preamble = block[:first_idx].strip() if first_idx != -1 else ""

    lines: list[str] = ["## Access Methods", ""]
    if preamble:
        lines.append(preamble)
        lines.append("")

    current_provider: str | None = None
    for match in _METHOD_RE.finditer(block):
        attrs = _parse_attrs(match.group(1))
        provider = attrs.get("provider", "")
        if provider != current_provider:
            current_provider = provider
            label = PROVIDER_LABELS.get(provider, provider.title() or "Other")
            lines.append(f"### {label}")
            lines.append("")
        lines.append(_render_method_card(attrs))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_selection_algorithm(content: str) -> str:
    body = _section(content, "selection-algorithm")
    return f"## Selection Algorithm\n\n{body}\n"


def render_access_selection(content: str) -> str:
    body = _section(content, "access-selection")
    return f"## Access Selection\n\n{body}\n"


def render_conversation_principles(content: str) -> str:
    block = _section(content, "conversation-principles")
    items = [m.group(1).strip() for m in _PRINCIPLE_RE.finditer(block)]
    rendered = "\n".join(f"- {item}" for item in items)
    return f"## Conversation Principles\n\n{rendered}\n"


def render_output_format(content: str) -> str:
    body = _section(content, "output-format")
    return f"## Output Format\n\n{body}\n"


def render(source_text: str) -> str:
    parts = [
        render_header(),
        render_instruction(source_text),
        render_usage(source_text),
        render_objective(source_text),
        render_pricing_context(source_text),
        render_max_mode(source_text),
        render_thinking_context(source_text),
        render_benchmark_sources(source_text),
        render_task_categories(source_text),
        render_model_options(source_text),
        render_access_methods(source_text),
        render_selection_algorithm(source_text),
        render_access_selection(source_text),
        render_conversation_principles(source_text),
        render_output_format(source_text),
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the on-disk .md does not match what would be rendered.",
    )
    args = parser.parse_args()

    rendered = render(SELECTOR_TXT.read_text())

    if args.check:
        existing = SELECTOR_MD.read_text() if SELECTOR_MD.exists() else ""
        if existing != rendered:
            sys.stderr.write(
                f"{SELECTOR_MD.relative_to(REPO_ROOT)} is out of sync with "
                f"{SELECTOR_TXT.relative_to(REPO_ROOT)}.\n"
                "Regenerate with: python update/render_md.py\n"
            )
            return 1
        return 0

    SELECTOR_MD.write_text(rendered)
    print(f"Wrote {SELECTOR_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
