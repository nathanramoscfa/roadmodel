---
description: Execute step M of phase P from its roadmap's <task> block (usage: /roadmap-step 1 3 [roadmap-path])
---
Execute Step $ARGUMENTS of this project's phase roadmap. Parse
"$ARGUMENTS" as: PHASE STEP [ROADMAP_PATH].

## 1. Locate the roadmap and the step

- ROADMAP_PATH if given; otherwise the first of
  `docs/phase{{PP}}-roadmap.md`, `private/phase{{PP}}-roadmap.md`, or
  any `**/phase{{PP}}-roadmap.md` (PP = PHASE zero-padded to two
  digits). If none exists, stop and say so — do not improvise a step.
- The step is the section headed `## Step {{STEP}} — …` up to the next
  `## ` heading. From it, read: the `**Branch:**` line, the
  `**Status:**` line, the Settings table (Model / Platform / Effort /
  Thinking), the single ```` ```xml ```` fenced `<task>…</task>` block,
  and the `### Step {{STEP}} acceptance criteria` list. If the Branch
  line, Settings table, task block, or criteria are missing, stop and
  report which. A missing Status line is handled in §2.

## 2. Status gate — the roadmap on `main` is the ledger

Each step's `**Status:**` line is `Not started` until the step's own
PR flips it to `Complete — PR #n (YYYY-MM-DD)` (Stage 3 of the
lifecycle), so the roadmap on `main` says a step is done exactly when
its PR merged. Check it before touching anything:

- **Step {{STEP}} already reads `Complete`** → stop. It has shipped;
  re-running would redo merged work. Say so, name the PR, and suggest
  `/roadmap-step {{PHASE}} {{STEP+1}}`. Proceed only if the operator
  replies that they want the step redone.
- **Step {{STEP-1}} does not read `Complete`** (STEP > 1, and the
  Execution Order does not draw the two steps in parallel) → stop.
  Either the previous step's PR has not merged, or its session
  skipped the mark. Check which with `gh pr list --state merged
  --head <Step {{STEP-1}} Branch line> --json number,mergedAt`, and
  report it. No merged PR → the operator finishes that step first
  (`/roadmap-step {{PHASE}} {{STEP-1}}`). Merged PR but no mark → the
  mark was skipped; when the operator says to proceed, backfill that
  one line in THIS step's PR (Stage 3) and continue. Never mark a step
  complete on your own judgement of the git history.
- **No step in the roadmap carries a `**Status:**` line at all** →
  the roadmap predates roadmodel 0.2.37. Backfill once, as part of
  this step's PR: for every step, run the same `gh pr list --state
  merged --head <its Branch line>` lookup — a merged PR ⇒
  `Complete — PR #n (<mergedAt date>)`, none ⇒ `Not started`. Insert
  `**Status:** …` after each step's `**Deploys:**` line (after
  `**Branch:**` if there is none), print the resulting step/status
  table, then re-apply the two bullets above. Backfill the parent
  ROADMAP.md in the same pass: every `### Phase` gets a `**Status:**`
  line under its Goal and a Status column in the summary table — a
  phase whose roadmap's steps are all Complete ⇒ `Complete — <last
  merge date>`; some ⇒ `In progress — <phase roadmap file>`; none, or
  no phase roadmap yet ⇒ `Not started`.

## 3. Settings gate — before any work

A step's Settings table is a recommendation frozen on the day the roadmap
was written. Providers supersede models within weeks and the operator's
posture changes, so read the table as **intent**, not as a string to
match exactly — and record what actually ran.

Print one line: `Step {{STEP}} requires: Model <M> · Platform <P> ·
<the dials the table carries, e.g. Effort <E> · Thinking <T>, or
Intelligence <I>>. This session: <your own model> on <this surface>.`

- If Platform is not the surface you are running on (Claude Code,
  Codex, Antigravity, Cursor, …), stop: this step is meant to run on
  another surface; tell the operator which.
- **Model.** Continue if you are the table's model. Also continue if you
  are a **newer version in the same line** — Claude Opus 5 → Opus 5.5,
  Fable 5 → Fable 5.1, Sonnet 5 → Sonnet 5.1: a provider supersedes
  within a line, and the newer version is what the operator's client now
  opens on. Say so on the printed line (`… · superseded by <yours>`).
  Anything else — a different line (Opus → Sonnet, Fable → Opus), an
  older version, or a name you cannot place — stop and tell the operator
  how to switch on this surface (Claude Code: `/model <M>` then
  `/effort <E>`; Codex and Antigravity: their model picker and reasoning
  setting), then re-run this command with the same arguments. Do not
  start the step on a model it did not intend.
- **Effort.** If the table's effort is a top rung — `Max`, `Ultracode`,
  or Codex `max` / `ultra` — and `planning/user-context.md` declares
  `Consumption headroom: capped`, the table predates that posture: it is
  the pinned-top-rung default that exhausted a weekly pool. Use the
  user-context's complexity ladder for this step instead (High-complexity
  coding → `High`; `XHigh` only for novel problem-solving, multi-step
  proof, or chain-of-thought across many files) and tell the operator the
  value to set. Keep a top rung only when the step's own rationale names
  reasoning depth as the demonstrated bottleneck.
- You cannot verify the reasoning dials yourself; the printed line is
  the operator's cue to set them. Continue.

**Record what ran.** If the model or effort you proceed with differs from
the table, the step's own PR rewrites its Settings table to match (§5),
with one line beneath it:
`> Settings updated <YYYY-MM-DD>: was <old model> · <old effort>. <why>.`
The roadmap on `main` is the ledger, so it must say what actually ran.
Never rewrite the table of a step that reads `Complete`: that is history.

## 4. Lifecycle currency

The roadmap's `<lifecycle>` may predate the current contract. Execute
the step under the CURRENT lifecycle regardless, and mention the stale
block once, in the PR body, not in chat:

- If Stage 6 still says findings go in a "Follow-ups (non-blocking)"
  note after the completion line (pre-0.2.34): dispose of every finding
  before the completion line, and make "Step {{STEP}} is complete. You
  can now move on to Step {{STEP+1}}." the last line of your final
  response.
- If Stage 3 is just "OPEN THE PR" with no mark (pre-0.2.37): apply
  §5 anyway — the step's own PR flips its `**Status:**` line.

## 5. Execute

Run the `<task>` block exactly as if the operator had pasted it,
starting at Stage 1 — `git checkout -b <the Branch line>` from a
clean, up-to-date `main` is your first tool call. Treat every
`<requirement>`, the `<security>` block, and the acceptance criteria
as binding. Do not read ahead into other steps except where the task
block tells you to.

At Stage 3, right after `gh pr create` returns the PR number: set this
step's `**Status:**` line to `Complete — PR #<n> (<today, YYYY-MM-DD>)`
(plus any §2 backfill, and the §3 Settings update when the step ran on
different settings than its table), commit on the step branch as
`docs: mark Phase {{PHASE}} Step {{STEP}} complete`, and push. If this
is the phase's final step, the same commit marks the phase in the
parent ROADMAP.md: its `**Status:**` line under `### Phase {{PHASE}}`
becomes `Complete — …`, with its row in the summary table and the
header `> **Status:**` line; if this is Step 1, that line becomes
`In progress — <this roadmap>` instead. A git-excluded roadmap (e.g.
`private/`) needs the edit only. Stage 6's
completion line presupposes this mark: do not emit it unless `main`
now carries the step's `Complete` line.
