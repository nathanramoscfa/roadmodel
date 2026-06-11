"""Deterministically extract Gemini's thinking facts from the official Gemini
API thinking docs.

This is the Gemini analog of ``update/extract_claude_code_effort.py`` and
``update/extract_codex_reasoning.py``. It is the *docs* half of the Gemini
surface-parameter tracker. Gemini is mid-transition between TWO reasoning
surfaces, and this extractor captures both:

1. **Gemini 3.x thinking LEVELS** — a discrete vocabulary
   (``minimal | low | medium | high``) with a per-model support matrix (e.g.
   Gemini 3.1 Pro does not support ``minimal``). Directly analogous to Codex's
   reasoning-effort enum + Claude Code's per-model effort matrix.
2. **Gemini 2.5 numeric ``thinkingBudget``** — token ranges per model plus the
   sentinels ``0`` (disable thinking, where supported) and ``-1`` (dynamic
   thinking). 2.5 Pro cannot disable thinking.

Unlike code.claude.com / developers.openai.com, ``ai.google.dev`` serves NO
clean Markdown endpoint (the ``.md`` suffix returns the same HTML wrapper), so
this extractor parses the page's HTML tables with BeautifulSoup — the same
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
import re
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

# Canonical display order for the Gemini 3.x thinking-level vocabulary.
LEVEL_ORDER = ("minimal", "low", "medium", "high")

# The Gemini 3.x level-matrix models this tracker has seen. A model column in
# the level table outside this set is FLAGGED (a new reasoning model is the
# catalog cron's lane), never acted on here. Gemini 2.5 budget-table churn
# (dated previews) is intentionally NOT flagged.
KNOWN_LEVEL_MODELS = frozenset(
    {"Gemini 3.1 Pro", "Gemini 3.1 Flash-Lite", "Gemini 3 Flash", "Gemini 3.5 Flash"}
)

# Sentinel substrings that MUST survive on the page. Their absence means the
# docs were restructured and the deterministic parse can no longer be trusted —
# fail loudly instead of emitting a partial snapshot.
REQUIRED_ANCHORS = (
    "Thinking Level",
    "Default setting",
    "Range",
    "Disable thinking",
    "thinkingBudget",
    "Dynamic thinking",
)

_RANGE_RE = re.compile(r"(\d+)\s*\D+?\s*(\d+)")


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


def parse_level_matrix(soup: BeautifulSoup) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Parse the Gemini 3.x ``Thinking Level`` per-model support matrix.

    Returns ``(per_model_levels, level_defaults)``. A model supports a level
    when its cell says "Supported" (but NOT "Not supported"); it is the default
    when the cell also says "Default".
    """
    table = _find_table(soup, ("Thinking Level",))
    rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
    headers = _row_cells(rows[0])
    # Columns: ["Thinking Level", <model>, ..., "Description"]. Keep the model
    # columns (drop the leading label and the trailing free-text Description).
    model_cols = [(i, h) for i, h in enumerate(headers) if i > 0 and h != "Description"]
    if not model_cols:
        raise ExtractError("level matrix header had no model columns")

    per_model: dict[str, list[str]] = {model: [] for _, model in model_cols}
    defaults: dict[str, str] = {}
    seen_levels: list[str] = []
    for row in rows[1:]:
        cells = _row_cells(row)
        if not cells:
            continue
        level = cells[0].strip().lower()
        if level not in LEVEL_ORDER:
            continue
        seen_levels.append(level)
        for idx, model in model_cols:
            if idx >= len(cells):
                continue
            cell = cells[idx].lower()
            supported = "supported" in cell and "not supported" not in cell
            if supported:
                per_model[model].append(level)
                if "default" in cell:
                    defaults[model] = level

    # Order each model's levels canonically and drop models with no support.
    ordered = {
        model: [lv for lv in LEVEL_ORDER if lv in lvls] for model, lvls in per_model.items() if lvls
    }
    if not ordered or not seen_levels:
        raise ExtractError("level matrix parsed no model/level support")
    return ordered, defaults


