# Planning workflow — project and phase roadmaps

The reference for authoring planning documents with roadmodel in **any**
project. Three asks, three commands, no retyping — plus one command that
keeps roadmodel current in every project at once (§5).

## 1. One-time setup per machine

Slash commands are **per machine** (Claude Code reads them from your
home directory), so do this once on every machine you plan on — the
Mac and the PC each need their own copy.

macOS / Linux, from a roadmodel checkout:

```sh
pip install -U roadmodel          # in the env your `roadmodel` runs from
mkdir -p ~/.claude/commands
cp docs/claude-commands/roadm*.md ~/.claude/commands/   # project, phase, step, update
```

Windows PowerShell, no checkout needed (fetches from `main`):

```powershell
$base = "https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main/docs/claude-commands"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\commands" | Out-Null
foreach ($n in "roadmap-project","roadmap-phase","roadmap-step","roadmodel-update") {
  curl.exe -fsSL "$base/$n.md" -o "$env:USERPROFILE\.claude\commands\$n.md"
}
```

Then **reload the editor window** (VS Code: `Developer: Reload Window`)
— the Claude Code extension scans commands when it starts, not when
you open a new chat. Type `/` in a chat; `roadmap-project`,
`roadmap-phase`, and `roadmap-step` should be listed.

The five files in [`docs/claude-commands/`](claude-commands/) become
the user-scope Claude Code slash commands `/roadmap-project`,
`/roadmap-phase`, `/roadmap-step`, `/roadmap-refresh`, and
`/roadmodel-update`, available
in every project on that machine. They are also the source for the
Gemini CLI and Codex versions — see "Other agents" below. The first two are thin: each executes
the paste-prompt the planning kit ships, so they never drift from the
kit. The third reads the step straight out of the phase roadmap and
EXECUTES it — code, tests, PR, merge. The fourth is bookkeeping only
(below). The fifth re-fetches the others (and itself) every time it runs, so
this copy step is a one-time bootstrap. Newer Claude Code
builds also accept them as skills — copy each file to
`~/.claude/skills/<name>/SKILL.md` with a `name: <name>` frontmatter
line if `commands/` is not picked up.

### Bookkeeping without running a step: `/roadmap-refresh`

`/roadmap-step` does the work of a step; `/roadmap-refresh` does none.
It marks every step that has already shipped (a merged PR on the step's
own Branch ⇒ `Complete — PR #n`), then re-runs the model selector for the
current step and every step after it, so their Settings reflect today's
catalog and your user-context. Completed steps are never touched — their
Settings are the record of what ran. It delivers one docs-only PR and
starts nothing.

Use it after a model generation ships, after your subscriptions change,
or once to bring an older roadmap up to date. Refresh AFTER the planning
kit is current (`/roadmodel-update`), since the selector it runs is the
kit's.

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
   `**Status:**` line — directly under its `## Step 3` heading — to
   `Complete — PR #n (date)`, appends ✅ to that heading, sets the
   step's Summary Table Status cell, commits
   `docs: mark Phase 1 Step 3 complete` on the step branch, and
   pushes. So `docs/phase01-roadmap.md` on `main` says Step 3 is done
   exactly when PR #n merges — never before, and never by a later
   chat reconstructing history. The same commit marks the phase:
   Step 1 flips the phase roadmap's own `**Status:**` line (under its
   title) and `ROADMAP.md`'s (under the `### Phase` heading) to
   `In progress`, the final step both to `Complete` (with its
   summary-table row and the header status line) and appends ✅ to
   the phase roadmap's title and to the phase's heading in
   `ROADMAP.md`.

The step ends with "Step 3 is complete. You can now move on to
Step 4." and nothing after it — every finding has been dispatched
(roadmap edited, issue opened, PR body) before that line is emitted.
If the AI reports the step is NOT complete, it names what is
outstanding; nothing is silently carried. Then close the chat and
`/roadmap-step 1 4` in a new one.

### Progress at a glance

No "update the roadmaps" chore exists — the marks land with the
work. A completed step's heading ends in ✅, and so does a completed
phase's heading in `ROADMAP.md` and its phase roadmap's title, so the
rendered preview, the outline, and the table of contents show progress
without opening anything. Each phase's Status line sits directly under
its heading; the phase roadmap's Summary Table and `ROADMAP.md`'s
summary table each have a Status column. To read it as text:

```sh
grep -n '^\*\*Status:\*\*' docs/phase01-roadmap.md   # one line per step
grep -n '^\*\*Status:\*\*' ROADMAP.md                # one line per phase
```

### Project roadmaps written before roadmodel 0.2.44

Before 0.2.44 a `### Phase` in `ROADMAP.md` carried its Status line
after its Goal and metadata badge, and no ✅ however it stood. Run
`/roadmap-refresh` once: it moves each phase's Status line directly
under its heading, adds ✅ to every Complete phase heading and phase
roadmap title, and updates links to headings whose anchors changed.
`/roadmap-step` makes the same migration in its own PR if it meets
the old layout first.

### Roadmaps written before roadmodel 0.2.40

