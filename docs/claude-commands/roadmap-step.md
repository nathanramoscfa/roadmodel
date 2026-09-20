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
  `## ` heading. From it, read: the `**Branch:**` line, the Settings
  table (Model / Platform / Effort / Thinking), the single
  ```` ```xml ```` fenced `<task>…</task>` block, and the
  `### Step {{STEP}} acceptance criteria` list. If any of these is
  missing, stop and report which.

## 2. Settings gate — before any other action

Print one line: `Step {{STEP}} requires: Model <M> · Platform <P> ·
Effort <E> · Thinking <T>. This session: <your own model>.`

- If Platform is not Claude Code, stop: this step is meant to run on
  another surface; tell the operator which.
- If the step's Model is not the model you are running as, stop and
  tell the operator to run `/model <M>` and `/effort <E>` (and set
  thinking to <T>), then re-run `/roadmap-step $ARGUMENTS`. Do not
  start the step on the wrong model.
- You cannot verify Effort or Thinking yourself; the printed line is
  the operator's cue to check them. Continue.

## 3. Lifecycle currency

If the `<lifecycle>` in the task block still says findings go in a
"Follow-ups (non-blocking)" note after the completion line, the
roadmap predates roadmodel 0.2.34. Execute the step under the
CURRENT Stage 6 anyway: dispose of every finding before the
completion line, and make "Step {{STEP}} is complete. You can now
move on to Step {{STEP+1}}." the last line of your final response.
Mention the stale lifecycle once, in the PR body, not in chat.

## 4. Execute

Run the `<task>` block exactly as if the operator had pasted it,
starting at Stage 1 — `git checkout -b <the Branch line>` from a
clean, up-to-date `main` is your first tool call. Treat every
`<requirement>`, the `<security>` block, and the acceptance criteria
as binding. Do not read ahead into other steps except where the task
block tells you to.
