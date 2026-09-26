---
description: Bring every roadmap's Status ledger and upcoming Settings up to date — bookkeeping only, no step runs (usage: /roadmap-refresh [roadmap-dir])
---
Bring this project's roadmaps current **without executing any step**:
mark what has already shipped, then re-run the model selector for every
step that has not. This is bookkeeping only — no step's `<task>` block
runs, and no code is changed. Only roadmap files change, plus the
references that point at them when §1 moves them into `docs/roadmap/`.

Roadmap directory: the first token of "$ARGUMENTS" if given; otherwise
`docs/roadmap/`, or, in a project whose roadmaps have not moved there
yet, wherever it keeps them (the repo root, `docs/`, a `roadmaps/`
folder, or a git-excluded `private/`).

## 0. Guard

- Do NOT run any step's `<task>` block, and do not edit anything but
  the project roadmap (`ROADMAP.md`) and the phase roadmaps
  (`phaseNN-roadmap.md`), except the path references §1 updates when it
  moves them.
- If the roadmaps are tracked by git: your first tool call is
  `git checkout -b chore/roadmap-refresh-<YYYY-MM-DD>` from a clean,
  up-to-date `main`. If they are git-excluded (e.g. `private/`), edit
  them in place — there is no branch or PR.
- If the only uncommitted edits to tracked files are under `planning/`,
  they are roadmodel's kit, re-exported by the daily updater. Carry them
  onto the branch and commit them first, on their own, as
  `chore(planning): refresh the roadmodel kit to <version>`
  (`roadmodel --version`), so no separate kit PR is needed. Kit files
  the repo does not track stay untracked. An uncommitted edit to any
  other tracked file: stop and report it.
- An untracked `AGENTS.md` at the repo root that carries the marker
  `<!-- Created once by roadmodel-update. Edit freely: it is never overwritten. -->`
  is roadmodel's too: the updater writes it once so Codex, Antigravity,
  Cursor and the other agents follow the same instructions. It belongs in
  the repo. Do not stop on it and do not ask: commit it first, on its own,
  as `chore: commit the AGENTS.md roadmodel-update created`, before the kit
  commit if there is one. An untracked `AGENTS.md` WITHOUT that marker is
  the operator's own file: leave it untracked and out of the PR.
- If `planning/model-selector.txt` does not exist, first run
  `roadmodel export-kit . --force` so §3 uses the current selector.

## 1. Locate, and move into `docs/roadmap/`

Find the project roadmap and every phase roadmap. List them with their
paths.

Roadmaps live in `docs/roadmap/`: `ROADMAP.md` and every
`phaseNN-roadmap.md` (sub-phases too, such as `phase04.5-…-roadmap.md`),
together in one folder. Git-excluded roadmaps (e.g. `private/`) stay
where they are, and in such a project nothing moves: a tracked
`ROADMAP.md` beside them is a published copy. In any other project, every
roadmap outside `docs/roadmap/` moves there now, in a commit of its own
before the ledger work:

1. `git mv` each one into `docs/roadmap/`, keeping its filename. A
   roadmap written but not yet committed moves with a plain `mv`.
2. Fix the relative links inside the moved files so each resolves from
   `docs/roadmap/`: from the root, `[optimize](docs/optimize.md)` becomes
   `[optimize](../optimize.md)` and `[cli](src/cli.py)` becomes
   `[cli](../../src/cli.py)`. Links between roadmaps stay as they are,
   since they now share a folder.
3. Update every reference to a moved file in the rest of the repo. Run
   `git grep -n` for each old path, and for each bare filename (a script
   run from the root names `phase03-roadmap.md` alone), skipping
   `planning/`. Every Markdown link must resolve after the move
   (README, CLAUDE.md, AGENTS.md, other docs). Every path a script, test
   or CI workflow reads must name the new location
   (`files_exist phase03-roadmap.md`, `awk … ROADMAP.md`). Change only
   the path. Historical records, such as CHANGELOG entries, stay as
   written.
4. Run the project's own checks that read roadmaps (its
   `scripts/verify-phase*.sh --fast`, and any test that names a roadmap)
   and fix whatever path they still miss.
5. Commit as `docs: move the roadmaps into docs/roadmap/`.

Print the old path → new path table.

## 2. Status ledger — mark what has already shipped

For every step in every phase roadmap, look up its `**Branch:**` line:
`gh pr list --state merged --head <branch> --json number,mergedAt --limit 1`.

- A merged PR ⇒ `**Status:** Complete — PR #<n> (<mergedAt date>)`.
- No merged PR, and no verified `Complete` step comes after it in phase
  order ⇒ `**Status:** Not started` — it is simply ahead — unless it
  already reads `In progress` and its branch has an OPEN PR; then leave
  it.
