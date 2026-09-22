# Bring Codex up to parity with Claude Code

Written for: an operator who runs Claude Code as the primary agent and wants
Codex to take over — same instructions, same memory, same commands, same
tools — when the Claude usage pool is exhausted or Anthropic is down.

Two parts: a **mapping table** (what corresponds to what, and which
mechanisms avoid copying anything) and a **paste-in prompt** that has Codex
do the sync in the project you are standing in.

---

## Run it with

| Field | Value | Why |
| --- | --- | --- |
| Model | **GPT-5.6 Terra** (or Luna on a tight pool) | `roadmodel score --category agentic --complexity medium` puts Luna first on score; this task edits config that everything else depends on, so Terra's extra headroom is worth one rung of the ladder. |
| Platform | Codex (CLI or IDE extension) | It is the agent being configured; it can read its own config and restart itself. |
| Intelligence | **Medium** | A bounded, well-specified file-and-config task. Raise to High only if the project has an unusual Claude setup (many hooks, many MCP servers). |

Run it **once per project** (the project-scoped half) plus **once on this
machine** (the home-scoped half). The prompt does both and says which is
which.

---

## What maps to what

| Claude Code | Codex | How to sync |
| --- | --- | --- |
| `CLAUDE.md` (project instructions) | `AGENTS.md` | **Do not copy.** Set `project_doc_fallback_filenames = ["CLAUDE.md"]` in `~/.codex/config.toml`: Codex then reads `CLAUDE.md` itself when a project has no `AGENTS.md`, so the two agents can never drift. Only write an `AGENTS.md` when a project needs Codex-specific instructions. |
| `~/.claude/CLAUDE.md` (user instructions) | `~/.codex/AGENTS.md` | Copy once; both are hand-maintained and short. |
| Auto-memory (`~/.claude/projects/<slug>/memory/*.md` + `MEMORY.md`) | Codex memories (`features.memories`, `~/.codex/memories`) | Different stores, same facts. Enable Codex memories, then import: append the Claude `MEMORY.md` index and the memory bodies into the project's `AGENTS.md` under a clearly-marked section, or paste them once and let Codex's own extractor keep them. Re-import whenever `MEMORY.md` changes materially. |
| `~/.claude/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` | Codex reads `~/.agents/skills` natively (`skills.config`). `roadmodel-update` already writes the four roadmap commands there; copy any other skill across unchanged. |
| `~/.claude/commands/<name>.md` (slash commands) | A skill in `~/.agents/skills/<name>/`, or `~/.codex/prompts/<name>.md` | Codex has no `/command` file format identical to Claude's; a skill is the faithful equivalent (it carries a name + description and is model-invocable). |
| `~/.claude.json` → `mcpServers` | `[mcp_servers.<id>]` in `~/.codex/config.toml`, or `codex mcp add` | Same servers, different file. stdio servers map key-for-key (`command`, `args`, `env`); HTTP servers use `url`. |
| `settings.json` → `model` | `model` | e.g. `"opus[1m]"` → `gpt-5.6-sol` (frontier) or `gpt-5.3-codex` (coding-specialised). |
| `settings.json` → `effortLevel` / `maxEffortLevel` | `model_reasoning_effort` (`minimal`…`xhigh`), `plan_mode_reasoning_effort` | Same ladder, one rung shorter: Codex has no `max` above `xhigh`. Mirror the **calibrated** level, not the ceiling. |
| `permissions` / `defaultMode` | `approval_policy`, `sandbox_mode` | `acceptEdits` ≈ `approval_policy = "on-request"` + `sandbox_mode = "workspace-write"`. |
| Hooks, subagents, statusline, plugins | — | **No equivalent.** Do not fake them; note them as Claude-only so nobody wonders why a hook did not fire. |

---

## The prompt

Copy everything in the block into Codex, in the project you want synced.

