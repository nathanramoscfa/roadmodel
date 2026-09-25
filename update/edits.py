# update/edits.py
"""Apply the find/replace edits a refresh cron's Opus pass returns.

The crons used to ask Opus to re-emit the WHOLE target file inside a JSON
string. docs/model-selector.txt is ~180 KB, so every run paid for ~65-77k
output tokens (~$2 at Opus rates) even when one line changed — output was
~85% of the crons' API bill, and it grew with the file until it threatened the
128k ceiling. Now each pass returns only its edits; this module rebuilds the
full file so everything downstream (quote repair, validators, the PR) still
sees a whole file, unchanged.

Each edit's ``find`` must occur EXACTLY ONCE in the text as it stands when the
edit is applied (edits apply in order). A miss or an ambiguous match is fatal,
not skipped: a silently dropped edit would ship a half-applied refresh, which is
worse than the loud failure the cron-health alarm already watches for.
"""

from __future__ import annotations

from typing import Any


class EditError(ValueError):
    """An edit could not be applied unambiguously."""


def _preview(text: str, limit: int = 120) -> str:
    one_line = text.replace("\n", "\\n")
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def apply_edits(text: str, edits: Any) -> str:
    """Return ``text`` with every ``{"find", "replace"}`` edit applied in order."""
    if not isinstance(edits, list):
        raise EditError(f"'edits' must be a list, got {type(edits).__name__}")
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise EditError(f"edit #{i} is not an object")
        find = edit.get("find")
        replace = edit.get("replace")
        if not isinstance(find, str) or not find:
            raise EditError(f"edit #{i} has no non-empty 'find' string")
        if not isinstance(replace, str):
            raise EditError(f"edit #{i} has no 'replace' string")
        count = text.count(find)
        if count != 1:
            where = "not found" if count == 0 else f"matches {count} places"
            raise EditError(
                f"edit #{i} 'find' {where} — it must match exactly once: {_preview(find)!r}"
            )
        text = text.replace(find, replace, 1)
    return text


def resolve_file(result: dict[str, Any], full_key: str, current_text: str) -> str:
    """The updated file named by one pass's result.

    Prefers ``edits`` (the current output contract). Falls back to a full-file
    ``full_key`` string so a response in the old shape still works.
    """
    if "edits" in result:
        return apply_edits(current_text, result["edits"])
    full = result.get(full_key)
    if isinstance(full, str) and full.strip():
        return full
    raise EditError(f"response has neither 'edits' nor a '{full_key}' string")


def payload_size(parsed: dict[str, Any], full_key: str) -> int:
    """Rank candidate JSON objects when a response carries several.

    The real answer out-sizes a sample/template fence under either contract.
    """
    full = parsed.get(full_key)
    if isinstance(full, str) and full:
        return len(full)
    edits = parsed.get("edits")
    if isinstance(edits, list):
        return sum(
            len(str(e.get("find", ""))) + len(str(e.get("replace", ""))) + 1
            for e in edits
            if isinstance(e, dict)
        )
    return 0
