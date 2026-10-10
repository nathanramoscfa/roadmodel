#!/usr/bin/env python3
"""Preview/install the Claude pool status line, preserving the original exactly.

Default is diff only. Show that diff to the operator BEFORE running --install.
Original statusLine is saved privately in the pool cache; --restore restores it.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

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
        command=shlex.join([sys.executable, str(script), "--original", str(original_path)]),
    )
    new["statusLine"] = status
    return new, old


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as out:
            json.dump(value, out, indent=2)
            out.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", type=Path, default=Path.home() / ".claude/settings.json")
    ap.add_argument("--cache", type=Path, default=CACHE)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    path = args.settings
    before = path.read_text() if path.exists() else "{}"
    settings = json.loads(before)
    original_path = args.cache / "claude-statusline-original.json"
    if args.restore:
        original = json.loads(original_path.read_text())
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
        if path.exists() and path.read_text() != before:
            raise RuntimeError("settings changed; preview the new diff first")
        if args.install:
            atomic_json(original_path, original)
        atomic_json(path, new, path.stat().st_mode & 0o777 if path.exists() else 0o600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
