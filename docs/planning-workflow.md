# Planning workflow — project and phase roadmaps

The reference for authoring planning documents with roadmodel in **any**
project. Three asks, three commands, no retyping.

## 1. One-time setup per machine

Slash commands are **per machine** (Claude Code reads them from your
home directory), so do this once on every machine you plan on — the
Mac and the PC each need their own copy.

macOS / Linux, from a roadmodel checkout:

```sh
pip install -U roadmodel          # in the env your `roadmodel` runs from
mkdir -p ~/.claude/commands
cp docs/claude-commands/roadmap-*.md ~/.claude/commands/   # project, phase, step
```

Windows PowerShell, no checkout needed (fetches from `main`):

```powershell
$base = "https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main/docs/claude-commands"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\commands" | Out-Null
foreach ($n in "roadmap-project","roadmap-phase","roadmap-step") {
  curl.exe -fsSL "$base/$n.md" -o "$env:USERPROFILE\.claude\commands\$n.md"
}
```

Then **reload the editor window** (VS Code: `Developer: Reload Window`)
— the Claude Code extension scans commands when it starts, not when
you open a new chat. Type `/` in a chat; `roadmap-project`,
`roadmap-phase`, and `roadmap-step` should be listed.

The three files in [`docs/claude-commands/`](claude-commands/) become
the user-scope Claude Code slash commands `/roadmap-project`,
`/roadmap-phase`, and `/roadmap-step`, available in every project on
that machine. The first two are thin: each executes the paste-prompt
the planning kit ships, so they never drift from the kit. The third
reads the step straight out of the phase roadmap. Newer Claude Code
builds also accept them as skills — copy each file to
`~/.claude/skills/<name>/SKILL.md` with a `name: <name>` frontmatter
line if `commands/` is not picked up.

## 2. Write the project roadmap

Open a **new** Claude Code chat in the project root and type:

```
/roadmap-project
```

Optional argument: where the brief lives, e.g.
`/roadmap-project @docs/brief.md`. Default is `@README.md`. Output is
`ROADMAP.md`.

## 3. Write a phase roadmap

New chat in the project root:

```
/roadmap-phase 6
```

Optional second argument: the output path, e.g.
`/roadmap-phase 6 private/phase06-roadmap.md`. Defaults: parent roadmap
`@ROADMAP.md`, output `docs/phaseNN-roadmap.md`, continuity from the
previous phase's roadmap.

## 4. Execute a step

New chat in the project root — one step per conversation:

```
/roadmap-step 1 3
```

(phase 1, step 3; optional third argument: the roadmap path if it is
not at `docs/` or `private/`). No copying the `<task>` block by hand.
The command:

1. **Finds the step** — `## Step 3 — …` in `docs/phase01-roadmap.md`
   (or `private/`), and reads its `**Branch:**` line, `**Status:**`
   line, Settings table, `<task>` block, and acceptance criteria.
2. **Gates on status.** The roadmap on `main` is the ledger: each
   step's `**Status:**` line is `Not started` until the step's own PR
   flips it to `Complete — PR #n (date)`. Step 3 already Complete →
   it stops (re-running would redo merged work). Step 2 not Complete
   → it stops and says whether Step 2's PR is unmerged or its mark
   was skipped (`gh pr list --state merged --head <branch>`); you
   finish Step 2, or say "proceed" and it backfills that one line in
   Step 3's PR. It never marks a step complete from git history on
   its own judgement.
3. **Gates on settings.** It prints `Step 3 requires: Model … ·
   Platform … · Effort … · Thinking …` next to the session's own
   model. Wrong model or a non-Claude-Code platform → it stops and
   tells you what to run (`/model`, `/effort`). It cannot read your
   Effort/Thinking settings, so that line is your cue to check them
   before it proceeds — set them first if you know them:
   `/model <M>` then `/effort <E>`, then `/roadmap-step 1 3`.
4. **Applies the current lifecycle** even if the roadmap was generated
   by an older kit: pre-0.2.34 "Follow-ups" roadmaps still dispose of
   findings before the completion line; pre-0.2.37 roadmaps (bare
   "OPEN THE PR", no Status lines) still get the Stage 3 mark.
