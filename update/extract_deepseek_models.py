"""Flag a DeepSeek model the reasoning tracker has not seen — FLAG ONLY.

This is the DeepSeek analog of ``update/extract_codex_models.py``. DeepSeek's
reasoning-dial page (``thinking_mode``) lists NO models (unlike the Gemini docs,
whose level matrix is itself the model source), so the model lineup is read from
the PRICING page's HTML table — specifically the ``MODEL`` header row
(``MODEL | deepseek-v4-flash | deepseek-v4-pro``). Footnote markers like ``(1)``
are stripped.

This tracker NEVER edits selector model lists and NEVER adds the per-token $
pricing — both are the Cursor catalog cron's lane (``docs/catalog.json`` /
``update/update_models.py``). This module only surfaces a flag.

Default output: the unexpected model slugs, one per line on stdout (a summary
line on stderr), so the workflow can ``mapfile`` them. Fail-open: a fetch/parse
failure prints nothing on stdout and returns 0, so a transient pricing-page
problem never breaks the reasoning refresh.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

UPDATE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = UPDATE_DIR / "sources-deepseek.json"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# The DeepSeek model lineup this tracker has seen (2026-06-11). A model in the
# pricing table's MODEL row outside this set is FLAGGED. Legacy aliases
# (deepseek-chat / deepseek-reasoner) are not listed in the MODEL row.
KNOWN_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})

_FOOTNOTE_RE = re.compile(r"\s*\(.*?\)\s*")


class ModelsParseError(RuntimeError):
    """The pricing page no longer matches the structure this parser expects."""


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def pricing_models(html: str) -> list[str]:
    """Parse the model slugs from the pricing table's ``MODEL`` header row.

    Located by the first cell reading ``MODEL`` (not by table index), so a
    layout change does not mis-select. Footnote markers (``(1)``) are stripped.
    De-duplicates while preserving first-seen order.
    """
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        for row in table.find_all("tr"):
            if not isinstance(row, Tag):
                continue
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if not cells or cells[0].strip().upper() != "MODEL":
                continue
            models: list[str] = []
            for cell in cells[1:]:
                slug = _FOOTNOTE_RE.sub("", cell).strip()
                if slug and slug not in models:
                    models.append(slug)
            if models:
                return models
    raise ModelsParseError("MODEL row not found in the pricing table (restructure?)")


def unexpected_models(html: str) -> list[str]:
    return [m for m in pricing_models(html) if m not in KNOWN_MODELS]


def models_url() -> str:
    cfg = json.loads(SOURCES_PATH.read_text())["models_docs"]
    return str(cfg["url"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flag DeepSeek pricing-page models not in the known baseline."
    )
    parser.add_argument(
        "--url", default=None, help="pricing HTML endpoint (default: sources-deepseek.json)"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read HTML from a local file instead of fetching (for tests)",
    )
    args = parser.parse_args()

    try:
        html = args.input.read_text() if args.input else fetch_html(args.url or models_url())
    except Exception as exc:
        # Fail-open: model flagging is a courtesy; never break the refresh.
        print(
            f"extract_deepseek_models: fetch/read failed ({exc!r}); skipping flag",
            file=sys.stderr,
        )
        return 0

    try:
        models = pricing_models(html)
        unexpected = unexpected_models(html)
    except ModelsParseError as exc:
        print(f"extract_deepseek_models: parse failed ({exc}); skipping flag", file=sys.stderr)
        return 0

    print(f"extract_deepseek_models: models={models}; unexpected={unexpected}", file=sys.stderr)
    for slug in unexpected:
        print(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
