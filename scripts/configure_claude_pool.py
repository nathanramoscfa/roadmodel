#!/usr/bin/env python3
"""Preview/install the Claude pool status line, preserving the original exactly.

Default is diff only. Show that diff to the operator BEFORE running --install.
Original statusLine is saved privately in the pool cache; --restore restores it.
--hook previews/installs (with --install) a SessionStart hook that refreshes
stale pool meters in the background; it adds one entry and changes nothing else.
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


def hook_configuration(settings: dict[str, Any]) -> dict[str, Any]:
    """Add the pool-freshness SessionStart hook once, keeping every other hook."""
    script = Path(__file__).with_name("ensure_pool_fresh.py").resolve()
    hooks = settings.get("hooks")
    hooks = dict(hooks) if isinstance(hooks, dict) else {}
    entries = list(hooks.get("SessionStart") or [])
    for entry in entries:
        for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if isinstance(hook, dict) and str(script) in str(hook.get("command", "")):
                return settings  # Idempotent.
    command = shlex.join([sys.executable, "-I", "-X", "utf8", str(script)])
    entries.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
    hooks["SessionStart"] = entries
    return {**settings, "hooks": hooks}


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
    ap.add_argument("--hook", action="store_true", help="work on the SessionStart hook instead")
    args = ap.parse_args()
    path = args.settings
    before = (
        private_files().read_private_output(path) if path.exists() or path.is_symlink() else None
    )
    settings = json.loads(before if before is not None else b"{}")
    original_path = args.cache / "claude-statusline-original.json"
    key = "hooks" if args.hook else "statusLine"
    if args.hook:
        if args.restore:
            ap.error("--hook has no --restore; remove its SessionStart entry by hand")
        new, original = hook_configuration(settings), None
    elif args.restore:
        original = json.loads(private_files().read_private_output(original_path))
        new = dict(settings)
        if original is None:
            new.pop("statusLine", None)
        else:
            new["statusLine"] = original
    else:
        new, original = configuration(settings, original_path)
    old_line = json.dumps({key: settings.get(key)}, indent=2) + "\n"
    new_line = json.dumps({key: new.get(key)}, indent=2) + "\n"
    print(
        "".join(
            difflib.unified_diff(
                old_line.splitlines(True),
                new_line.splitlines(True),
                fromfile=f"current {key}",
                tofile=f"proposed {key}",
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
        if args.install and not args.hook:
            private_files().private_directory(args.cache)
            atomic_json(original_path, original)
        atomic_json(path, new, before_replace=unchanged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
