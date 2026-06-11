"""Deterministically extract DeepSeek's thinking facts from the official
DeepSeek API thinking-mode docs.

This is the DeepSeek analog of ``update/extract_gemini_thinking.py`` (which it
mirrors most closely, because both sources are HTML-only). It is the *docs* half
of the DeepSeek surface-parameter tracker, the 5th provider in the selector's
``<thinking-context>``. DeepSeek exposes a SINGLE reasoning surface, captured
from one HTML table:

1. **Thinking toggle** — ``{"thinking": {"type": "enabled/disabled"}}`` (default
   ``enabled``). Whether the model reasons before answering.
2. **Reasoning-effort enum** — ``{"reasoning_effort": "high/max"}`` (OpenAI
   format) / ``{"output_config": {"effort": "high/max"}}`` (Anthropic format),
   default ``high`` (``max`` for some complex agent requests). Unlike Codex /
   Gemini, DeepSeek effort has ONLY ``high`` and ``max`` — no ``low`` / ``medium``
   tier (for compatibility the API accepts ``low`` / ``medium`` mapped to
   ``high`` and ``xhigh`` mapped to ``max``, captured as ``effort_aliases``).

Like ``ai.google.dev``, ``api-docs.deepseek.com`` serves NO clean Markdown
endpoint (the ``.md`` suffix 404s; the models API needs auth), so this extractor
parses the page's HTML table with BeautifulSoup — the same approach the Gemini
tracker and the Cursor catalog cron use. Because HTML is noisy, the
change-detection hash (``section_sha256``) is taken over the *canonical extracted
facts* (sorted JSON), NOT the raw HTML span, so an unrelated devsite re-render
does not trip the docs-freshness cron.

The result is written as a JSON snapshot. The committed copy
(``update/deepseek-thinking.json``) is the OFFLINE source of truth for
``update/validate_effort_conformance.py``'s DeepSeek check (check F).

Exit codes: 0 ok, 3 fetch/read failure, 4 extraction failure (the docs were
restructured so the deterministic parse no longer finds what it expects —
intentionally loud so the cron surfaces it rather than shipping a silently
wrong snapshot).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "deepseek-thinking.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "deepseek-thinking.json"

DOCS_URL = "https://api-docs.deepseek.com/guides/thinking_mode"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Canonical display order for the DeepSeek reasoning vocabulary — matching the
# docs' own cell order ("enabled/disabled" and "high/max") so the snapshot reads
# the way the docs (and the selector bullet) present it. A toggle/effort value
# outside these sets is FLAGGED (a docs-added native tier is significant — it
# needs a deliberate THINKING-field mapping), never silently absorbed. This
# mirrors the Gemini extractor's unexpected_levels guard (PR #229).
TOGGLE_ORDER = ("enabled", "disabled")
EFFORT_ORDER = ("high", "max")

# Sentinel substrings that MUST survive on the page. Their absence means the
# docs were restructured and the deterministic parse can no longer be trusted —
# fail loudly instead of emitting a partial snapshot. These are literal
# server-rendered substrings (verified present in the raw HTML 2026-06-11).
REQUIRED_ANCHORS = (
    "Control Parameter",
    "reasoning_effort",
    "Thinking Mode Toggle",
    "Thinking Effort Control",
    "enabled/disabled",
    "high/max",
)


class ExtractError(RuntimeError):
    """The docs no longer match the structure this parser expects."""


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def verify_anchors(html: str) -> None:
    missing = [a for a in REQUIRED_ANCHORS if a not in html]
    if missing:
        raise ExtractError(f"expected docs anchors missing (restructure?): {missing}")


def _row_cells(row: Tag) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]


def _tables(soup: BeautifulSoup) -> list[Tag]:
    return [t for t in soup.find_all("table") if isinstance(t, Tag)]


def _find_table(soup: BeautifulSoup, header_needles: tuple[str, ...]) -> Tag:
    """Return the first table whose header row contains every needle.

    Located by HEADER CONTENT, never by index/CSS, so a layout reshuffle does
    not silently select the wrong table (the Gemini HTML lesson).
    """
    for table in _tables(soup):
        rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
        if not rows:
            continue
        header = " ".join(_row_cells(rows[0]))
        if all(n in header for n in header_needles):
            return table
    raise ExtractError(f"no table found whose header contains all of {header_needles}")


def order_values(values: list[str], order: tuple[str, ...]) -> list[str]:
    """Known values first (canonical order), then any extras sorted.

    Keeping docs-added values (not just the known baseline) means a new native
    tier flows into ``reasoning_effort`` / ``thinking_toggle`` — so it changes the
    facts hash (the cron triggers) AND the conformance gate demands the selector
    enumerate it, rather than the value being silently dropped.
    """
    known = [v for v in order if v in values]
    extras = sorted(set(values) - set(order))
    return known + extras


def _split_slash_values(raw: str) -> list[str]:
    """``"enabled/disabled"`` -> ``["enabled", "disabled"]`` (lowercased)."""
    return [v.strip().lower() for v in raw.split("/") if v.strip()]


def parse_control_table(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    """Parse the DeepSeek ``Control Parameter`` table.

    Returns ``(thinking_toggle, reasoning_effort)`` — the native vocabularies,
    parsed FROM THE TABLE CELL strings (never hardcoded). Rows are identified by
    their first-column LABEL ("toggle" / "effort"), not by index, so a row
    reorder does not mis-assign. The toggle value comes from the ``thinking.type``
    cell; the effort value from the OpenAI-format ``reasoning_effort`` cell (with
    the Anthropic ``effort`` cell as a fallback).
    """
    table = _find_table(soup, ("Control Parameter",))
    rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
    toggle_values: list[str] = []
    effort_values: list[str] = []
    for row in rows[1:]:
        cells = _row_cells(row)
        if not cells:
            continue
        label = cells[0].lower()
        joined = " ".join(cells)
        if "toggle" in label:
            m = re.search(r'"type"\s*:\s*"([^"]+)"', joined)
            if m:
                toggle_values = _split_slash_values(m.group(1))
        elif "effort" in label:
            m = re.search(r'"reasoning_effort"\s*:\s*"([^"]+)"', joined)
            if not m:
                m = re.search(r'"effort"\s*:\s*"([^"]+)"', joined)
            if m:
                effort_values = _split_slash_values(m.group(1))
    if not toggle_values:
        raise ExtractError("control table: thinking-toggle values not found")
    if not effort_values:
        raise ExtractError("control table: reasoning-effort values not found")
    return order_values(toggle_values, TOGGLE_ORDER), order_values(effort_values, EFFORT_ORDER)


def parse_footnotes(soup: BeautifulSoup) -> tuple[str | None, str | None, dict[str, str]]:
    """Parse the table footnotes for defaults + compatibility aliases.

    Best-effort and informational (the conformance gate does not depend on these):
    footnote (1) the toggle default, (2) the effort default, (3) the compatibility
    aliases (``low``/``medium`` -> ``high``, ``xhigh`` -> ``max``). Aliases are
    scoped to the "for compatibility" sentence so an unrelated "mapped to" phrase
    elsewhere on the page is not absorbed.
    """
    # Collapse whitespace so a footnote wrapped across HTML lines (mid-string
    # newlines) is parsed as one logical sentence — the span/alias regexes below
    # otherwise stop at a newline.
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    toggle_default: str | None = None
    m = re.search(r"thinking toggle defaults to\s+(\w+)", text, re.IGNORECASE)
    if m:
        toggle_default = m.group(1).lower()
    effort_default: str | None = None
    m = re.search(r"default effort is\s+(\w+)", text, re.IGNORECASE)
    if m:
        effort_default = m.group(1).lower()

    aliases: dict[str, str] = {}
    span_m = re.search(r"for compatibility,?\s*(.*?)(?:\.|When using|$)", text, re.IGNORECASE)
    span = span_m.group(1) if span_m else ""
    for am in re.finditer(
        r"([a-z]+(?:\s+and\s+[a-z]+)*)\s+(?:are|is)\s+mapped to\s+(\w+)",
        span,
        re.IGNORECASE,
    ):
        target = am.group(2).lower()
        for alias in re.split(r"\s+and\s+", am.group(1).strip(), flags=re.IGNORECASE):
            norm = alias.strip().lower()
            if norm:
                aliases[norm] = target
    return toggle_default, effort_default, aliases


def canonical_facts(
    reasoning_effort: list[str],
    thinking_toggle: list[str],
    toggle_default: str | None,
    effort_default: str | None,
    effort_aliases: dict[str, str],
) -> str:
    return json.dumps(
        {
            "reasoning_effort": reasoning_effort,
            "thinking_toggle": thinking_toggle,
            "toggle_default": toggle_default,
            "effort_default": effort_default,
            "effort_aliases": effort_aliases,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(html: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(html)
    soup = BeautifulSoup(html, "html.parser")

    thinking_toggle, reasoning_effort = parse_control_table(soup)
    toggle_default, effort_default, effort_aliases = parse_footnotes(soup)

    # FLAG (never act on) a NATIVE toggle/effort value this tracker hasn't seen.
    # A docs-added native effort tier flows into reasoning_effort (so the facts
    # hash changes and the cron triggers) AND is surfaced explicitly so the new
    # tier gets a deliberate THINKING mapping rather than being silently dropped.
    # The compatibility aliases (low/medium/xhigh) are parsed separately and do
    # NOT count as native tiers, so they never false-flag here.
    unexpected_effort = sorted(set(reasoning_effort) - set(EFFORT_ORDER))
    unexpected_toggle = sorted(set(thinking_toggle) - set(TOGGLE_ORDER))
    if unexpected_effort:
        print(
            f"extract_deepseek_thinking: NOTE unexpected DeepSeek reasoning-effort "
            f"value(s) not in the known baseline {list(EFFORT_ORDER)}: "
            f"{unexpected_effort}. A new reasoning tier needs a deliberate "
            f"THINKING-field mapping in the selector — flag for review.",
            file=sys.stderr,
        )
    if unexpected_toggle:
        print(
            f"extract_deepseek_thinking: NOTE unexpected DeepSeek thinking-toggle "
            f"value(s) not in the known baseline {list(TOGGLE_ORDER)}: "
            f"{unexpected_toggle}. Flag for review.",
            file=sys.stderr,
        )

    facts = canonical_facts(
        reasoning_effort, thinking_toggle, toggle_default, effort_default, effort_aliases
    )
    return {
        "_comment": (
            "Canonical DeepSeek thinking facts extracted from the official DeepSeek "
            "API thinking-mode docs. Generated by update/extract_deepseek_thinking.py "
            "— do not hand-edit; refresh by running that script. Consumed OFFLINE by "
            "update/validate_effort_conformance.py (DeepSeek check F)."
        ),
        "source_url": source_url,
        "reasoning_effort": reasoning_effort,
        "thinking_toggle": thinking_toggle,
        "toggle_default": toggle_default,
        "effort_default": effort_default,
        "effort_aliases": effort_aliases,
        "unexpected_effort": unexpected_effort,
        "unexpected_toggle": unexpected_toggle,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract DeepSeek thinking-toggle + reasoning-effort facts from the docs."
    )
    parser.add_argument("--url", default=DOCS_URL, help="docs HTML endpoint to fetch")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read HTML from a local file instead of fetching (for tests)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="where to write the JSON snapshot (default: committed canonical copy)",
    )
    args = parser.parse_args()

    try:
        html = args.input.read_text() if args.input else fetch_html(args.url)
    except Exception as exc:
        print(f"extract_deepseek_thinking: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(html, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_deepseek_thinking: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    effort = snapshot["reasoning_effort"]
    toggle = snapshot["thinking_toggle"]
    effort_s = ", ".join(effort) if isinstance(effort, list) else str(effort)
    toggle_s = ", ".join(toggle) if isinstance(toggle, list) else str(toggle)
    print(
        f"extract_deepseek_thinking: wrote {args.output} (toggle: {toggle_s}; effort: {effort_s})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
