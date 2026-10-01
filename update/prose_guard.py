#!/usr/bin/env python3
"""Quarantine an AI curation pass whose added text could steer the recommender.

docs/model-selector.txt is the recommender's prompt, and the AI passes write
prose into it (and into docs/model-tier-cost-scale.md) from pages outside this
repository: Cursor's pricing page, provider pages, CLI changelogs, web search.
A tampered page could plant text written for the recommender rather than the
reader. This compares each file's committed text with the pass's proposal and
checks every ADDED line for what the prose in these files never needs:

- a URL: sources are cited by name;
- markup that runs or links: script, iframe, img, svg, style, object, embed
  and anchor tags, ``javascript:`` / ``data:`` URIs, ``on…=`` handlers;
- invisible or bidirectional-control characters;
- text addressed to a model: overriding earlier instructions, a
  system / assistant / user role marker, "you must / should", or "always /
  never / only recommend · select · choose · pick · prefer".

On any hit it QUARANTINES the pass: every file goes back to its committed
text, so only the deterministic layers that run after it (provider prices,
derived letters, the rating guard, lifecycle tags) change the files this run,
and the report names each hit. A clean pass is left untouched. It runs in all
five AI workflows (the catalog refresh and the four trackers).

    python update/prose_guard.py --apply docs/model-selector.txt docs/model-tier-cost-scale.md
    python update/prose_guard.py --check docs/model-selector.txt   # exit 1 on a hit, no edit

The committed text is read with ``git show <ref>:<path>`` (``--ref``, default
HEAD). The report goes to stdout and update/.last-prose-guard.md.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "update" / ".last-prose-guard.md"

CHECKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a URL", re.compile(r"(?i)\bhttps?://|\bwww\.[a-z0-9-]+\.")),
    (
        "markup that runs or links",
        re.compile(
            r"(?i)<\s*/?\s*(?:script|iframe|img|svg|style|object|embed|a)\b"
            r"|\b(?:javascript|vbscript|data)\s*:"
            r"|\bon[a-z]+\s*=\s*[\"']"
        ),
    ),
    ("an invisible or bidirectional-control character", re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")),
    (
        "an instruction to override earlier instructions",
        re.compile(
            r"(?i)\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(?:previous|prior|above|earlier|all|any|these|those|your|the)\b[^.\n]{0,30}"
            r"\b(?:instructions?|rules?|prompts?|guidelines?|directives?|context)\b"
        ),
    ),
    (
        "a role marker",
        # A role LABEL ("System:", "Assistant:"), not a mention: Claude Code's
        # changelog describes its own `--system-prompt` flags in plain words.
        re.compile(r"(?i)(?:^|[\s\"'(\[])(?:system|assistant|user|human|developer)\s*:(?=\s)"),
    ),
    (
        "text addressed to a model",
        re.compile(
            r"(?i)\byou\s+(?:must|should|are\s+to|need\s+to|will\s+now)\b"
            r"|\b(?:always|never|only)\s+(?:recommend|select|choose|pick|prefer|rank|suggest)\b"
        ),
    ),
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int  # 1-based, in the proposed text
    reason: str
    text: str

    def render(self) -> str:
        snippet = self.text.strip()
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        return f"- `{self.path}` line {self.line}: {self.reason} — `{snippet}`"


def added_lines(base: str, proposed: str) -> list[tuple[int, str]]:
    """(1-based line number, text) of every line ``proposed`` adds or changes."""
    a, b = base.splitlines(), proposed.splitlines()
    out: list[tuple[int, str]] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            out.extend((j + 1, b[j]) for j in range(j1, j2))
    return out


def scan(path: str, base: str, proposed: str) -> list[Hit]:
    hits: list[Hit] = []
    for number, text in added_lines(base, proposed):
        for reason, pattern in CHECKS:
            if pattern.search(text):
                hits.append(Hit(path, number, reason, text))
    return hits


def render_report(hits: list[Hit], paths: list[str]) -> str:
    if not hits:
        return ""
    return (
        "\n".join(
            [
                "## Prose guard",
                "",
                f"The AI pass was quarantined: {', '.join(f'`{p}`' for p in paths)} went back to "
                "their committed text, so only the deterministic layers changed them this run. "
                "Added lines that tripped the guard (update/prose_guard.py):",
                "",
                *(h.render() for h in hits),
            ]
        )
        + "\n"
    )


def committed(ref: str, path: str, root: Path = REPO_ROOT) -> str:
    result = subprocess.run(  # noqa: S603 — fixed git binary, no shell, literal args
        ["git", "show", f"{ref}:{path}"],  # noqa: S607 — "git" resolved via the runner's PATH
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    # A file new to this pass has no committed text: every line is added.
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true", help="quarantine the pass on a hit")
    mode.add_argument("--check", action="store_true", help="exit 1 on a hit, no edit")
    parser.add_argument("paths", nargs="+", help="repo-relative files the pass wrote")
    parser.add_argument("--ref", default="HEAD", help="the committed text to compare with")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="the repository")
    args = parser.parse_args()

    bases = {p: committed(args.ref, p, args.root) for p in args.paths}
    hits: list[Hit] = []
    for p in args.paths:
        hits += scan(p, bases[p], (args.root / p).read_text(encoding="utf-8"))
    report = render_report(hits, args.paths)
    print(report or "## Prose guard\n\nEvery added line is clean.")
    if args.check:
        return 1 if hits else 0
    args.report.write_text(report, encoding="utf-8")
    if hits:
        for p in args.paths:
            (args.root / p).write_text(bases[p], encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
