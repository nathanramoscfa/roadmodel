"""Hash Cursor's pricing page and decide whether Opus needs to run.

The full catalog refresh (~$5 of Opus tokens per run) is wasted on days
when no new model has landed. The strongest signal for "new model
released" is an edit to Cursor's pricing page — every model roadmodel
recommends has to appear there first. This script fetches that page,
hashes it, and compares against a cached signature from the previous
run.

Why only pricing.md and not every URL in sources.json: the benchmark
sources update on different cadences (LiveCodeBench refreshes its
rolling question set most days; AA's Insights API recomputes on a
near-hourly basis). Hashing all of them would trip the gate nearly
every day and defeat the cost-saving purpose. Slow-moving benchmark
drift gets folded in the next time pricing changes (or via a manual
`workflow_dispatch`).

Output:
- Writes the new signature to ``update/.cache/sources-hash.new``
  (staging — workflow promotes after Opus + PR succeed).
- Writes ``changed=true|false`` to ``$GITHUB_OUTPUT`` for the workflow
  step that gates the Opus call.
- Exits 0 in all non-error cases. Any fetch / parse error is treated as
  ``changed=true`` so Opus runs and surfaces the underlying problem
  rather than silently skipping a refresh.

A separate workflow step promotes ``update/.cache/sources-hash.new`` →
``update/.cache/sources-hash`` only if the downstream Opus +
build_catalog + PR-open steps all succeed. That prevents a transient
Opus failure from silently swallowing a real upstream change.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = UPDATE_DIR / "sources.json"
CACHE_DIR = UPDATE_DIR / ".cache"
HASH_PATH = CACHE_DIR / "sources-hash"
HASH_STAGING_PATH = CACHE_DIR / "sources-hash.new"

USER_AGENT = (
    "roadmodel-updater/1.0 "
    "(+https://github.com/nathanramoscfa/roadmodel)"
)
FETCH_TIMEOUT = 30


def pricing_url() -> str:
    payload = json.loads(SOURCES_PATH.read_text())
    return payload["pricing"]["url"]


def fetch_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=FETCH_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def compute_signature(url: str) -> str:
    digest = hashlib.sha256(fetch_bytes(url)).hexdigest()
    return f"{digest}  {url}\n"


def emit_output(changed: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    line = f"changed={'true' if changed else 'false'}\n"
    if out:
        with open(out, "a") as fh:
            fh.write(line)
    print(line, end="")


def main() -> int:
    try:
        url = pricing_url()
        new_sig = compute_signature(url)
    except Exception as exc:
        print(
            f"check_sources: error during fetch ({exc!r}); treating as changed",
            file=sys.stderr,
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        emit_output(True)
        return 0

    old_sig = HASH_PATH.read_text() if HASH_PATH.exists() else ""
    changed = new_sig != old_sig

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HASH_STAGING_PATH.write_text(new_sig)

    if changed:
        diff_summary = "no previous signature" if not old_sig else "signature differs"
        print(f"check_sources: changed=true ({diff_summary})")
    else:
        print("check_sources: changed=false (pricing.md unchanged)")
    emit_output(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
