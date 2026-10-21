#!/usr/bin/env python3
"""Queue what the Claude Code refresh cannot settle itself, for a human.

The Claude Code tracker runs inside the typed refresh boundary
(``update/automation_integrity.py``): it may move prices and rating letters
and nothing else in the selector. Some of what it detects needs more than
that — a docs fact that went away, a selector attribute the docs now
contradict, a CHANGELOG bullet that changes a dial the selector describes.

Failing the run over such a finding deadlocks the cron, because tomorrow's run
meets the same finding and the same boundary (#1149). Calling it a no-op hides
it: Claude Code 2.1.300 stopped offering the Thinking toggle on five models,
the run called that a "considered no-op", and the snapshot's
``cannot_disable_on`` sat empty for six weeks. So every such finding lands in
one queue file, and the workflow files one exact-title deduplicated issue per
item (``.github/workflows/update-claude-code.yml``, "Route review items").

Writers: ``extract_claude_code_effort.py --review-queue`` (a docs fact the
snapshot lost), ``validate_effort_conformance.py --review-queue`` (selector
``always-thinks`` vs the docs), ``validate_claude_code_diff.py --review-queue``
(a trigger bullet the selector diff does not cite) and ``update_claude_code.py``
(the bullets the Opus pass reports in ``needs_review``).

    python update/review_queue.py --emit DIR   # NNN.title + NNN.body per item
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

QUEUE_PATH = Path(__file__).resolve().parent / ".cache" / "claude-code-review.json"
TITLE_LIMIT = 200  # GitHub allows 256; leave room for nothing surprising
FOOTER = (
    "Opened automatically by the Claude Code refresh cron "
    "(`.github/workflows/update-claude-code.yml`). The cron cannot make this "
    "change itself: its typed refresh boundary (`update/automation_integrity.py`) "
    "admits prices and rating letters only, so a reviewed PR has to."
)


def one_line(text: str, limit: int = TITLE_LIMIT) -> str:
    """``text`` on a single line, cut to ``limit`` characters."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def bullet_title(version: str, bullet: str) -> str:
    """The issue title for a CHANGELOG bullet that needs review.

    Shared by the diff validator and the Opus pass's ``needs_review`` so the
    same bullet reported by both becomes one issue, not two.
    """
    return one_line(f"chore(claude-code): review Claude Code {version}: {one_line(bullet, 110)}")


def load(path: Path = QUEUE_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a JSON list")
    return [
        {"title": str(item["title"]), "body": str(item["body"])}
        for item in data
        if isinstance(item, dict) and "title" in item and "body" in item
    ]


def add(items: Iterable[tuple[str, str]], path: Path = QUEUE_PATH) -> int:
    """Append ``(title, body)`` items; return how many new titles were added.

    A title already queued keeps one entry, with the new body appended when it
    says something the first did not.
    """
    queue = load(path)
    by_title = {item["title"]: item for item in queue}
    added = 0
    for raw_title, body in items:
        title = one_line(raw_title)
        body = body.strip()
        if title in by_title:
            existing = by_title[title]
            if body and body not in existing["body"]:
                existing["body"] = existing["body"].rstrip() + "\n\n" + body
            continue
        entry = {"title": title, "body": body}
        queue.append(entry)
        by_title[title] = entry
        added += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added


def emit(out_dir: Path, path: Path = QUEUE_PATH) -> int:
    """Write each queued item as ``NNN.title`` / ``NNN.body`` under ``out_dir``.

    Files rather than shell arguments: bodies quote CHANGELOG and docs text,
    which the workflow must pass to ``gh`` as data, never as shell words.
    """
    queue = load(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(queue, start=1):
        (out_dir / f"{index:03d}.title").write_text(item["title"] + "\n", encoding="utf-8")
        (out_dir / f"{index:03d}.body").write_text(
            item["body"].rstrip() + "\n\n---\n\n" + FOOTER + "\n", encoding="utf-8"
        )
    return len(queue)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH, help="the queue file")
    parser.add_argument("--emit", type=Path, required=True, help="directory for title/body files")
    args = parser.parse_args()
    try:
        count = emit(args.emit, args.queue)
    except (OSError, ValueError, KeyError) as exc:
        print(f"review_queue: cannot read {args.queue}: {exc}", file=sys.stderr)
        return 2
    print(f"review_queue: {count} item(s) for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