- No merged PR, but verified work comes AFTER it, or its phase roadmap
  has no `**Branch:**` lines at all (written before that convention) ⇒
  unverified. Such a step may have shipped under another branch name, or
  been operator work that never had a PR (a `→ operate` step). Do not
  decide either way, and do not write `Not started`: collect every
  unverified step, then ask the operator which are done, listing them
  by phase with any hint you found (a merged PR whose branch names the
  step, the step's `→ operate` verb, an open PR). One question for the
  whole list; a range answer ("everything before Phase 12 is done") is
  fine. Record each answer as
  `**Status:** Complete — confirmed by the operator <YYYY-MM-DD> (no PR on record)`,
  `In progress`, or `Not started`, and only then continue.
- If the operator hands the call back ("I don't know — you figure it
  out"), settle each unverified step from evidence instead, and cite it:
  a merged PR that shipped the step under another branch (its title or
  diff names the step or its deliverables); for a roadmap older than
  per-step PRs, the phase's release tag or its closing QA deliverables
  (`verify-phaseN.sh`, `phaseN-qa-findings.md`) on `main`, with later
  phases built on top of it; the files the step's Goal names, present on
  `main`; a live check for a deploy or gate step. Record
  `**Status:** Complete — verified <YYYY-MM-DD>: <evidence>`. Evidence
  that it did NOT happen — a gate still up, a deliverable absent — means
  `Not started` or `In progress`, with that evidence beside it. A step
  with no evidence either way is `Not started`, never a guess.
- Put the line directly under the step's `## Step N — …` heading, before
  its Goal. Move an existing `**Status:**` line there (roadmaps written
  before roadmodel 0.2.40 carry it after `**Deploys:**`), so each step
  ends up with exactly one.
- A step that reads `Complete` gets ` ✅` at the end of its heading
  (`## Step 3 — 4B Estimators ✅`); a step that does not, has none. The
  mark is what shows completion in the preview, the outline, and the
  table of contents.
- Never mark a step complete on your own judgement of the git history.
  Only a merged PR on the step's own Branch, or the operator's word,
  counts.

Then each phase roadmap itself: a `**Status:**` line directly under its
`# ` title (all its steps Complete ⇒ `Complete — <last merge date>`;
some ⇒ `In progress`; none ⇒ `Not started`), and a Status column in its
Summary Table (add it if missing): each step's row mirrors that step's
line (`Complete — PR #<n>` or `Not started`), verification rows read
`--`. A phase roadmap that reads `Complete` gets ` ✅` at the end of its
title (`# Phase 5 Roadmap — Downside-risk efficient frontier ✅`); one
that does not, has none.

Then the project roadmap: every `### Phase` gets a `**Status:**` line
directly under its heading, before its Goal — the place a step carries
its own. Move an existing one there (roadmaps written before roadmodel
0.2.44 carry it after the Goal or the metadata badge), so each phase
ends up with exactly one; change no Status value while moving it. All of
a phase's steps Complete ⇒ `Complete — <last merge date>`; some ⇒
`In progress — <phase roadmap file>`; none, or no phase roadmap yet ⇒
`Not started`. A phase that reads `Complete` gets ` ✅` at the end of
its heading (`### Phase 5 — Downside-risk efficient frontier ✅`); a
phase that does not, has none. The mark is how a reader of the project
roadmap sees which phases are done, in the preview, the outline and the
table of contents, as they see steps in a phase roadmap. Its summary
table gets a Status column. A phase roadmap with no `### Phase` section
of its own (a sub-phase such as 4.5 or 31.5, written after the project
roadmap) gets one, in phase order: its title, the Status line, a
one-paragraph Goal drawn from the phase roadmap's own overview, and a
pointer to the file. Without it, the project ledger hides the phase that
is underway.

A heading that gains or loses ` ✅` gets a new anchor (GitHub renders
`### Phase 6 — Report ✅` as `#phase-6--report-`, with a trailing
hyphen). Update every link in the repo's Markdown that points at the old
anchor.

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
  A changed backup alone counts as a difference; name it in that line.
- Every table carries a `Backup` row directly under `Model`: the
  selector's BACKUP with its own platform and dial in one cell
  (`GPT-5.6 Terra — Codex · Intelligence Medium`), or `None`. A table
  written before roadmodel 0.2.41 has no such row: add it from the
  backup the step already names (its Model rationale's closing
  sentence, or its entry in the Model selection blocks) — a layout
  fix, not a new pick, so it takes no `Settings updated` line.
- Keep the step's `BACKUP:` line in the Model selection blocks equal to
  its table's Backup row.
- If it matches, leave the step exactly as it is.
- **Never touch a step that reads `Complete`.** Its settings are the
  record of what ran.
- Keep each step's Conversation row as written — it is session hygiene,
  not a model choice.

Print the step · was · now · changed table.

## 4. Deliver

Commit once, as `docs: refresh roadmap status and upcoming settings`
(after the kit commit from §0 and the move commit from §1, if there
were any).
Then open the PR and take it through this project's own lifecycle — the
same CI gates a step's PR passes — to merge. For git-excluded roadmaps,
the edits are the delivery.

Reply with the tables and the PR link. **Do not start any step** —
the next one runs in a fresh conversation with `/roadmap-step <phase> <step>`.
