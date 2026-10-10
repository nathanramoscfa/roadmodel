#!/usr/bin/env python3
"""Show a usage-table diff from cached snapshots; never write the context file."""

import argparse
import difflib
import time
from pathlib import Path

from pool_table import render
from pool_usage import CACHE, load

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--file", type=Path, default=Path(__file__).resolve().parent.parent / "docs/user-context.md"
    )
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--zone", default="America/New_York")
    ap.add_argument(
        "--dry-run", action="store_true", help="Always a dry run; accepted for symmetry"
    )
    args = ap.parse_args()
    old = args.file.read_text()
    new = render(old, load(args.cache), time.time(), args.zone)
    print(
        "".join(
            difflib.unified_diff(
                old.splitlines(True),
                new.splitlines(True),
                fromfile=str(args.file),
                tofile=str(args.file),
            )
        ),
        end="",
    )
