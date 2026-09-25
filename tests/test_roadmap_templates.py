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
    # Legacy backfill never guesses a step behind shipped work.
    assert "confirmed by the operator" in flat
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


REFRESH_COMMAND = ROOT / "docs" / "claude-commands" / "roadmap-refresh.md"


# ---------------------------------------------------------------------------
# Completion is shown where a reader looks (0.2.40): the Status line sits
# directly under each step heading, a Complete step's heading ends in ✅ (so
# the preview, the outline and the table of contents show progress), the
# phase roadmap carries its own Status line under the title, and its Summary
# Table a Status column. Before this, the line hid below Goal/Branch/Deploys.
# ---------------------------------------------------------------------------


def test_phase_template_puts_status_at_the_step_heading() -> None:
    text = PHASE.read_text()
    flat = re.sub(r"\s+", " ", text)
    headings = re.findall(r"^## Step [^\n]*$", text, re.M)
    assert len(headings) >= 3  # Step 1, Step 2, the QA step
    for heading in headings:
        after = text[text.index(heading) :]
        assert re.match(
            re.escape(heading) + r"\n\n\*\*Status:\*\* Not started\n\n> \*\*Goal:\*\*", after
        ), f"Status is not directly under: {heading}"
    # No step keeps its Status line in the old place, after Deploys.
    assert not re.search(
        r"^\*\*Deploys:\*\*[^\n]*(?:\n(?!\n)[^\n]*)*\n\n\*\*Status:\*\*", text, re.M
    )
    # The phase's own Status line, under the title.
    assert re.search(
        r"^# Phase \{\{N\}\} Roadmap — [^\n]*\n\n\*\*Status:\*\* Not started\n", text, re.M
    )
    # ✅ on completion: the Status rule, both Stage-3 copies, the QA step.
    assert "`## Step 3 — {{Step Title}} ✅`" in text
    assert "append ` ✅` to the step's `## Step` heading" in flat
    assert flat.count("✅") >= 6
    # The Summary Table's Status column, set by the same Stage-3 commit.
    assert "| Conv | Status      |" in text
    assert "Summary Table Status cell" in flat


def test_roadmap_step_marks_completion_at_the_heading() -> None:
    flat = re.sub(r"\s+", " ", STEP_COMMAND.read_text())
    assert "(directly under its heading)" in flat
    assert "append ` ✅` to its `## Step {{STEP}}` heading" in flat
    assert "Summary Table Status cell" in flat
    assert "phase-level `**Status:**`" in flat
    # An old-layout roadmap is migrated in the step's PR, never left mixed.
    assert "Status lines sit after `**Deploys:**`" in flat
    assert "Change no Status value while moving it" in flat


def test_roadmap_refresh_migrates_status_to_the_heading() -> None:
    flat = re.sub(r"\s+", " ", REFRESH_COMMAND.read_text())
    assert "directly under the step's `## Step N — …` heading" in flat
    assert "Move an existing `**Status:**` line there" in flat
    assert "`## Step 3 — 4B Estimators ✅`" in flat
    assert "a step that does not, has none" in flat
    assert "a `**Status:**` line directly under its `# ` title" in flat
    assert "a Status column in its Summary Table" in flat


def test_roadmap_refresh_gives_every_phase_roadmap_a_project_section() -> None:
    """On 2026-09-23 both refreshed projects had phase roadmaps the project
    roadmap never listed (reversi's 31.5, roadmodel's 4.5-4.10), so the
    ledger showed nothing underway while 31.5 was mid-beta."""
    flat = re.sub(r"\s+", " ", REFRESH_COMMAND.read_text())
    assert "A phase roadmap with no `### Phase` section of its own" in flat
    assert "a one-paragraph Goal drawn from the phase roadmap's own overview" in flat
    assert "the project ledger hides the phase that is underway" in flat


def test_roadmap_commands_carry_the_kit_refresh_in_their_own_pr() -> None:
    """The daily updater re-exports roadmodel's kit into planning/. Four
    projects track it, so every release left their working trees dirty and
    each needed a hand-made chore(planning) PR (jackson-opt #40, paperlock
    #75). The step or refresh PR now carries it as its own commit."""
    for command in (STEP_COMMAND, REFRESH_COMMAND):
        flat = re.sub(r"\s+", " ", command.read_text())
        assert "the only uncommitted edits to tracked files are under `planning/`" in flat
        assert "`chore(planning): refresh the roadmodel kit to <version>`" in flat
        assert "Kit files the repo does not track stay untracked" in flat
        assert "An uncommitted edit to any other tracked file: stop and report it" in flat


def test_phase_prompt_refuses_a_kit_with_the_old_status_layout() -> None:
    flat = re.sub(r"\s+", " ", PROMPT_PHASE.read_text())
    assert "a step's Status line sits after its `**Deploys:**` line" in flat
    assert "directly under every `## Step` heading" in flat