def parse_budget_table(soup: BeautifulSoup) -> dict[str, dict[str, object]]:
    """Parse the Gemini 2.5 numeric ``thinkingBudget`` table.

    Returns ``{model: {range:[lo,hi], can_disable:bool, dynamic:int|None,
    default:str}}``.
    """
    table = _find_table(soup, ("Default setting", "Range", "Disable thinking"))
    rows = [r for r in table.find_all("tr") if isinstance(r, Tag)]
    headers = _row_cells(rows[0])

    def col(needle: str) -> int:
        for i, h in enumerate(headers):
            if needle in h:
                return i
        raise ExtractError(f"budget table missing column {needle!r}")

    c_default, c_range, c_disable, c_dynamic = (
        col("Default setting"),
        col("Range"),
        col("Disable thinking"),
        col("dynamic"),
    )

    out: dict[str, dict[str, object]] = {}
    for row in rows[1:]:
        cells = _row_cells(row)
        if len(cells) <= max(c_range, c_disable, c_dynamic):
            continue
        model = cells[0].strip()
        if not model:
            continue
        m = _RANGE_RE.search(cells[c_range])
        budget_range = [int(m.group(1)), int(m.group(2))] if m else None
        disable_cell = cells[c_disable].lower()
        can_disable = "= 0" in disable_cell and "cannot" not in disable_cell
        dynamic = -1 if "-1" in cells[c_dynamic] else None
        out[model] = {
            "range": budget_range,
            "can_disable": can_disable,
            "dynamic": dynamic,
            "default": cells[c_default].strip(),
        }
    if not out:
        raise ExtractError("budget table parsed no model rows")
    return out


def build_thinking_levels(per_model_levels: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    for lvls in per_model_levels.values():
        seen.update(lvls)
    return [lv for lv in LEVEL_ORDER if lv in seen]


def canonical_facts(
    thinking_levels: list[str],
    per_model_levels: dict[str, list[str]],
    level_defaults: dict[str, str],
    per_model_budget: dict[str, dict[str, object]],
    budget_sentinels: dict[str, int],
) -> str:
    return json.dumps(
        {
            "thinking_levels": thinking_levels,
            "per_model_levels": per_model_levels,
            "level_defaults": level_defaults,
            "per_model_budget": per_model_budget,
            "budget_sentinels": budget_sentinels,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def build_snapshot(html: str, *, source_url: str) -> dict[str, object]:
    verify_anchors(html)
    soup = BeautifulSoup(html, "html.parser")

    per_model_levels, level_defaults = parse_level_matrix(soup)
    per_model_budget = parse_budget_table(soup)
    thinking_levels = build_thinking_levels(per_model_levels)

    # Derive the documented sentinels from the budget table rather than
    # hardcoding: disable = 0 (any model that can disable), dynamic = -1.
    can_disable_any = any(v.get("can_disable") for v in per_model_budget.values())
    dynamic_present = any(v.get("dynamic") == -1 for v in per_model_budget.values())
    if not dynamic_present:
        raise ExtractError("budget table no longer documents the -1 dynamic sentinel")
    budget_sentinels = {"dynamic": -1}
    if can_disable_any:
        budget_sentinels["disable"] = 0

    # FLAG (never act on) a level-matrix model this tracker hasn't seen — new
    # reasoning models are the catalog cron's lane.
    unexpected = sorted(set(per_model_levels) - KNOWN_LEVEL_MODELS)
    if unexpected:
        print(
            f"extract_gemini_thinking: NOTE unexpected Gemini 3.x level-matrix "
            f"model(s) not in the known baseline: {unexpected}. New models are the "
            f"catalog cron's lane — flag them; do NOT add them to selector model "
            f"lists here.",
            file=sys.stderr,
        )

    facts = canonical_facts(
        thinking_levels, per_model_levels, level_defaults, per_model_budget, budget_sentinels
    )
    return {
        "_comment": (
            "Canonical Gemini thinking facts extracted from the official Gemini "
            "API thinking docs. Generated by update/extract_gemini_thinking.py — "
            "do not hand-edit; refresh by running that script. Consumed OFFLINE "
            "by update/validate_effort_conformance.py (Gemini check E)."
        ),
        "source_url": source_url,
        "thinking_levels": thinking_levels,
        "per_model_levels": per_model_levels,
        "level_defaults": level_defaults,
        "per_model_budget": per_model_budget,
        "budget_sentinels": budget_sentinels,
        "unexpected_models": unexpected,
        "section_sha256": hashlib.sha256(facts.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Gemini thinking-level + budget facts from the docs."
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
    n_budget = (
        len(snapshot["per_model_budget"]) if isinstance(snapshot["per_model_budget"], dict) else 0
    )
    print(
        f"extract_gemini_thinking: wrote {args.output} "
        f"(3.x levels: {summary}; {n_level} level models, {n_budget} budget models)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