Roadmodel 0.2.37 to 0.2.39 put each step's `**Status:**` line after
its `**Deploys:**` line, with no ✅ and no phase-level line. Run
`/roadmap-refresh` once: it moves every Status line under its step
heading, adds ✅ to the steps that shipped, and adds the phase Status
line and the Summary Table's Status column. It changes no status and
runs no step. `/roadmap-step` makes the same migration in its own PR
if it meets the old layout first.

### Roadmaps written before roadmodel 0.2.37

Older roadmaps have no `**Status:**` lines. The first
`/roadmap-step` you run against one backfills them in that step's
PR: every step whose `**Branch:**` has a merged PR
(`gh pr list --state merged --head <branch>`) becomes
`Complete — PR #n (merge date)`, and a step still ahead of all
verified work becomes `Not started`. A step with no PR on record
that sits behind shipped work — or in a roadmap written before
`**Branch:**` lines existed — is never guessed: it asks you which of
those are done and records your answer as `Complete — confirmed by
the operator <date> (no PR on record)`. Then the
parent `ROADMAP.md` gains a `**Status:**` line per phase (`Complete`
/ `In progress` / `Not started` from its steps) plus a Status column
in its summary table. Review that diff in the PR like
any other. To backfill without executing a step, ask for exactly
that in a new chat: "add `**Status:**` lines to ROADMAP.md and
docs/phase01-roadmap.md per the Status rule in
planning/templates/phase-roadmap-template.md" — same lookup, same
result.

## 5. Keep roadmodel current everywhere

Projects each carry roadmodel in their own conda env or venv (Step 0 of
the prompts installs it there), so a release like 0.2.37 would mean
upgrading one project at a time. Instead, from any Claude Code chat on
the machine:

```
/roadmodel-update
```

The command fetches [`scripts/update_projects.py`](../scripts/update_projects.py)
fresh from the repo and runs it. The script reads the registry
`~/.config/roadmodel/projects.txt` (one project dir per line), detects
each project's env — a `.venv`/`venv`/`env` dir, the `name:` in
`environment.yml`, a conda env named like the folder, or a conda env
inside the project; `<dir> | conda:<name>` / `<dir> | venv:<subdir>`
overrides — then, **concurrently**, upgrades `roadmodel` in every env,
re-exports `planning/` where a kit exists, and re-downloads the four
command files. One table at the end; a project whose env cannot be
detected is reported, never guessed into `base`.

First run: `/roadmodel-update E:\Code\app-one E:\Code\app-two …`
registers the dirs and runs. Later runs: `/roadmodel-update` alone. The
registry and updater live under `~/.config/roadmodel/`; nothing is
committed to any project. Without Claude Code:
`python ~/.config/roadmodel/update_projects.py [--dry-run]`.

**Hands-off:** `/roadmodel-update --install-schedule 09:00` (once per
machine) registers a daily run — launchd on macOS, Task Scheduler on
Windows, cron on Linux — so every registered project follows each
release within a day, logged to `~/.config/roadmodel/update.log`.
`--uninstall-schedule` removes it. On Windows the task runs after a start
missed while the PC was off.

**The updater keeps itself current.** It also ships inside the roadmodel
package, and the copy the schedule runs is a launcher: each run upgrades
roadmodel in a venv of its own (`~/.config/roadmodel/venv`), replaces
itself with the updater in that release, and hands the run over to it. A
fix to the updater reaches every machine with the next release, and
nobody re-fetches anything. It only ever runs a published release (a
signed tag, artifacts with provenance), never whatever is on `main`. If a
step fails, the run carries on with the local copy and its first line
says `*** self-update FAILED` with the reason.

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

## Other agents: Gemini CLI, Codex, Cursor, OpenCode

The same five commands exist for Gemini CLI, Codex, Cursor and
OpenCode, generated from the Claude Code files so they never drift. `/roadmodel-update` (or
`python ~/.config/roadmodel/update_projects.py --commands-only`)
installs them wherever it finds the tool:

| Agent      | Detected by     | Installed as                         | Invoke as              |
| ---------- | --------------- | ------------------------------------ | ---------------------- |
| Gemini CLI | `~/.gemini/`    | `~/.gemini/commands/<name>.toml`     | `/roadmap-step 1 3`    |
| Codex      | `~/.codex/`     | `~/.agents/skills/<name>/SKILL.md`   | `$roadmap-step 1 3`    |
| Cursor     | `~/.cursor/`    | same `~/.agents/skills/` file (Cursor reads it) | `/roadmap-step 1 3` |
| OpenCode   | `~/.config/opencode/` | `~/.config/opencode/commands/<name>.md` | `/roadmap-step 1 3` |

`--agents gemini,codex,cursor,opencode` forces a set. The commands behave the same:
`/roadmap-step` checks the step's Platform against the surface it is
running on and stops if they differ, so a step the roadmap assigns to
Codex is executed with `$roadmap-step` in Codex, not in Claude Code.
The `<task>` blocks, the paste-prompts, and the Status rule are
surface-independent — any agent that follows the instructions
branches, opens the PR, marks the step, and ends with the completion
line. Expect more re-prompting from smaller models on the ~1,900-line
phase template.

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
