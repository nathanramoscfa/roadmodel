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
   (or `private/`), and reads its `**Branch:**` line, Settings table,
   `<task>` block, and acceptance criteria.
2. **Gates on settings.** It prints `Step 3 requires: Model … ·
   Platform … · Effort … · Thinking …` next to the session's own
   model. Wrong model or a non-Claude-Code platform → it stops and
   tells you what to run (`/model`, `/effort`). It cannot read your
   Effort/Thinking settings, so that line is your cue to check them
   before it proceeds — set them first if you know them:
   `/model <M>` then `/effort <E>`, then `/roadmap-step 1 3`.
3. **Applies the current Stage 6** even if the roadmap was generated
   before roadmodel 0.2.34 (old "Follow-ups" lifecycle): findings are
   disposed of before the completion line, and that line is the last
   line of the response.
4. **Runs the `<task>` block** exactly as if pasted, starting with
   `git checkout -b <Branch>` from clean `main`.

The step ends with "Step 3 is complete. You can now move on to
Step 4." and nothing after it — every finding has been dispatched
(roadmap edited, issue opened, PR body) before that line is emitted.
If the AI reports the step is NOT complete, it names what is
outstanding; nothing is silently carried. Then close the chat and
`/roadmap-step 1 4` in a new one.

## What `/roadmap-project` and `/roadmap-phase` do

1. **Refreshes the kit** — `pip install -U roadmodel && roadmodel
   export-kit . --force` — so templates, catalog, and your curated
   `~/.config/roadmodel/user-context.md` are current. Creates
   `planning/` if the project has none.
2. **Checks the template is current** — the exported phase template's
   Stage 6 must read "DISPOSE OF EVERY FINDING, DECLARE COMPLETION,
   THEN NEW CONVERSATION". A stale kit stops with a message instead of
   baking an old step lifecycle into every step.
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

- roadmodel **>= 0.2.35** — the first release whose kit ships
  `planning/prompts/`. Older kits have the templates but not the prompts.
- Claude Code for the slash commands; any AI chat for the paste-prompts.
