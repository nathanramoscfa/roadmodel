"""Deterministically extract Gemini's thinking facts from the official Gemini
API thinking docs.

This is the Gemini analog of ``update/extract_claude_code_effort.py`` and
``update/extract_codex_reasoning.py``. It is the *docs* half of the Gemini
surface-parameter tracker.

As of 2026-06 Google UNIFIED the Gemini reasoning surface onto a single
discrete thinking-LEVEL vocabulary (``low | medium | high``) spanning BOTH the
3.x and the 2.5 model generations. The page now carries one table:

    | Model | Default Thinking | Levels Supported |

one row per model (e.g. ``gemini-2.5-flash-lite`` → default ``Off``, supports
``low, medium, high``). The previous numeric 2.5 ``thinkingBudget`` table was
retired upstream — 2.5 now uses the same discrete levels — so this extractor no
longer parses (or emits) numeric budgets or the ``0`` / ``-1`` sentinels.

Unlike code.claude.com / developers.openai.com, ``ai.google.dev`` serves NO
clean Markdown endpoint (the ``.md`` suffix returns the same HTML wrapper), so
this extractor parses the page's HTML table with BeautifulSoup — the same
approach the Cursor catalog cron (``update/update_models.py``) already uses.
Because HTML is noisy, the change-detection hash (``section_sha256``) is taken
over the *canonical extracted facts* (sorted JSON), NOT the raw HTML span, so an
unrelated devsite re-render does not trip the docs-freshness cron.

The result is written as a JSON snapshot. The committed copy
(``update/gemini-thinking.json``) is the OFFLINE source of truth for
``update/validate_effort_conformance.py``'s Gemini check (check E).

Exit codes: 0 ok, 3 fetch/read failure, 4 extraction failure (the docs were
restructured so the deterministic parse no longer finds what it expects —
intentionally loud so the cron surfaces it rather than shipping a silently
wrong snapshot).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

UPDATE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = UPDATE_DIR / "gemini-thinking.json"
CACHE_SNAPSHOT_PATH = UPDATE_DIR / ".cache" / "gemini-thinking.json"

DOCS_URL = "https://ai.google.dev/gemini-api/docs/thinking"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# Canonical display order for the Gemini thinking-level vocabulary. ``minimal``
# is retained in the ordering only so that if Google ever re-introduces it the
# level sorts correctly; the current docs enumerate low/medium/high.
LEVEL_ORDER = ("minimal", "low", "medium", "high")

# Display names for the Gemini models the docs' level table enumerates, keyed by
# the model id shown in the page's "Model" column. The selector + conformance
# gate (check E) reference models by display name, so the snapshot is keyed that
# way. An id outside this map is still captured (best-effort display) and FLAGGED
# as unexpected — new reasoning models are the catalog cron's lane, not this one.
MODEL_ID_TO_DISPLAY = {
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-preview": "Gemini 3 Pro",
    "gemini-3.5-flash": "Gemini 3.5 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash-Lite",
}

KNOWN_LEVEL_MODELS = frozenset(MODEL_ID_TO_DISPLAY.values())

# Sentinel substrings that MUST survive on the page. Their absence means the
# docs were restructured and the deterministic parse can no longer be trusted —
# fail loudly instead of emitting a partial snapshot. These are the literal
# column headers of the unified level table (server-rendered, present in the
# initial HTML response — no JS engine needed).
REQUIRED_ANCHORS = (
    "Model",
    "Default Thinking",
    "Levels Supported",
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
    """Return the first table whose header row contains every needle."""
    for table in _tables(soup):
        rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
        if not rows:
            continue
        header = " ".join(_row_cells(rows[0]))
        if all(n in header for n in header_needles):
            return table
    raise ExtractError(f"no table found whose header contains all of {header_needles}")


def order_levels(levels: list[str]) -> list[str]:
    """Known levels first (canonical order), then any extras sorted.

    Keeping docs-added levels (not just the known baseline) means a new
    top-of-scale tier flows into ``thinking_levels`` / ``per_model_levels`` —
    so it changes the facts hash (the cron triggers) AND the conformance gate
    demands the selector enumerate it, rather than the level being silently
    dropped.
    """
    known = [lv for lv in LEVEL_ORDER if lv in levels]
    extras = sorted(set(levels) - set(LEVEL_ORDER))
    return known + extras


def _display_name(model_id: str) -> str:
    """Map a docs ``Model`` id to its selector display name.

    Known ids use the curated map (exact match to the selector + conformance
    gate). An unknown id falls back to a deterministic title-cased transform so
    the row is still captured — it will be surfaced via ``unexpected_models``.
    """
    if model_id in MODEL_ID_TO_DISPLAY:
        return MODEL_ID_TO_DISPLAY[model_id]
    words: list[str] = []
    for part in model_id.removesuffix("-preview").split("-"):
        if part == "gemini":
            words.append("Gemini")
        elif part == "lite" and words:
            words[-1] = f"{words[-1]}-Lite"
        elif part[:1].isdigit():
            words.append(part)
        elif part:
            words.append(part.capitalize())
    return " ".join(words)


def parse_level_table(
    soup: BeautifulSoup,
) -> tuple[dict[str, list[str]], dict[str, str], list[str]]:
    """Parse the unified ``Model | Default Thinking | Levels Supported`` table.

    Returns ``(per_model_levels, level_defaults, all_levels)``:

    - ``per_model_levels[display]`` — the comma-separated ``Levels Supported``
      cell, lowercased and canonically ordered.
    - ``level_defaults[display]`` — the level inside the ``Default Thinking``
      cell (``On (high)`` → ``high``), else the bare state (``on`` / ``off``).
    - ``all_levels`` — the union of every level seen, canonically ordered.

    Levels are taken verbatim from the cell (not an allow-list), so a docs-added
    tier flows through to ``thinking_levels`` and trips the conformance gate
    rather than being silently dropped.
    """
    table = _find_table(soup, ("Model", "Default Thinking", "Levels Supported"))
    rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
    headers = _row_cells(rows[0])

    def col(needle: str) -> int:
        for i, h in enumerate(headers):
            if needle in h:
                return i
        raise ExtractError(f"level table missing column {needle!r}")

    c_model, c_default, c_levels = (
        col("Model"),
        col("Default Thinking"),
        col("Levels Supported"),
    )

    per_model: dict[str, list[str]] = {}
    defaults: dict[str, str] = {}
    seen_levels: list[str] = []
    for row in rows[1:]:
        cells = _row_cells(row)
        if len(cells) <= max(c_model, c_default, c_levels):
            continue
        model_id = cells[c_model].strip()
        if not model_id:
            continue
        levels = [tok.strip().lower() for tok in cells[c_levels].split(",") if tok.strip()]
        if not levels:
            continue
        display = _display_name(model_id)
        for lv in levels:
            if lv not in seen_levels:
                seen_levels.append(lv)
        per_model[display] = order_levels(levels)
        default_cell = cells[c_default].strip()
        if "(" in default_cell and ")" in default_cell:
            inner = default_cell[default_cell.index("(") + 1 : default_cell.index(")")]
            defaults[display] = inner.strip().lower()
        else:
            defaults[display] = default_cell.lower()

    if not per_model or not seen_levels:
        raise ExtractError("level table parsed no model/level rows")
    return per_model, defaults, order_levels(seen_levels)


def canonical_facts(
    thinking_levels: list[str],
    per_model_levels: dict[str, list[str]],
    level_defaults: dict[str, str],
) -> str:
    return json.dumps(
        {
            "thinking_levels": thinking_levels,
            "per_model_levels": per_model_levels,
            "level_defaults": level_defaults,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(html: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(html)
    soup = BeautifulSoup(html, "html.parser")

    per_model_levels, level_defaults, thinking_levels = parse_level_table(soup)

    # FLAG (never act on) a level-table model this tracker hasn't seen — new
    # reasoning models are the catalog cron's lane.
    unexpected = sorted(set(per_model_levels) - KNOWN_LEVEL_MODELS)
    if unexpected:
        print(
            f"extract_gemini_thinking: NOTE unexpected Gemini level-table "
            f"model(s) not in the known baseline: {unexpected}. New models are the "
            f"catalog cron's lane — flag them; do NOT add them to selector model "
            f"lists here.",
            file=sys.stderr,
        )

    # FLAG a thinking LEVEL the docs introduced beyond the known baseline. This
    # is the high-value guard: a new top-of-scale tier now flows into
    # thinking_levels (so the facts hash changes and the cron triggers) AND is
    # surfaced explicitly so the new tier gets a deliberate THINKING mapping
    # rather than being silently dropped.
    unexpected_levels = [lv for lv in thinking_levels if lv not in LEVEL_ORDER]
    if unexpected_levels:
        print(
            f"extract_gemini_thinking: NOTE unexpected Gemini thinking level(s) "
            f"not in the known baseline {list(LEVEL_ORDER)}: {unexpected_levels}. A "
            f"new reasoning tier needs a deliberate THINKING-field mapping in the "
            f"selector — flag for review.",
            file=sys.stderr,
        )

    facts = canonical_facts(thinking_levels, per_model_levels, level_defaults)
    return {
        "_comment": (
            "Canonical Gemini thinking facts extracted from the official Gemini "
            "API thinking docs. Generated by update/extract_gemini_thinking.py — "
            "do not hand-edit; refresh by running that script. Consumed OFFLINE "
            "by update/validate_effort_conformance.py (Gemini check E). Gemini "
            "unified its reasoning surface onto discrete levels (2026-06); the "
            "numeric 2.5 thinkingBudget is no longer documented or tracked."
        ),
        "source_url": source_url,
        "thinking_levels": thinking_levels,
        "per_model_levels": per_model_levels,
        "level_defaults": level_defaults,
        "unexpected_models": unexpected,
        "unexpected_levels": unexpected_levels,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Gemini thinking-level facts from the docs."
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
        print(f"extract_gemini_thinking: fetch/read failed: {exc!r}", file=sys.stderr)
        return 3

    try:
        snapshot = build_snapshot(html, source_url=args.url)
    except ExtractError as exc:
        print(f"extract_gemini_thinking: extraction failed: {exc}", file=sys.stderr)
        return 4

    payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    if args.output.resolve() != CACHE_SNAPSHOT_PATH.resolve():
        CACHE_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_SNAPSHOT_PATH.write_text(payload)

    levels = snapshot["thinking_levels"]
    summary = ", ".join(levels) if isinstance(levels, list) else str(levels)
    n_level = (
        len(snapshot["per_model_levels"]) if isinstance(snapshot["per_model_levels"], dict) else 0
    )
    print(
        f"extract_gemini_thinking: wrote {args.output} ({n_level} level models; levels: {summary})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