```text
You are bringing yourself (Codex) to parity with Claude Code on this machine
and in this project, so that when the Claude usage pool is exhausted or
Anthropic is unavailable I can switch to you and keep working with the same
instructions, memory, commands and tools.

Work in this order, and SHOW me each diff before you apply it. Do not invent
settings I do not already have in Claude Code; where something has no Codex
equivalent, say so explicitly rather than approximating it.

STEP 1 — Inventory Claude Code (read-only).
Read, where they exist:
  - ./CLAUDE.md, ./.claude/settings.json, ./.claude/settings.local.json,
    ./.claude/commands/, ./.claude/skills/, ./.mcp.json
  - ~/.claude/CLAUDE.md, ~/.claude/settings.json, ~/.claude/commands/,
    ~/.claude/skills/
  - ~/.claude.json  (read ONLY the "mcpServers" key, top-level and under
    "projects" for this repo; the file also holds unrelated local state)
  - the auto-memory directory for this project:
    ~/.claude/projects/<this repo path with "/" replaced by "-">/memory/
    (MEMORY.md is its index)
Print a short table of what you found, and which of them have no Codex
equivalent (hooks, subagents/Task, statusline, plugins, /effort ultracode).

STEP 2 — Instructions, without copying.
In ~/.codex/config.toml set:
    project_doc_fallback_filenames = ["CLAUDE.md"]
so you read CLAUDE.md directly in any project that has no AGENTS.md. Only if
this project needs Codex-specific guidance, create a minimal AGENTS.md that
says "see CLAUDE.md" plus the Codex-only notes — never a duplicate of
CLAUDE.md. If ~/.claude/CLAUDE.md exists and ~/.codex/AGENTS.md does not,
copy it across and tell me you did.

STEP 3 — Memory.
Enable your own memory in ~/.codex/config.toml:
    [features]
    memories = true
Then import what Claude already knows about this project: read that project's
MEMORY.md index and the memory files it points to, and write their CONTENT
(not the file list) into AGENTS.md under a section headed
"## Imported from Claude Code auto-memory (<today's date>)", collapsing
duplicates and dropping anything that is purely about Claude Code's own UI.
Keep it under ~150 lines; these are durable facts, not a transcript.

STEP 4 — Commands and skills.
For every ~/.claude/skills/<name>/SKILL.md and ~/.claude/commands/<name>.md
that is NOT already present at ~/.agents/skills/<name>/SKILL.md, create it
there: same body, with YAML frontmatter carrying `name` and a one-line
`description`. Do not touch ~/.agents/skills entries that `roadmodel-update`
manages (roadmap-project, roadmap-phase, roadmap-step, roadmodel-update) —
they are regenerated and your edits would be overwritten.

STEP 5 — MCP servers.
For each server in ~/.claude.json "mcpServers" that is absent from
~/.codex/config.toml, add the equivalent [mcp_servers.<id>] block: stdio
servers map command/args/env directly; HTTP servers use url. Do not copy
secrets into the file if the Claude entry reads them from the environment —
keep the same env-var indirection. List anything you skipped and why.

STEP 6 — Model and effort, calibrated.
Read ~/.claude/settings.json "model", "effortLevel" and "maxEffortLevel" and
mirror the INTENT, not the letter:
  - model: pick the Codex model of the same class (frontier ↔ frontier,
    coding-specialised ↔ coding-specialised).
  - model_reasoning_effort: the same calibrated level, remembering your ladder
    stops at xhigh (there is no `max`). If Claude is set to a ceiling rather
    than a default, mirror the DEFAULT.
  - approval_policy / sandbox_mode: match the Claude permission posture.
Print the before/after of every key you change.

STEP 7 — Verify and report.
Restart yourself if needed, then confirm out loud:
  - which instructions file you are actually reading in this project,
  - how many skills you can see and that the four roadmap-* ones are among
    them,
  - which MCP servers connected and which failed,
  - your active model, reasoning effort, approval policy and sandbox mode.
Finish with a short list of everything in Claude Code that has NO Codex
equivalent, so I know exactly what I lose by switching.
```

---

## After the sync

- **The roadmap commands.** `roadmodel-update` writes `roadmap-project`,
  `roadmap-phase`, `roadmap-step` and `roadmodel-update` to
  `~/.agents/skills/` (Codex, Cursor) and `~/.gemini/commands/*.toml`
  (Gemini CLI) from the same Claude sources, every run. Ask Codex for them by
  name ("run the roadmap-phase skill for phase 5") rather than typing
  `/roadmap-phase`.
- **The roadmodel MCP server** is registered for Claude Code but not
  automatically for Codex; Step 5 above adds it. With it, Codex gets
  `recommend_model`, `score_candidates`, `read_catalog` and
  `generate_phase_roadmap` exactly as Claude Code does.
- **Keep the two in sync going forward.** `CLAUDE.md` needs no re-sync (Codex
  reads it). Memory does: re-run Step 3 when the project's `MEMORY.md`
  changes materially. Skills and MCP servers re-sync by re-running Steps 4–5.