5. **Runs the `<task>` block** exactly as if pasted, starting with
   `git checkout -b <Branch>` from clean `main`.
6. **Marks the step in its own PR.** At Stage 3, right after
   `gh pr create` returns the number, it sets the step's
   `**Status:**` line to `Complete — PR #n (date)`, commits
   `docs: mark Phase 1 Step 3 complete` on the step branch, and
   pushes. So `docs/phase01-roadmap.md` on `main` says Step 3 is done
   exactly when PR #n merges — never before, and never by a later
   chat reconstructing history. The same commit marks the phase in
   `ROADMAP.md`: Step 1 flips its `**Status:**` line to `In progress`,
   the final step to `Complete` (with its summary-table row and the
   header status line).

The step ends with "Step 3 is complete. You can now move on to
Step 4." and nothing after it — every finding has been dispatched
(roadmap edited, issue opened, PR body) before that line is emitted.
If the AI reports the step is NOT complete, it names what is
outstanding; nothing is silently carried. Then close the chat and
`/roadmap-step 1 4` in a new one.

### Progress at a glance

No "update the roadmaps" chore exists — the marks land with the
work. To read progress:

```sh
grep -n '^\*\*Status:\*\*' docs/phase01-roadmap.md   # one line per step
grep -n '^\*\*Status:\*\*' ROADMAP.md                # one line per phase
```

### Roadmaps written before roadmodel 0.2.37

Older roadmaps have no `**Status:**` lines. The first
`/roadmap-step` you run against one backfills them in that step's
PR: every step whose `**Branch:**` has a merged PR
(`gh pr list --state merged --head <branch>`) becomes
`Complete — PR #n (merge date)`, the rest `Not started`, and the
parent `ROADMAP.md` gains a `**Status:**` line per phase (`Complete`
/ `In progress` / `Not started` from its steps) plus a Status column
in its summary table. Review that diff in the PR like
any other. To backfill without executing a step, ask for exactly
that in a new chat: "add `**Status:**` lines to ROADMAP.md and
docs/phase01-roadmap.md per the Status rule in
planning/templates/phase-roadmap-template.md" — same lookup, same
result.

## What `/roadmap-project` and `/roadmap-phase` do

1. **Refreshes the kit** — `pip install -U roadmodel && roadmodel
   export-kit . --force` — so templates, catalog, and your curated
   `~/.config/roadmodel/user-context.md` are current. Creates
   `planning/` if the project has none.
2. **Checks the template is current** — the exported phase template's
   Stage 3 must read "OPEN THE PR, THEN MARK THE STEP" and its Stage 6
   "DISPOSE OF EVERY FINDING, DECLARE COMPLETION, THEN NEW
   CONVERSATION". A stale kit stops with a message instead of baking
   an old step lifecycle into every step.
3. **Executes `planning/prompts/{project,phase}-roadmap.md`** with your
   argument filled in and every other placeholder at its default. The
   AI runs `planning/model-selector.txt` against `planning/user-context.md`
   as the engine — no external API call.
4. **Writes the file and stops.** It replies with the path and a short
   summary. It does not start Step 1 — every step is its own
   conversation, per the step lifecycle in the template.

## Without slash commands (Cursor, other clients)

Open `planning/prompts/phase-roadmap.md` (or `project-roadmap.md`), fill
the `{{placeholders}}` in its table, paste everything below the rule into
a new chat, submit. Where a scheduled task keeps `planning/` current from
GitHub `main`, the prompt's Step 0 still refreshes it when roadmodel is
installed; on Windows, run Step 0 in the project's conda env
(`pip install -U roadmodel; roadmodel export-kit . --force`) — the
`scripts/export-planning-kit.sh` fallback needs bash.

## Requirements

- roadmodel **>= 0.2.37** — the first release whose templates carry the
  Status rule (per-step / per-phase `**Status:**` lines flipped by the
  step's own PR). 0.2.35 introduced `planning/prompts/`; older kits
  have the templates but not the prompts.
- Claude Code for the slash commands; any AI chat for the paste-prompts.
