#!/usr/bin/env python3
"""Keep the bundled static ``<availability-context>`` cold-start fallback in
``docs/model-selector.txt`` in lockstep with ``infra/model-availability.json``.

Why this exists
---------------
The runtime availability layer (the daily probe -> ``model-availability.json``
-> Supabase -> web ``/api/recommend``) is authoritative for the *production*
recommender: a benched/un-benched model is reflected there with no package
release. But the OFFLINE consumers — the ``roadmodel recommend`` CLI (which runs
with ``authoritative=false``) and the exported planning kit (fully offline, no
network) — read only the bundled ``<availability-context>`` cold-start fallback.
Without this sync, an autonomous change to ``model-availability.json`` never
reaches those consumers, and the static fallback silently drifts (exactly what
happened when Fable 5 was un-benched at runtime on 2026-07-02 but stayed benched
in the bundled selector for two weeks).

This module regenerates the cold-start fallback list from the JSON source of
truth so the daily probe's auto-PR carries a correct static fallback into the
next release. An offline kit still fundamentally needs a release to pick the
change up — but the human no longer hand-edits the selector to make that happen.

Usage
-----
    python update/sync_static_availability.py            # rewrite .txt + .md
    python update/sync_static_availability.py --check    # exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_TXT = REPO_ROOT / "docs" / "model-selector.txt"
AVAILABILITY_JSON = REPO_ROOT / "infra" / "model-availability.json"

_INDENT = "    "
_WIDTH = 78

# Anchors delimiting the regenerated region inside <availability-context>. The
# region runs from the START line through the blank line before the END line;
# everything else in the element (the two static intro paragraphs and the
# substitution paragraph) is left untouched.
_START = _INDENT + "Cold-start fallback"
_END = _INDENT + "When an unavailable model would otherwise"

_INTRO = (
    "Cold-start fallback — the models listed here are treated as unavailable "
    "ONLY when no runtime override is present (enforced at Step 0a of "
    "`<selection-algorithm>`). This section is auto-generated from "
    "infra/model-availability.json by update/sync_static_availability.py — do "
    "not hand-edit."
)
_EMPTY_TAIL = (
    " It is currently EMPTY: no catalogued model is under a standing provider "
    "access restriction, so at cold-start every catalogued model is treated as "
    "available."
)

# Matches a generated bullet: "- `<id>` (Name) — reason".
_BULLET_ID_RE = re.compile(r"^\s*-\s*`([a-z0-9.\-]+)`", re.MULTILINE)
# Parses every "<model id=... name=.../>" declaration in the selector.
_MODEL_RE = re.compile(r"<model\s+([^>]+?)\s*/>", re.DOTALL)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def _fill(text: str, *, hanging: bool = False) -> str:
    return textwrap.fill(
        text,
        width=_WIDTH,
        initial_indent=_INDENT,
        subsequent_indent=_INDENT + ("  " if hanging else ""),
        break_long_words=False,
        break_on_hyphens=False,
    )


def names_from_selector(selector_text: str) -> dict[str, str]:
    """Map model id -> display name from the selector's own <model/> entries, so
    a generated bullet's name always matches what the catalog section shows."""
    out: dict[str, str] = {}
    for match in _MODEL_RE.finditer(selector_text):
        attrs: dict[str, str] = dict(_ATTR_RE.findall(match.group(1)))
        mid = attrs.get("id")
        if mid:
            out[mid] = attrs.get("name", mid)
    return out


def render_region(entries: list[dict[str, Any]], name_of: Callable[[str], str]) -> str:
    """Render the cold-start fallback region text from the unavailable entries.

    Ends with a single trailing newline; ``apply_region`` adds the blank line
    that separates it from the substitution paragraph.
    """
    if not entries:
        return _fill(_INTRO + _EMPTY_TAIL) + "\n"
    blocks = [_fill(_INTRO), ""]
    for entry in entries:
        mid = entry["id"]
        name = name_of(mid) or mid
        reason = " ".join(str(entry.get("reason", "")).split()) or "Provider access restricted."
        blocks.append(_fill(f"- `{mid}` ({name}) — {reason}", hanging=True))
    return "\n".join(blocks) + "\n"


def apply_region(selector_text: str, region: str) -> str:
    """Replace the cold-start fallback region between the two anchors."""
    if selector_text.count(_START) != 1 or selector_text.count(_END) != 1:
        raise ValueError(
            "expected exactly one Cold-start / When-an-unavailable anchor in "
            "<availability-context>; refusing to edit ambiguously"
        )
    start = selector_text.index(_START)
    end = selector_text.index(_END)
    if not 0 < start < end:
        raise ValueError("availability-context anchors out of order")
    return selector_text[:start] + region + "\n" + selector_text[end:]


def ids_in_selector(selector_text: str) -> set[str]:
    """Model ids currently benched in the static cold-start fallback region."""
    start = selector_text.index(_START)
    end = selector_text.index(_END)
    return set(_BULLET_ID_RE.findall(selector_text[start:end]))


def ids_in_json(data: dict[str, Any]) -> set[str]:
    return {e["id"] for e in data.get("unavailable", []) if isinstance(e, dict) and e.get("id")}


def _entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in data.get("unavailable", []) if isinstance(e, dict) and e.get("id")]


def rewrite_selector_text(selector_text: str, data: dict[str, Any]) -> str:
    names = names_from_selector(selector_text)
    region = render_region(_entries(data), name_of=lambda m: names.get(m, m))
    return apply_region(selector_text, region)


def sync(
    *,
    selector_path: Path = SELECTOR_TXT,
    json_path: Path = AVAILABILITY_JSON,
    render_md: bool = True,
) -> bool:
    """Rewrite the selector's static fallback from the JSON. Returns True if the
    on-disk selector changed. When ``render_md`` is set, regenerates the .md
    mirror too (byte-identical to update/render_md.py)."""
    original = selector_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    updated = rewrite_selector_text(original, data)
    changed = updated != original
    if changed:
        selector_path.write_text(updated, encoding="utf-8", newline="\n")
    if render_md:
        # Import lazily so the pure functions above have no import-time coupling.
        sys.path.insert(0, str(REPO_ROOT / "update"))
        from render_md import SELECTOR_MD, render

        SELECTOR_MD.write_text(render(selector_path.read_text()))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the static fallback disagrees with model-availability.json.",
    )
    args = parser.parse_args(argv)

    selector_text = SELECTOR_TXT.read_text(encoding="utf-8")
    data = json.loads(AVAILABILITY_JSON.read_text(encoding="utf-8"))
    sel_ids, json_ids = ids_in_selector(selector_text), ids_in_json(data)

    if args.check:
        if sel_ids != json_ids:
            sys.stderr.write(
                "Static <availability-context> fallback is out of sync with "
                "infra/model-availability.json.\n"
                f"  only in selector: {sorted(sel_ids - json_ids) or '(none)'}\n"
                f"  only in json:     {sorted(json_ids - sel_ids) or '(none)'}\n"
                "Regenerate with: python update/sync_static_availability.py\n"
            )
            return 1
        return 0

    changed = sync()
    print("Rewrote docs/model-selector.txt + .md" if changed else "Already in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
