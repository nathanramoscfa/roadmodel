"""Decide whether the Claude Code refresh (Opus + docs extractor) needs to run.

Two upstream sources gate the (expensive) refresh:

1. The ``anthropics/claude-code`` CHANGELOG — the canonical signal for a new
   Claude Code surface parameter. Hashed whole (raw bytes).
2. The official ``model-config`` docs — authoritative for Effort levels, the
   ultracode/ultrathink distinction, and extended thinking. Only the
   **in-scope effort/thinking span** is hashed (via
   ``extract_claude_code_effort.isolate_in_scope``), so an unrelated docs edit
   (model aliases, env vars, 1M context, caching) does NOT trip the gate.

Output:
- ``changed=true|false``     — CHANGELOG OR in-scope docs span changed.
- ``docs_changed=true|false`` — the in-scope docs span changed (drives the
  docs-reconciliation path in ``update_claude_code.py``).
- New signatures are written to ``*.new`` staging files; the workflow promotes
  them to canonical only after the downstream steps all succeed, so a transient
  failure never swallows a real upstream change.
- Exits 0 in all non-error cases. Any per-source fetch/parse error is treated
  as ``changed=true`` (fail-open) so the refresh runs and surfaces the problem.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Callable

import requests

# The in-scope-span isolation lives in the extractor; reuse it so the gate and
# the snapshot agree on exactly which span counts. Sibling import (update/ is
# not a package) — mirror build_fixture.py's sys.path guard.
_UPDATE_DIR = Path(__file__).resolve().parent
if str(_UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_UPDATE_DIR))
# Sibling import after the path guard above: E402 (not at top) and I001
# (isort can't reorder past the guard) are both expected here.
from extract_claude_code_effort import isolate_in_scope  # noqa: E402, I001

UPDATE_DIR = _UPDATE_DIR
SOURCES_PATH = UPDATE_DIR / "sources-claude-code.json"
CACHE_DIR = UPDATE_DIR / ".cache"
HASH_PATH = CACHE_DIR / "claude-code-hash"
HASH_STAGING_PATH = CACHE_DIR / "claude-code-hash.new"
DOCS_HASH_PATH = CACHE_DIR / "claude-code-docs-hash"
DOCS_HASH_STAGING_PATH = CACHE_DIR / "claude-code-docs-hash.new"

USER_AGENT = "roadmodel-updater/1.0 (+https://github.com/nathanramoscfa/roadmodel)"
FETCH_TIMEOUT = 30


def sources() -> dict[str, dict]:
    return json.loads(SOURCES_PATH.read_text())


def fetch_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown, */*"},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def validate_docs(text: str, cfg: dict) -> None:
    """Enforce the source entry's declarative ``validate`` block."""
    rules = cfg.get("validate", {})
    min_bytes = int(rules.get("min_bytes", 0))
    size = len(text.encode("utf-8"))
    if size < min_bytes:
        raise ValueError(f"docs payload below min_bytes ({size} < {min_bytes})")
    for needle in rules.get("must_contain_all", []):
        if needle not in text:
            raise ValueError(f"docs payload missing required substring: {needle!r}")


def changelog_signature() -> str:
    url = sources()["changelog"]["url"]
    digest = hashlib.sha256(fetch_bytes(url)).hexdigest()
    return f"{digest}  {url}\n"


def docs_signature() -> str:
    cfg = sources()["model_config_docs"]
    url = cfg["url"]
    text = fetch_text(url)
    validate_docs(text, cfg)
    # Hash ONLY the in-scope effort/thinking span, not the whole page.
    span = isolate_in_scope(text)
    digest = hashlib.sha256(span.encode("utf-8")).hexdigest()
    return f"{digest}  {url}#effort-thinking\n"


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
            f"check_claude_code_source: {label} fetch/parse error ({exc!r}); treating as changed",
            file=sys.stderr,
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return True

    old_sig = canonical.read_text() if canonical.exists() else ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    staging.write_text(new_sig)
    changed = new_sig != old_sig
    state = "changed" if changed else "unchanged"
    print(f"check_claude_code_source: {label} {state}")
    return changed


def main() -> int:
    changelog_changed = check_source(changelog_signature, HASH_PATH, HASH_STAGING_PATH, "CHANGELOG")
    docs_changed = check_source(
        docs_signature, DOCS_HASH_PATH, DOCS_HASH_STAGING_PATH, "model-config docs"
    )
    changed = changelog_changed or docs_changed

    emit_output("changed", changed)
    emit_output("docs_changed", docs_changed)
    print(
        f"check_claude_code_source: changed={changed} "
        f"(changelog={changelog_changed}, docs={docs_changed})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
