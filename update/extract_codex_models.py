"""Flag a Codex model the reasoning tracker has not seen — FLAG ONLY.

This is the Codex analog of the Claude Code cron's ``unexpected_models`` flag.
It reads the official Codex ``models.md`` page, parses the recommended-model
``slug="..."`` attributes, and reports any slug not in the known baseline so the
refresh cron can open a deduplicated tracking issue.

This tracker NEVER edits selector model lists — new models are the Cursor
catalog cron's lane (see ``docs/catalog.json`` / ``update/update_models.py``).
This module only surfaces a flag.

Default output: the unexpected slugs, one per line on stdout (a summary line on
stderr), so the workflow can ``mapfile`` them. Fail-open: a fetch/parse failure
prints nothing on stdout and returns 0, so a transient models.md problem never
breaks the reasoning refresh.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = UPDATE_DIR / "sources-codex.json"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30

# The Codex recommended-model lineup this tracker has seen (2026-06-10). A
# recommended slug outside this set is FLAGGED. Deprecated models are ignored.
KNOWN_MODELS = frozenset({"gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"})

RECOMMENDED_HEADING = "## Recommended models"
# Anchor the heading to the start of its own line so a backtick reference to
# "`## Recommended models`" in prose (or a doc comment) is not mistaken for it.
_RECOMMENDED_RE = re.compile(r"^##\s+Recommended models\s*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^##\s+", re.MULTILINE)
_SLUG_RE = re.compile(r'slug="([^"]+)"')


class ModelsParseError(RuntimeError):
    """models.md no longer matches the structure this parser expects."""


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def recommended_section(markdown: str) -> str:
    """Return only the ``## Recommended models`` section (up to the next H2)."""
    heading = _RECOMMENDED_RE.search(markdown)
    if heading is None:
        raise ModelsParseError(f"heading not found: {RECOMMENDED_HEADING!r}")
    after = heading.end()
    m = _NEXT_H2_RE.search(markdown, after)
    end = m.start() if m else len(markdown)
    return markdown[after:end]


def recommended_slugs(markdown: str) -> list[str]:
    """Parse the recommended-model ``slug="..."`` attributes, in document order.

    Scoped to the ``## Recommended models`` section so deprecated/other models
    are excluded. De-duplicates while preserving first-seen order.
    """
    section = recommended_section(markdown)
    slugs: list[str] = []
    for slug in _SLUG_RE.findall(section):
        if slug not in slugs:
            slugs.append(slug)
    if not slugs:
        raise ModelsParseError("no recommended-model slugs parsed (restructure?)")
    return slugs


def unexpected_models(markdown: str) -> list[str]:
    return [s for s in recommended_slugs(markdown) if s not in KNOWN_MODELS]


def models_url() -> str:
    cfg = json.loads(SOURCES_PATH.read_text())["models_docs"]
    return str(cfg["url"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flag Codex recommended models not in the known baseline."
    )
    parser.add_argument(
        "--url", default=None, help="models .md endpoint (default: sources-codex.json)"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="read Markdown from a local file instead of fetching (for tests)",
    )
    args = parser.parse_args()

    try:
        markdown = args.input.read_text() if args.input else fetch_text(args.url or models_url())
    except Exception as exc:
        # Fail-open: model flagging is a courtesy; never break the refresh.
        print(f"extract_codex_models: fetch/read failed ({exc!r}); skipping flag", file=sys.stderr)
        return 0

    try:
        recommended = recommended_slugs(markdown)
        unexpected = unexpected_models(markdown)
    except ModelsParseError as exc:
        print(f"extract_codex_models: parse failed ({exc}); skipping flag", file=sys.stderr)
        return 0

    print(
        f"extract_codex_models: recommended={recommended}; unexpected={unexpected}",
        file=sys.stderr,
    )
    for slug in unexpected:
        print(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
