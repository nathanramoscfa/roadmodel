"""Decide whether the Codex reasoning-effort refresh (extractor + Opus) runs.

Codex — unlike Claude Code — has no usable changelog (the openai/codex repo's
docs stub and CHANGELOG point elsewhere, and no `.../codex/changelog.md`
exists). So the single change trigger is the official Codex config-reference
docs: only the **in-scope reasoning-key span** is hashed (via
``extract_codex_reasoning.isolate_in_scope``), so an unrelated config edit
(providers, hooks, telemetry, model catalogs) does NOT trip the gate.

Output:
- ``changed=true|false``      — the in-scope reasoning span changed.
- ``docs_changed=true|false`` — same value; emitted as a distinct output so the
  workflow wiring mirrors the Claude Code cron's ``--docs-changed`` path.
- The new signature is written to a ``*.new`` staging file; the workflow
  promotes it to canonical only after the downstream steps all succeed, so a
  transient failure never swallows a real upstream change.
- Exits 0 in all non-error cases. A fetch/parse error is treated as
  ``changed=true`` (fail-open) so the refresh runs and surfaces the problem.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, cast

import requests

# The in-scope-span isolation lives in the extractor; reuse it so the gate and
# the snapshot agree on exactly which span counts. Sibling import (update/ is
# not a package) — mirror check_claude_code_source.py's sys.path guard.
_UPDATE_DIR = Path(__file__).resolve().parent
if str(_UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_UPDATE_DIR))
# Sibling import after the path guard above: E402 (not at top) and I001
# (isort can't reorder past the guard) are both expected here.
from extract_codex_reasoning import isolate_in_scope  # noqa: E402, I001

UPDATE_DIR = _UPDATE_DIR
SOURCES_PATH = UPDATE_DIR / "sources-codex.json"
CACHE_DIR = UPDATE_DIR / ".cache"
DOCS_HASH_PATH = CACHE_DIR / "codex-docs-hash"
DOCS_HASH_STAGING_PATH = CACHE_DIR / "codex-docs-hash.new"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30


def sources() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(SOURCES_PATH.read_text()))


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def validate_docs(text: str, cfg: dict[str, Any]) -> None:
    """Enforce the source entry's declarative ``validate`` block."""
    rules = cfg.get("validate", {})
    min_bytes = int(rules.get("min_bytes", 0))
    size = len(text.encode("utf-8"))
    if size < min_bytes:
        raise ValueError(f"docs payload below min_bytes ({size} < {min_bytes})")
    for needle in rules.get("must_contain_all", []):
        if needle not in text:
            raise ValueError(f"docs payload missing required substring: {needle!r}")


def docs_signature() -> str:
    cfg = sources()["reasoning_docs"]
    url = cfg["url"]
    text = fetch_text(url)
    validate_docs(text, cfg)
    # Hash ONLY the in-scope reasoning-key span, not the whole page.
    span = isolate_in_scope(text)
    digest = hashlib.sha256(span.encode("utf-8")).hexdigest()
    return f"{digest}  {url}#reasoning\n"


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

    Fail-open: any fetch/parse error returns ``True`` (changed) WITHOUT staging,
    so the canonical hash is left intact (promote finds nothing to promote) and
    tomorrow's run retries the same comparison.
    """
    try:
        new_sig = compute_signature()
    except Exception as exc:
        print(
            f"check_codex_source: {label} fetch/parse error ({exc!r}); treating as changed",
            file=sys.stderr,
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return True

    old_sig = canonical.read_text() if canonical.exists() else ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    staging.write_text(new_sig)
    changed = new_sig != old_sig
    state = "changed" if changed else "unchanged"
    print(f"check_codex_source: {label} {state}")
    return changed


def main() -> int:
    changed = check_source(
        docs_signature, DOCS_HASH_PATH, DOCS_HASH_STAGING_PATH, "config-reference docs"
    )
    # Codex has a single source; docs_changed mirrors changed so the workflow
    # wiring matches the Claude Code cron (which distinguishes CHANGELOG vs docs).
    emit_output("changed", changed)
    emit_output("docs_changed", changed)
    print(f"check_codex_source: changed={changed} (docs={changed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
