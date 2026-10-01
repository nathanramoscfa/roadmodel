"""Cron PR bodies keep their line breaks.

``$(printf '\n\n## Warnings\n')`` looks like a heading on its own line, but
command substitution strips trailing newlines: the catalog PR of 2026-10-01
(#813) read "## Warnings- discovery entry …" and "…own page## Discovery lane",
and ``$(printf '\n\n')`` added nothing at all. The workflows join sections
with ``${nl}`` (``nl=$'\n'``) instead.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
# A printf inside $( ) whose format string ends in a newline.
_STRIPPED = re.compile(r"\$\(printf '[^']*\\n'")


def test_no_workflow_ends_a_substituted_printf_with_a_newline() -> None:
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _STRIPPED.search(line)
    ]
    assert offenders == []


def test_every_block_that_joins_with_nl_defines_it_first() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        for block in re.split(r"\n\s+run: \|\n", text)[1:]:
            uses = block.find("${nl}")
            if uses == -1:
                continue
            defined = block.find("nl=$'\\n'")
            assert -1 < defined < uses, f"{path.name}: ${{nl}} used before nl=$'\\n'"
