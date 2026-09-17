# tests/test_roadmap_templates.py
"""Guards on the roadmap templates' step-completion contract.

0.2.32 introduced the verbatim "Step N is complete." line and, with it, a
"Follow-ups (non-blocking)" note the agent was told to place AFTER that
line. In practice that clause produced the exact "are we done or not?"
confusion it was meant to fix: every completion line arrived with a
trailer of undisposed findings. The contract now is dispose-before-
declare — every finding reaches its Triage destination first, and the
completion line is the last line of the response. These tests keep the
old allowance from creeping back into either template.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "docs" / "templates"
PHASE = TEMPLATES / "phase-roadmap-template.md"
PROJECT = TEMPLATES / "project-roadmap-template.md"

# Any sentence that tells the agent to put something AFTER the completion
# line is the regression. The prohibitions in the templates mention the
# phrase too ("no 'Follow-ups (non-blocking)'"), so match the *directive*
# shape, not the bare phrase.
_TRAILER_DIRECTIVE = re.compile(
    r"(note|report|put|place)[^.]{0,80}"
    r"(\"|“)?Follow-ups\s*\(non-blocking\)(\"|”)?[^.]{0,80}AFTER",
    re.IGNORECASE | re.DOTALL,
)


@pytest.mark.parametrize("path", [PHASE, PROJECT], ids=["phase", "project"])
def test_no_trailer_after_completion_line(path: Path) -> None:
    text = path.read_text()
    hit = _TRAILER_DIRECTIVE.search(text)
    assert hit is None, (
        f"{path.name} tells the agent to place a note AFTER the completion "
        f"line again: {hit.group(0)[:120]!r}. Findings are disposed of "
        "BEFORE the line; nothing follows it."
    )


@pytest.mark.parametrize("path", [PHASE, PROJECT], ids=["phase", "project"])
def test_dispose_before_declare_present(path: Path) -> None:
    text = path.read_text()
    required = [
        "is complete. You can now move on to",
        "LAST line of the response",
        'Done" means done',
    ]
    missing = [phrase for phrase in required if phrase not in text]
    assert not missing, f"{path.name} is missing dispose-before-declare phrases: {missing}"


def test_phase_template_lifecycle_copies_agree() -> None:
    """Stage 6 exists in three places in the phase template (STYLE RULES,
    the Overview prose lifecycle, the per-step XML <lifecycle>). All three
    must carry the no-trailer rule, or an agent reading only one copy
    reverts to the old behaviour."""
    text = PHASE.read_text()
    # The XML copy is wrapped at ~30 columns, so match across whitespace.
    flat = re.sub(r"\s+", " ", text)
    assert flat.count("LAST line of the response") >= 2
    assert "DISPOSE OF EVERY FINDING" in flat
    assert "Phase {{N}} is complete. You can now move on to Phase {{N+1}}." in flat
