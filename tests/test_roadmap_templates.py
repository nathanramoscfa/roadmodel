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


# ---------------------------------------------------------------------------
# Status rule (0.2.37): the roadmap on main is the ledger. Each step / phase
# carries a `**Status:**` line that the step's OWN PR flips at Stage 3, so a
# step reads Complete on main exactly when its PR merged. These guards keep
# the three lifecycle copies (and the paste-prompts' currency check) agreeing
# on that — a template that drops the Stage-3 mark silently reverts every
# project to "ask the AI to mark things complete" reconciliation passes.
# ---------------------------------------------------------------------------

PROMPT_PHASE = TEMPLATES / "prompt-phase-roadmap.md"
PROMPT_PROJECT = TEMPLATES / "prompt-project-roadmap.md"
STEP_COMMAND = ROOT / "docs" / "claude-commands" / "roadmap-step.md"


def test_phase_template_status_rule_in_all_lifecycle_copies() -> None:
    text = PHASE.read_text()
    flat = re.sub(r"\s+", " ", text)
    # STYLE RULES + Overview rule paragraph.
    assert "Status rule" in text
    assert "**Status rule.**" in text
    # Overview prose lifecycle, Stage 3.
    assert "**Open the PR, then mark the step.**" in text
    # Per-step XML <lifecycle>, Stage 3 (wrapped at ~30 columns).
    assert "OPEN THE PR, THEN MARK THE STEP" in flat
    # Stage 6 presupposes the mark, in both the prose and the XML copy.
    assert flat.count("carries this step's `Complete` Status line") >= 2
    # Every step skeleton (Step 1 and the final QA step) starts Not started.
    assert text.count("**Status:** Not started") >= 2
    # The final QA step marks the phase in the parent roadmap.
    assert "Mark the phase complete in the parent project roadmap" in flat


def test_project_template_status_ledger() -> None:
    text = PROJECT.read_text()
    flat = re.sub(r"\s+", " ", text)
    assert "**Open the PR, then mark the step.**" in text
    assert "carries the step's `Complete` Status line" in flat
    # Phase 1, Phase 2, and Phase N skeletons.
    assert text.count("**Status:** Not started") >= 3
    # §8 summary table carries the Status column.
    assert "| Complexity   | Status      |" in text


@pytest.mark.parametrize(
    ("path", "phrase"),
    [
        (PROMPT_PHASE, "OPEN THE PR, THEN MARK THE STEP"),
        (PROMPT_PROJECT, "Open the PR, then mark the step"),
    ],
    ids=["phase-prompt", "project-prompt"],
)
def test_prompt_currency_check_covers_stage_3(path: Path, phrase: str) -> None:
    """Step 0 of each paste-prompt stops on a stale kit. It must check the
    Stage-3 wording too, or a pre-0.2.37 kit (no Status lines) passes the
    Stage-6 check and bakes the old lifecycle into every step."""
    assert phrase in path.read_text()


def test_roadmap_step_command_gates_on_status() -> None:
    text = STEP_COMMAND.read_text()
    flat = re.sub(r"\s+", " ", text)
    assert "## 2. Status gate" in text
    # Idempotency + sequencing.
    assert "already reads `Complete`" in text
    assert "does not read `Complete`" in text
    # Legacy backfill is deterministic: merged PR by head branch.
    assert "gh pr list --state merged" in text
    assert "--head" in text
    # Never invent completion from git history.
    assert "Never mark a step complete on your own judgement" in flat
    # The Stage-3 mark itself.
    assert "docs: mark Phase {{PHASE}} Step {{STEP}} complete" in text


def test_roadmap_step_reads_a_settings_table_as_intent() -> None:
    """A Settings table freezes the model and effort on the day the roadmap
    was written. On 2026-09-22 a jackson-opt step stalled because its table
    said `Claude Opus 5 · Max` while the session ran Opus 5.5 — the model its
    provider had just made the default, and a Max written under the old
    uncapped posture. The gate must not block on either, and must not lose
    the record of what actually ran."""
    text = STEP_COMMAND.read_text()
    flat = re.sub(r"\s+", " ", text)
    # A newer version in the same line satisfies the gate …
    assert "newer version in the same line" in flat
    assert "Opus 5 → Opus 5.5" in flat
    # … but a different line still stops: never start on an unintended model.
    assert "a different line" in flat
    assert "Do not start the step on a model it did not intend" in flat
    # A pre-capped top rung is stale, not binding.
    assert "Consumption headroom: capped" in flat
    assert "Keep a top rung only when" in flat
    # What ran is recorded in the step's own PR; history is never rewritten.
    assert "Settings updated <YYYY-MM-DD>: was" in flat
    assert "Never rewrite the table of a step that reads `Complete`" in flat
    assert "the §3 Settings update" in flat
