# update/sync_public_roadmap.py
#!/usr/bin/env python3
"""Public ROADMAP.md deny-list linter for roadmodel.

Reads docs/templates/public-roadmap-deny-list.txt and asserts that
ROADMAP.md (the sanitized public roadmap at the repo root) contains
none of the deny-listed regex patterns. The deny-list guards against
pricing leaks, vendor-specific commitments, hardening internals, and
internal-doc references that belong only in private/ROADMAP.md.

Wired into CI by .github/workflows/tests.yml's `roadmap-sync` job;
also runnable locally for pre-commit verification:

    python update/sync_public_roadmap.py            # default lint
    python update/sync_public_roadmap.py --check    # CI alias
    python update/sync_public_roadmap.py --public ./ROADMAP.md
    python update/sync_public_roadmap.py --deny-list ./docs/templates/public-roadmap-deny-list.txt

Exit codes mirror update/build_catalog.py: 0 on success, 1 on any
deny-list hit (or missing input file).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC = REPO_ROOT / "ROADMAP.md"
DEFAULT_DENY_LIST = REPO_ROOT / "docs" / "templates" / "public-roadmap-deny-list.txt"


def _load_patterns(deny_list_path: Path) -> list[tuple[str, re.Pattern[str]]]:
    """Read the deny-list file and compile each non-comment line as regex.

    Returns a list of (raw_pattern, compiled_regex) tuples preserving
    file order so the per-pattern PASS/FAIL output matches the file's
    section grouping.
    """
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for raw_line in deny_list_path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append((stripped, re.compile(stripped)))
    return patterns


def _display_path(path: Path) -> Path | str:
    """Render a path as repo-relative when possible, absolute otherwise.

    Tests drive the linter against fixtures in pytest's tmp_path, which
    sits outside the repo root; falling back to the path's name keeps
    the FAIL line readable in that case.
    """
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path.name


def _scan(
    public_path: Path,
    patterns: list[tuple[str, re.Pattern[str]]],
) -> int:
    """Walk every line of the public file against every pattern.

    Prints a PASS line for each pattern with zero hits and a FAIL line
    (with file:line) for each hit. Returns the total hit count.
    """
    public_lines = public_path.read_text().splitlines()
    public_display = _display_path(public_path)
    total_hits = 0
    for raw_pattern, compiled in patterns:
        hits: list[tuple[int, str]] = []
        for line_num, line in enumerate(public_lines, start=1):
            if compiled.search(line):
                hits.append((line_num, line))
        if not hits:
            print(f"PASS  {raw_pattern}")
            continue
        for line_num, line in hits:
            print(f"FAIL  {raw_pattern}  {public_display}:{line_num}: {line.rstrip()}")
        total_hits += len(hits)
    return total_hits


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync_public_roadmap.py",
        description=(
            "Lint the public ROADMAP.md against the deny-list of private "
            "vocabulary (pricing, vendor specifics, hardening internals, "
            "internal-doc refs)."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Alias for the default lint behavior; used by CI for clarity.",
    )
    parser.add_argument(
        "--public",
        type=Path,
        default=DEFAULT_PUBLIC,
        help=f"Path to the public roadmap (default: {DEFAULT_PUBLIC}).",
    )
    parser.add_argument(
        "--deny-list",
        type=Path,
        default=DEFAULT_DENY_LIST,
        help=f"Path to the deny-list file (default: {DEFAULT_DENY_LIST}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _ = args.check

    public_path: Path = args.public
    deny_list_path: Path = args.deny_list

    if not public_path.is_file():
        print(f"FAIL  public roadmap not found: {public_path}", file=sys.stderr)
        return 1
    if not deny_list_path.is_file():
        print(f"FAIL  deny-list not found: {deny_list_path}", file=sys.stderr)
        return 1

    patterns = _load_patterns(deny_list_path)
    if not patterns:
        print(f"FAIL  deny-list has no patterns: {deny_list_path}", file=sys.stderr)
        return 1

    hits = _scan(public_path, patterns)
    display = _display_path(public_path)
    if hits:
        print(f"\n{hits} deny-list hit(s) in {display}")
        return 1
    print(f"\nOK  {display} clean against {len(patterns)} patterns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