def test_roadmap_refresh_is_bookkeeping_that_runs_no_step() -> None:
    """On 2026-09-22 the operator ran /roadmap-step expecting bookkeeping and
    got a whole step implemented. /roadmap-refresh is the command they meant:
    it marks what shipped and re-selects upcoming Settings, and must never
    execute a task block or touch a completed step."""
    text = REFRESH_COMMAND.read_text()
    flat = re.sub(r"\s+", " ", text)
    # Runs nothing, edits only roadmaps.
    assert "without executing any step" in flat
    assert "Do NOT run any step's `<task>` block" in flat
    assert "Do not start any step" in flat
    # The ledger comes from merged PRs on each step's own Branch, never judgement.
    assert "gh pr list --state merged --head" in text
    assert "Never mark a step complete on your own judgement" in flat
    # A step with no PR on record BEHIND shipped work is the operator's call,
    # never "Not started" by default: on 2026-09-23 a literal reading would
    # have marked ~220 shipped reversi steps (roadmaps older than Branch
    # lines) Not started, then re-planned every one of them.
    assert "unverified" in flat
    assert "Do not decide either way, and do not write `Not started`" in flat
    assert "Complete — confirmed by the operator <YYYY-MM-DD> (no PR on record)" in flat
    assert "only then continue" in flat
    # … and when the operator hands it back, evidence decides, cited — the
    # operator could not answer for reversi's 221 pre-Branch steps either.
    assert "If the operator hands the call back" in flat
    assert "Complete — verified <YYYY-MM-DD>: <evidence>" in flat
    assert "never a guess" in flat
    # Settings are re-selected the same way the roadmap was written …
    assert "planning/model-selector.txt" in text and "planning/user-context.md" in text
    assert "do not call any external API" in flat
    # … for the current step onward only; completed steps are history.
    assert "The current step is the first step" in flat
    assert "Never touch a step that reads `Complete`" in flat
    assert "Settings updated <YYYY-MM-DD> (refresh): was" in flat
    # OpenCode refuses '@' and Gemini refuses '!{' / '@{' — keep it portable.
    assert "@" not in text and "!{" not in text


def test_every_command_ships_to_every_agent() -> None:
    """A command file in docs/claude-commands/ that the updater does not
    list never reaches Codex, Antigravity or VS Code."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "update_projects", ROOT / "scripts" / "update_projects.py"
    )
    assert spec and spec.loader
    up = importlib.util.module_from_spec(spec)
    import sys as _sys

    # A dataclass resolves its module through sys.modules by the SPEC's name.
    _sys.modules.setdefault(spec.name, up)
    spec.loader.exec_module(up)
    on_disk = {p.stem for p in (ROOT / "docs" / "claude-commands").glob("*.md")}
    assert on_disk == set(up.COMMANDS)


def test_every_settings_table_carries_a_backup_row() -> None:
    """The backup lived only in the rationale's last sentence and the
    selection blocks at the foot of the file, so an operator looking at a
    step's Settings table could not see what to switch to. Every table in
    the template — the three platform variants and the step skeletons —
    carries a Backup row directly under Model."""
    lines = PHASE.read_text().splitlines()
    model_rows = [i for i, line in enumerate(lines) if line.startswith("| Model ")]
    assert len(model_rows) >= 5
    for i in model_rows:
        assert lines[i + 1].startswith("| Backup "), lines[i]
    flat = re.sub(r"\s+", " ", PHASE.read_text())
    assert "Every table carries Model / Backup / Platform / Conversation" in flat


def test_roadmap_commands_handle_the_backup_row() -> None:
    refresh = re.sub(r"\s+", " ", REFRESH_COMMAND.read_text())
    assert "Every table carries a `Backup` row directly under `Model`" in refresh
    assert "a layout fix, not a new pick" in refresh
    step = re.sub(r"\s+", " ", STEP_COMMAND.read_text())
    assert "If you are that backup model on that platform, continue" in step
    prompt = re.sub(r"\s+", " ", PROMPT_PHASE.read_text())
    assert "its Settings tables have no `Backup` row" in prompt


def test_roadmap_writing_commands_set_their_own_effort() -> None:
    """Writing a roadmap is the planning work the operator wants done at a
    fixed rung, without typing /effort first: a phase roadmap at xhigh, the
    project roadmap at max. Claude Code reads `effort:` from a command's
    frontmatter; the ports for other agents carry only the description."""
    import importlib.util
    import sys as _sys

    spec = importlib.util.spec_from_file_location(
        "update_projects", ROOT / "scripts" / "update_projects.py"
    )
    assert spec and spec.loader
    up = importlib.util.module_from_spec(spec)
    _sys.modules.setdefault(spec.name, up)
    spec.loader.exec_module(up)
    commands = ROOT / "docs" / "claude-commands"
    for name, effort in (("roadmap-phase", "xhigh"), ("roadmap-project", "max")):
        body = (commands / f"{name}.md").read_text()
        head = body.split("\n---\n", 1)[0]
        assert f"\neffort: {effort}" in head, name
        description, text = up._split_frontmatter(body)
        assert description and "effort:" not in text
        assert "effort:" not in up.port_gemini(name, body)


def test_roadmap_commands_commit_the_agents_md_the_updater_created() -> None:
    """roadmodel-update writes AGENTS.md once in every project and never
    commits it, so each project's next step stopped on a dirty tree and
    asked the operator what to do (assetmark-dashboard, 2026-09-24). The
    step or refresh PR now commits it — recognised by the updater's own
    marker, which must match what the updater writes."""
    marker = "<!-- Created once by roadmodel-update. Edit freely: it is never overwritten. -->"
    assert marker in (ROOT / "scripts" / "update_projects.py").read_text()
    for command in (STEP_COMMAND, REFRESH_COMMAND):
        flat = re.sub(r"\s+", " ", command.read_text())
        assert f"`{marker}`" in flat
        assert "`chore: commit the AGENTS.md roadmodel-update created`" in flat
        assert "Do not stop on it and do not ask" in flat
        assert "WITHOUT that marker is the operator's own file" in flat
