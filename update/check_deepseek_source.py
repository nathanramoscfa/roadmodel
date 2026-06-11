"""Decide whether the DeepSeek thinking refresh (extractor + Opus) needs to run.

DeepSeek's reasoning facts live on an HTML docs page (``api-docs.deepseek.com``
serves no clean Markdown). Robust change-detection here is deliberately
TWO-layered so a dynamic / flaky devsite can never silently corrupt the tracker
(the same design as ``update/check_gemini_source.py``):

1. **Validate the fetch.** The declarative ``must_contain_all`` anchors are the
   literal table headers / cell values that live in the SERVER-rendered HTML. If
   the page comes back as a JS shell, an interstitial, or a truncated body, those
   anchors are absent and validation raises — we do NOT try to parse a degenerate
   page.
2. **Hash the EXTRACTED FACTS, not the raw HTML.** The change signature is the
   ``section_sha256`` the extractor computes over the canonical parsed facts
   (sorted JSON of the toggle + reasoning-effort vocab + defaults + aliases).
   Cosmetic devsite churn (re-renders, analytics, reordered prose) therefore
   never triggers an expensive Opus run — only a real change to the thinking
   facts does. A structural break (the parse no longer finds the table) raises
   ``ExtractError``, which is treated as ``changed`` (fail-open) so the workflow
   runs and the extractor step then fails LOUD for a human to investigate.

Output:
- ``changed=true|false``      — the extracted thinking facts changed.
- ``docs_changed=true|false`` — same value (single source); emitted distinctly
  so the workflow wiring mirrors the Claude Code / Codex / Gemini crons.
- The new signature is staged to ``*.new``; the workflow promotes it to
  canonical only after downstream steps succeed.
- Exits 0 in all non-error cases. Any fetch/validate/parse error is treated as
  ``changed=true`` (fail-open) so the refresh runs and surfaces the problem.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, cast

import requests

# Reuse the extractor's parse so the gate and the snapshot agree on exactly which
# facts count. Sibling import (update/ is not a package) — mirror
# check_gemini_source.py's sys.path guard.
_UPDATE_DIR = Path(__file__).resolve().parent
if str(_UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_UPDATE_DIR))
# Sibling import after the path guard above: E402 (not at top) and I001
# (isort can't reorder past the guard) are both expected here.
from extract_deepseek_thinking import build_snapshot  # noqa: E402, I001

UPDATE_DIR = _UPDATE_DIR
SOURCES_PATH = UPDATE_DIR / "sources-deepseek.json"
CACHE_DIR = UPDATE_DIR / ".cache"
DOCS_HASH_PATH = CACHE_DIR / "deepseek-docs-hash"
DOCS_HASH_STAGING_PATH = CACHE_DIR / "deepseek-docs-hash.new"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30


def sources() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(SOURCES_PATH.read_text()))


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def validate_docs(text: str, cfg: dict[str, Any]) -> None:
    """Enforce the source entry's declarative ``validate`` block.

    This is the dynamic-site guard: the anchors are server-rendered table
    headers / cell values, so their absence means we did NOT receive the real
    content (JS shell / interstitial / truncation) and must not parse it.
    """
    rules = cfg.get("validate", {})
    min_bytes = int(rules.get("min_bytes", 0))
    size = len(text.encode("utf-8"))
    if size < min_bytes:
        raise ValueError(f"docs payload below min_bytes ({size} < {min_bytes})")
    for needle in rules.get("must_contain_all", []):
        if needle not in text:
            raise ValueError(
                f"docs payload missing required anchor {needle!r} — page may be a "
                "client-rendered shell, an interstitial, or restructured"
            )


def facts_signature() -> str:
    cfg = sources()["thinking_docs"]
    url = cfg["url"]
    html = fetch_html(url)
    validate_docs(html, cfg)
    # Hash the EXTRACTED FACTS (canonical), not the raw HTML. build_snapshot
    # also re-verifies the in-page anchors and raises ExtractError on a
    # restructure — caught by check_source as fail-open.
    snap = build_snapshot(html, source_url=url)
    digest = snap["section_sha256"]
    return f"{digest}  {url}#facts\n"


def emit_output(name: str, value: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    line = f"{name}={'true' if value else 'false'}\n"
    if out:
        with open(out, "a") as fh:
            fh.write(line)
    print(line, end="")


def check_source(
    compute_signature: Callable[[], str],
    canonical: Path,
    staging: Path,
    label: str,
) -> bool:
    """Stage the new signature and return whether it changed.

    Fail-open: any fetch/validate/parse error returns ``True`` (changed) WITHOUT
    staging, so the canonical hash is left intact (promote finds nothing) and the
    workflow's extractor step then fails loud on a real structural break.
    """
    try:
        new_sig = compute_signature()
    except Exception as exc:
        print(
            f"check_deepseek_source: {label} fetch/validate/parse error ({exc!r}); "
            "treating as changed",
            file=sys.stderr,
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return True

    old_sig = canonical.read_text() if canonical.exists() else ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    staging.write_text(new_sig)
    changed = new_sig != old_sig
    state = "changed" if changed else "unchanged"
    print(f"check_deepseek_source: {label} {state}")
    return changed


def main() -> int:
    changed = check_source(
        facts_signature, DOCS_HASH_PATH, DOCS_HASH_STAGING_PATH, "thinking facts"
    )
    emit_output("changed", changed)
    emit_output("docs_changed", changed)
    print(f"check_deepseek_source: changed={changed} (docs={changed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
