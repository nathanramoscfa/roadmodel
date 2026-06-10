#!/usr/bin/env python3
"""Programmatic pre/post-Opus checks for the Claude Code refresh.

Per [[project-opus-pricing-diff-unreliable]], Opus is not a reliable
diff-citation engine — it can silently skip CHANGELOG entries it
considered out of scope without saying so, and it can claim it
processed a release without actually mentioning the new surface
parameter in the diff. This validator catches both failure modes with
two checks:

1. Coverage check (POST). Every version in
   ``update/.cache/pending-bullets.json`` (written by
   ``update/update_claude_code.py`` BEFORE the Opus call) MUST appear
   in Opus's `consumed_versions` array. A missing version is a hard
   FAIL — the runner gave Opus N versions and Opus must explicitly
   account for each one, even as "considered no-op".

2. Citation check (POST). For every bullet across the pending
   versions that contains a TRIGGER keyword (effort-level renames,
   slash commands, hooks, settings.json keys, extended thinking
   knobs, env vars), the validator searches the
   ``docs/model-selector.txt`` diff (`git diff` between HEAD and the
   working tree, or between two paths if --before/--after are given)
   for at least ONE non-trivial token from the bullet. A trigger
   bullet that produced no matching diff hunk is a hard FAIL — Opus
   said it considered the release but the visible surface didn't
   change to match.

The PRE check (parsing the CHANGELOG into per-version bullets) lives
in ``update_claude_code.py::parse_versions`` /
``write_pending_bullets``. This file consumes the persisted snapshot
rather than re-fetching the CHANGELOG, which keeps the validator
deterministic against the exact input Opus saw.

Trigger keywords are kept small and unambiguous on purpose — false
positives would block harmless releases. Add keywords sparingly when
a real-world miss surfaces; the keyword list is documented in
[[project-claude-code-param-tracker]] memory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
CACHE_DIR = UPDATE_DIR / ".cache"
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
PENDING_BULLETS_PATH = CACHE_DIR / "pending-bullets.json"
LAST_SUMMARY_PATH = UPDATE_DIR / ".last-claude-code-summary.txt"

# Keywords that mark a CHANGELOG bullet as a Claude Code surface-
# parameter change Opus is responsible for reflecting in the diff.
# Casefolded comparison; substrings allowed. Keep this list narrow:
# false positives block PR merge unnecessarily.
TRIGGER_KEYWORDS = (
    "/effort",
    "effort level",
    "slash command",
    "hook",
    "settings.json",
    "extended thinking",
    "auto mode",
    "ultracode",
    "ultrathink",
    "xhigh",
    "max effort",
    "adaptive reasoning",
    "claude_code_",
)

# Tokens to ignore when computing "non-trivial" overlap between a
# bullet and the diff. These are stop-words / boilerplate that would
# spuriously satisfy the citation check.
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "with",
        "by",
        "is",
        "are",
        "be",
        "now",
        "new",
        "add",
        "added",
        "adds",
        "support",
        "supports",
        "supported",
        "fix",
        "fixed",
        "fixes",
        "update",
        "updated",
        "updates",
        "improve",
        "improved",
        "improves",
        "claude",
        "code",
        "release",
        "this",
        "that",
        "when",
        "where",
        "via",
        "into",
        "from",
        "as",
        "at",
    ]
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-/.]{2,}")


def extract_consumed_versions(consumed: list[str] | None) -> set[str]:
    if not consumed:
        return set()
    return {str(v).strip() for v in consumed if str(v).strip()}


def load_pending() -> list[dict[str, object]]:
    if not PENDING_BULLETS_PATH.exists():
        raise FileNotFoundError(
            f"{PENDING_BULLETS_PATH} not found — update_claude_code.py "
            "must run before validate_claude_code_diff.py"
        )
    payload = json.loads(PENDING_BULLETS_PATH.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"{PENDING_BULLETS_PATH} is not a JSON list")
    return payload


def coverage_check(pending: list[dict[str, object]], consumed: set[str]) -> list[str]:
    """Return a list of FAIL messages; empty list means pass."""
    failures: list[str] = []
    for entry in pending:
        version = str(entry.get("version", "")).strip()
        if not version:
            continue
        if version not in consumed:
            failures.append(
                f"coverage check: version {version} appeared in "
                "pending-bullets.json but NOT in Opus's "
                "consumed_versions — Opus silently skipped this "
                "release. Add it explicitly (with a 'considered "
                "no-op' warning if it produced no edit)."
            )
    return failures


def bullet_is_trigger(bullet: str) -> bool:
    low = bullet.lower()
    return any(kw in low for kw in TRIGGER_KEYWORDS)


def non_trivial_tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS}


def load_diff(before: Path | None, after: Path | None) -> str:
    """Return the unified diff between `before` and `after`.

    If both are None, diffs HEAD against the working tree for
    `docs/model-selector.txt` using `git diff`. This is what the
    workflow uses post-Opus-write before the commit/push.
    """
    if before is None and after is None:
        try:
            result = subprocess.run(  # noqa: S603 — fixed git binary, no shell, literal args
                [  # noqa: S607 — "git" resolved via the runner's PATH; repo-relative literal args
                    "git",
                    "-C",
                    str(REPO_ROOT),
                    "diff",
                    "--",
                    str(SELECTOR_PATH.relative_to(REPO_ROOT)),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git diff failed: {exc.stderr.strip()}") from exc
        return result.stdout
    if before is None or after is None:
        raise ValueError("--before and --after must be given together")
    import difflib

    return "".join(
        difflib.unified_diff(
            before.read_text().splitlines(keepends=True),
            after.read_text().splitlines(keepends=True),
            fromfile=str(before),
            tofile=str(after),
        )
    )


def citation_check(pending: list[dict[str, object]], diff_text: str) -> list[str]:
    """For every trigger bullet, require ≥1 non-trivial token in the diff."""
    failures: list[str] = []
    diff_tokens = non_trivial_tokens(diff_text)
    for entry in pending:
        version = str(entry.get("version", "")).strip()
        bullets = entry.get("bullets") or []
        if not isinstance(bullets, list):
            continue
        for bullet in bullets:
            bullet_text = str(bullet)
            if not bullet_is_trigger(bullet_text):
                continue
            bullet_tokens = non_trivial_tokens(bullet_text)
            if not bullet_tokens:
                continue
            if not (bullet_tokens & diff_tokens):
                failures.append(
                    f"citation check: version {version} bullet "
                    f"{bullet_text!r} matched a trigger keyword "
                    f"({_first_match(bullet_text)!r}) but no non-"
                    "trivial token from the bullet appears in the "
                    "docs/model-selector.txt diff. Opus likely "
                    "missed the surface-parameter update."
                )
    return failures


def _first_match(bullet: str) -> str:
    low = bullet.lower()
    for kw in TRIGGER_KEYWORDS:
        if kw in low:
            return kw
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--consumed-versions",
        type=Path,
        default=None,
        help=(
            "Path to a JSON file containing Opus's reply (the same "
            "object structure update_claude_code.py would have parsed "
            "from the API response). If omitted, the validator reads "
            "consumed_versions from $CLAUDE_CODE_CONSUMED_VERSIONS as "
            "a JSON-encoded list."
        ),
    )
    parser.add_argument(
        "--before",
        type=Path,
        default=None,
        help=(
            "Path to the pre-Opus snapshot of docs/model-selector.txt. "
            "If both --before and --after are given, diff them directly "
            "instead of using git diff."
        ),
    )
    parser.add_argument(
        "--after",
        type=Path,
        default=None,
        help="Path to the post-Opus snapshot of docs/model-selector.txt.",
    )
    parser.add_argument(
        "--pending",
        type=Path,
        default=None,
        help=(
            "Override path to pending-bullets.json (default: update/.cache/pending-bullets.json)."
        ),
    )
    args = parser.parse_args()

    global PENDING_BULLETS_PATH
    if args.pending is not None:
        PENDING_BULLETS_PATH = args.pending

    try:
        pending = load_pending()
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"validate_claude_code_diff: {exc}\n")
        return 2

    # consumed_versions source: file > env var.
    consumed_raw: object
    if args.consumed_versions is not None:
        consumed_raw = json.loads(args.consumed_versions.read_text())
        if isinstance(consumed_raw, dict):
            consumed_raw = consumed_raw.get("consumed_versions") or []
    else:
        env_value = os.environ.get("CLAUDE_CODE_CONSUMED_VERSIONS", "")
        consumed_raw = json.loads(env_value) if env_value else []
    if not isinstance(consumed_raw, list):
        sys.stderr.write("validate_claude_code_diff: consumed_versions must be a list\n")
        return 2

    consumed = extract_consumed_versions(consumed_raw)  # type: ignore[arg-type]

    failures: list[str] = []
    failures.extend(coverage_check(pending, consumed))

    try:
        diff_text = load_diff(args.before, args.after)
    except RuntimeError as exc:
        sys.stderr.write(f"validate_claude_code_diff: {exc}\n")
        return 2
    failures.extend(citation_check(pending, diff_text))

    if failures:
        sys.stderr.write(f"validate_claude_code_diff: {len(failures)} failure(s):\n")
        for f in failures:
            sys.stderr.write(f"  - {f}\n")
        return 1

    print(
        "validate_claude_code_diff: PASS "
        f"({len(pending)} version(s), "
        f"{sum(len(e.get('bullets') or []) for e in pending)} bullet(s) "
        "inspected)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
