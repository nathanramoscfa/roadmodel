"""Print the catalog ids of the models Cursor offers, one per line.

Cursor's Models & Pricing page (``update/sources.json`` ``pricing``, served as
raw Markdown) lists every model Cursor runs in its pricing tables.
``update-models.yml`` feeds these ids to ``merge_catalog.py --sync-method
cursor``, as it feeds Codex's, Claude Code's and OpenRouter's lists to theirs:
deterministic and additive, so a new model reaches the cursor method on the
first refresh after Cursor prices it. Before this sync nothing but the daily
curation pass wrote the cursor method, and Claude Fable 5.2 never reached it
(2026-11-16). Fable 5.1 then stayed in the catalog, because the method said
Cursor offered only the older model (update/supersede.py's coverage test).

A row's name matches a live catalog model on its words, in any order and
without the "Claude" brand word, so Cursor's "Claude 4.7 Opus" is the catalog's
Opus 4.7. A mode row ("Grok 4.7 (Fast)", "Claude Opus 4.7 (fast mode)") names
no separate model and is skipped; a context-size row ("Claude 4 Sonnet 1M")
matches nothing. A name the selector does not carry, carries only as retired,
or shares with another model is skipped. Fail-open: a fetch or parse failure
prints nothing and returns 0, so the refresh never stops here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

UPDATE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(UPDATE_DIR))

from selector_re import ATTR_RE, MODEL_RE  # noqa: E402

SOURCES_PATH = UPDATE_DIR / "sources.json"
SELECTOR_PATH = UPDATE_DIR.parent / "docs" / "model-selector.txt"
USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# A pricing-table row's model cell: "| [Claude Fable 5.2](https://...) | ...".
_ROW_NAME_RE = re.compile(r"^\|\s*\[([^\]]+)\]\(", re.MULTILINE)


def name_key(name: str) -> tuple[str, ...]:
    """A model name's words, lower-case and sorted, without the "Claude" brand
    word: "Claude 4.7 Opus" and "Opus 4.7" key the same."""
    words = re.split(r"[\s\-]+", name.lower())
    return tuple(sorted(w for w in words if w and w != "claude"))


def listed_names(markdown: str) -> list[str]:
    """Every model name Cursor's pricing tables list, in page order, without
    the mode rows."""
    names = (n.strip() for n in _ROW_NAME_RE.findall(markdown))
    return list(dict.fromkeys(n for n in names if n and "(" not in n))


def catalog_keys(selector_text: str) -> dict[tuple[str, ...], str]:
    """Each live model's name key -> its id. A key two models share maps to
    neither, so an ambiguous name never lands on the wrong model."""
    out: dict[tuple[str, ...], str] = {}
    shared: set[tuple[str, ...]] = set()
    for match in MODEL_RE.finditer(selector_text):
        attrs = dict(ATTR_RE.findall(match.group(1)))
        mid, name = attrs.get("id"), attrs.get("name")
        if not mid or not name or "retired-on" in attrs:
            continue
        key = name_key(name)
        if key in out and out[key] != mid:
            shared.add(key)
        out.setdefault(key, mid)
    for key in shared:
        del out[key]
    return out


def cursor_ids(markdown: str, selector_text: str) -> list[str]:
    """The live catalog ids Cursor's pricing tables name, in page order."""
    keys = catalog_keys(selector_text)
    ids = (keys.get(name_key(n)) for n in listed_names(markdown))
    return list(dict.fromkeys(i for i in ids if i))


def pricing_url() -> str:
    return str(json.loads(SOURCES_PATH.read_text())["pricing"]["url"])


def fetch_text(url: str) -> str:
    import requests

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the catalog ids Cursor offers.")
    parser.add_argument(
        "--input", type=Path, default=None, help="read the Markdown from a file (tests)"
    )
    parser.add_argument("--selector", type=Path, default=SELECTOR_PATH)
    args = parser.parse_args(argv)
    try:
        markdown = args.input.read_text() if args.input else fetch_text(pricing_url())
        selector_text = args.selector.read_text()
    except Exception as exc:  # noqa: BLE001 - fail-open: never stop the refresh
        print(f"extract_cursor_models: fetch/read failed ({exc!r}); skipping", file=sys.stderr)
        return 0
    ids = cursor_ids(markdown, selector_text)
    for model_id in ids:
        print(model_id)
    print(f"extract_cursor_models: {len(ids)} catalogued model(s) on Cursor", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
