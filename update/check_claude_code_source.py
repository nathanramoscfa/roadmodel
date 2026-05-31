"""Hash Claude Code's CHANGELOG and decide whether Opus needs to run.

The Claude Code refresh (a focused Opus call that updates
`<thinking-context>`, `<max-mode-context>`, and the `<method
id="claude-code">` element in ``docs/model-selector.txt``) is wasted on
days when Anthropic hasn't shipped a Claude Code release. The strongest
signal for "new surface-parameter to consider" is an edit to the
``anthropics/claude-code`` CHANGELOG. This script fetches that file,
hashes it, and compares against a cached signature from the previous
run.

Why only the CHANGELOG and not every Anthropic surface (docs site,
release notes blog, etc.): the CHANGELOG is the single source Anthropic
ships per-release and reliably enumerates every user-visible setting
change. Hashing additional sources would trip the gate on
documentation rewrites that don't actually change Claude Code surface
parameters.

Output:
- Writes the new signature to ``update/.cache/claude-code-hash.new``
  (staging — workflow promotes after Opus + validator succeed).
- Writes ``changed=true|false`` to ``$GITHUB_OUTPUT`` for the workflow
  step that gates the Opus call.
- Exits 0 in all non-error cases. Any fetch / parse error is treated as
  ``changed=true`` so Opus runs and surfaces the underlying problem
  rather than silently skipping a refresh.

A separate workflow step promotes
``update/.cache/claude-code-hash.new`` →
``update/.cache/claude-code-hash`` only if the downstream Opus +
validator + PR-open steps all succeed. That prevents a transient
failure from silently swallowing a real upstream change.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import requests

UPDATE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = UPDATE_DIR / "sources-claude-code.json"
CACHE_DIR = UPDATE_DIR / ".cache"
HASH_PATH = CACHE_DIR / "claude-code-hash"
HASH_STAGING_PATH = CACHE_DIR / "claude-code-hash.new"

USER_AGENT = (
    "roadmodel-updater/1.0 "
    "(+https://github.com/nathanramoscfa/roadmodel)"
)
FETCH_TIMEOUT = 30


def changelog_url() -> str:
    payload = json.loads(SOURCES_PATH.read_text())
    return payload["changelog"]["url"]


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
        url = changelog_url()
        new_sig = compute_signature(url)
    except Exception as exc:
        print(
            f"check_claude_code_source: error during fetch ({exc!r}); "
            "treating as changed",
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
        print(f"check_claude_code_source: changed=true ({diff_summary})")
    else:
        print("check_claude_code_source: changed=false (CHANGELOG unchanged)")
    emit_output(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
