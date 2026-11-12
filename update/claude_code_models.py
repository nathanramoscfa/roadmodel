"""Print the catalog ids of the models Claude Code runs, one per line.

Claude Code's model-config docs list every model it runs in their effort table,
which ``update/extract_claude_code_effort.py`` snapshots daily into
``update/claude-code-effort.json`` (``per_model_effort``). ``update-models.yml``
feeds these ids to ``merge_catalog.py --sync-method claude-code``, as it feeds
the Codex docs' list to the Codex methods: deterministic and additive, so a new
Claude model reaches the claude-code method on the first refresh after the docs
name it. Fable 5.2 waited for a hand edit until this sync existed (2026-11-12).

A name the selector does not carry, or carries only as a retired model, is
skipped. Fail-open: an unreadable file prints nothing and returns 0, so the
refresh never stops here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

UPDATE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(UPDATE_DIR))

from selector_re import ATTR_RE, MODEL_RE  # noqa: E402

SNAPSHOT_PATH = UPDATE_DIR / "claude-code-effort.json"
SELECTOR_PATH = UPDATE_DIR.parent / "docs" / "model-selector.txt"


def name_key(name: str) -> str:
    """ "Opus 5.5" and "Claude Opus 5.5" key the same, as in build_catalog."""
    words = name.lower().split()
    return " ".join(words[1:] if words[:1] == ["claude"] else words)


def claude_code_ids(snapshot: dict[str, Any], selector_text: str) -> list[str]:
    """The live catalog ids the snapshot's effort table names, in table order."""
    table = snapshot.get("per_model_effort")
    if not isinstance(table, dict):
        return []
    by_name: dict[str, str] = {}
    for match in MODEL_RE.finditer(selector_text):
        attrs = dict(ATTR_RE.findall(match.group(1)))
        if attrs.get("id") and attrs.get("name") and "retired-on" not in attrs:
            by_name.setdefault(name_key(attrs["name"]), attrs["id"])
    ids = (by_name.get(name_key(str(name))) for name in table)
    return list(dict.fromkeys(i for i in ids if i))


def main() -> int:
    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        selector_text = SELECTOR_PATH.read_text()
    except (OSError, ValueError) as exc:
        print(f"claude_code_models: {exc!r}", file=sys.stderr)
        return 0
    ids = claude_code_ids(snapshot, selector_text) if isinstance(snapshot, dict) else []
    for model_id in ids:
        print(model_id)
    print(f"claude_code_models: {len(ids)} catalogued model(s) on Claude Code", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
