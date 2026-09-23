---
description: Bring every roadmap's Status ledger and upcoming Settings up to date — bookkeeping only, no step runs (usage: /roadmap-refresh [roadmap-dir])
---
Bring this project's roadmaps current **without executing any step**:
mark what has already shipped, then re-run the model selector for every
step that has not. This is bookkeeping only — no step's `<task>` block
runs, and no code, test, CI or config file is touched. Only roadmap
files change.

Roadmap directory: the first token of "$ARGUMENTS" if given; otherwise
wherever this project keeps them (the repo root, `docs/`, or
`private/`).

## 0. Guard

- Do NOT run any step's `<task>` block, and do not edit anything but
  the project roadmap (`ROADMAP.md`) and the phase roadmaps
  (`phaseNN-roadmap.md`).
- If the roadmaps are tracked by git: your first tool call is
  `git checkout -b chore/roadmap-refresh-<YYYY-MM-DD>` from a clean,
  up-to-date `main`. If they are git-excluded (e.g. `private/`), edit
  them in place — there is no branch or PR.
- If `planning/model-selector.txt` does not exist, first run
  `roadmodel export-kit . --force` so §3 uses the current selector.

## 1. Locate

Find the project roadmap and every phase roadmap. List them.

## 2. Status ledger — mark what has already shipped

For every step in every phase roadmap, look up its `**Branch:**` line:
`gh pr list --state merged --head <branch> --json number,mergedAt --limit 1`.

- A merged PR ⇒ `**Status:** Complete — PR #<n> (<mergedAt date>)`.
- None ⇒ `**Status:** Not started`, unless the step already reads
  `In progress` and its branch has an OPEN PR — then leave it.
- Put the line directly under the step's `## Step N — …` heading, before
  its Goal. Move an existing `**Status:**` line there (roadmaps written
  before roadmodel 0.2.40 carry it after `**Deploys:**`), so each step
  ends up with exactly one.
- A step that reads `Complete` gets ` ✅` at the end of its heading
  (`## Step 3 — 4B Estimators ✅`); a step that does not, has none. The
  mark is what shows completion in the preview, the outline, and the
  table of contents.
- Never mark a step complete on your own judgement of the git history.
  Only a merged PR on the step's own Branch counts.

Then each phase roadmap itself: a `**Status:**` line directly under its
`# ` title (all its steps Complete ⇒ `Complete — <last merge date>`;
some ⇒ `In progress`; none ⇒ `Not started`), and a Status column in its
Summary Table (add it if missing): each step's row mirrors that step's
line (`Complete — PR #<n>` or `Not started`), verification rows read
`--`.

Then the project roadmap: every `### Phase` gets a `**Status:**` line
under its Goal, and its summary table a Status column. All of a phase's
steps Complete ⇒ `Complete — <last merge date>`; some ⇒
`In progress — <phase roadmap file>`; none, or no phase roadmap yet ⇒
`Not started`.

Print the phase · step · status table.

## 3. Settings — re-select every step that has not shipped

The current step is the first step, in phase order, that does not read
`Complete`. For the current step and every step after it, in every phase
roadmap that exists, re-run the model selector exactly as the phase
roadmap was written: `planning/model-selector.txt`, with prices from
`planning/model-tier-cost-scale.md` and display rules from
`planning/settings-display.md`, against `planning/user-context.md`. You
are the engine — do not call any external API. Honor every availability
exclusion in the selector, and include a backup model.

- If the result differs from the step's Settings table, rewrite the
  table and its Model rationale, and add one line beneath the table:
  `> Settings updated <YYYY-MM-DD> (refresh): was <old model> · <old effort>. <why>.`
- If it matches, leave the step exactly as it is.
- **Never touch a step that reads `Complete`.** Its settings are the
  record of what ran.
- Keep each step's Conversation row as written — it is session hygiene,
  not a model choice.

Print the step · was · now · changed table.

## 4. Deliver

Commit once, as `docs: refresh roadmap status and upcoming settings`.
Then open the PR and take it through this project's own lifecycle — the
same CI gates a step's PR passes — to merge. For git-excluded roadmaps,
the edits are the delivery.

Reply with both tables and the PR link. **Do not start any step** —
the next one runs in a fresh conversation with `/roadmap-step <phase> <step>`.
