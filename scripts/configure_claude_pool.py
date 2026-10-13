#!/usr/bin/env python3
"""Preview/install the Claude pool status line, preserving the original exactly.

Default is diff only. Show that diff to the operator BEFORE running --install.
Original statusLine is saved privately in the pool cache; --restore restores it.
"""

from __future__ import annotations

import argparse
import difflib
import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_private import private_files
from pool_usage import CACHE


def configuration(settings: dict[str, Any], original_path: Path) -> tuple[dict[str, Any], Any]:
    script = Path(__file__).with_name("collect_claude_pool.py").resolve()
    old = settings.get("statusLine")
    if isinstance(old, dict) and str(script) in str(old.get("command", "")):
        return settings, None  # Idempotent: never wrap our own wrapper.
    new = dict(settings)
    status = dict(old) if isinstance(old, dict) else {}
    status.update(
        type="command",
        command=shlex.join(
            [sys.executable, "-I", "-X", "utf8", str(script), "--original", str(original_path)]
        ),
    )
    new["statusLine"] = status
    return new, old


def atomic_json(path: Path, value: Any, before_replace: Callable[[], None] | None = None) -> None:
    private_files().atomic_private_write(
        path, (json.dumps(value, indent=2) + "\n").encode(), before_replace=before_replace
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", type=Path, default=Path.home() / ".claude/settings.json")
    ap.add_argument("--cache", type=Path, default=CACHE)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    path = args.settings
    before = (
        private_files().read_private_output(path) if path.exists() or path.is_symlink() else None
    )
    settings = json.loads(before if before is not None else b"{}")
    original_path = args.cache / "claude-statusline-original.json"
    if args.restore:
        original = json.loads(private_files().read_private_output(original_path))
        new = dict(settings)
        if original is None:
            new.pop("statusLine", None)
        else:
            new["statusLine"] = original
    else:
        new, original = configuration(settings, original_path)
    old_line = json.dumps({"statusLine": settings.get("statusLine")}, indent=2) + "\n"
    new_line = json.dumps({"statusLine": new.get("statusLine")}, indent=2) + "\n"
    print(
        "".join(
            difflib.unified_diff(
                old_line.splitlines(True),
                new_line.splitlines(True),
                fromfile="current statusLine",
                tofile="proposed statusLine",
            )
        ),
        end="",
    )
    if new != settings and (args.install or args.restore):

        def unchanged() -> None:
            try:
                current = private_files().read_private_output(path)
            except FileNotFoundError:
                current = None
            if current != before:
                raise RuntimeError("settings changed; preview the new diff first")

        unchanged()
        if args.install:
            private_files().private_directory(args.cache)
            atomic_json(original_path, original)
        atomic_json(path, new, before_replace=unchanged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
