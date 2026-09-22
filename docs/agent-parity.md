# Agent parity: make any coding agent match any other

Written for: an operator who runs more than one coding agent — because one
subscription's usage pool runs out, or a provider goes down, or a task suits a
different model — and wants the second agent to know what the first one knows.

One file, every direction. The **surface map** below is symmetric: read the
SOURCE column for where a setting lives today and the TARGET column for where
it has to land. The **prompt** is parameterised: fill in two names and paste.

Ecosystems covered:

| Ecosystem | Agents it covers |
| --- | --- |
| **Claude** | Claude Code (CLI + IDE extension), Claude Desktop |
| **Codex** | Codex CLI + Codex IDE extension (VS Code / Cursor / Windsurf) |
| **Gemini** | Antigravity CLI + Antigravity IDE (the Gemini CLI's successor), Jules |
| **Open source** | OpenCode, Cline, Continue, Aider and other clients over Ollama / vLLM / an OpenAI-compatible endpoint |

`roadmodel-update` already keeps the *roadmap commands*, the *roadmodel MCP
server* and the *reasoning-effort default* in parity across every agent it
detects — see [After the sync](#after-the-sync). This document covers
everything it cannot: your own instructions, memory, skills and permissions.

---

## The surface map

Every row is a thing an agent knows. Find your SOURCE column, find your TARGET
column, apply the mechanism.

| Surface | Claude | Codex | Gemini (Antigravity) | Open source |
| --- | --- | --- | --- | --- |
| **Project instructions** | `CLAUDE.md` (falls back to `AGENTS.md`) | `AGENTS.md`, or any name in `project_doc_fallback_filenames` | `AGENTS.md` / `GEMINI.md` | `AGENTS.md` (OpenCode, Cline, Aider all read it) |
| **User instructions** | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `~/.gemini/GEMINI.md` | client-specific; usually a global rules file |
| **Memory** | auto-memory: `~/.claude/projects/<slug>/memory/*.md` + `MEMORY.md` | `features.memories` → `~/.codex/memories` | agent memories / `GEMINI.md` | usually none — fold into the instructions file |
| **Skills** (model-invocable) | `~/.claude/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` | plugin/extension skills | `~/.agents/skills` where supported |
| **Slash commands** (you type them) | `~/.claude/commands/<name>.md` → `/name` | `~/.codex/prompts/<name>.md` → `/prompts:name` | `~/.gemini/commands/<name>.toml` → `/name` | OpenCode `~/.config/opencode/commands/<name>.md` → `/name`; VS Code chat `<user>/prompts/<name>.prompt.md` → `/name` |
| **MCP servers** | `~/.claude.json` → `mcpServers` (or `claude mcp add`) | `[mcp_servers.<id>]` in `~/.codex/config.toml` | `mcpServers` in `~/.gemini/settings.json` | `mcpServers` in the client's JSON config |
| **Model** | `settings.json` → `model` | `config.toml` → `model` | client setting | client setting / `ROADMODEL_MODEL`-style env |
| **Reasoning effort** | `effortLevel` (low…max), `maxEffortLevel` as a ceiling | `model_reasoning_effort` (minimal…xhigh), `plan_mode_reasoning_effort` | thinking level | `reasoning_effort` where the endpoint exposes it |
| **Permissions** | `permissions`, `defaultMode` | `approval_policy`, `sandbox_mode` | approval setting | client setting |
| **Hooks / subagents / statusline / plugins** | yes | partial (hooks: no; subagents: yes) | partial | varies |

Three rules that save work in every direction:

1. **Prefer reading over copying.** Codex's `project_doc_fallback_filenames =
   ["CLAUDE.md"]` makes it read `CLAUDE.md` directly; most other agents read
   `AGENTS.md`. A repo that carries one file plus a one-line pointer in the
   other never drifts. Copy only what cannot be pointed at.
2. **Mirror the intent of a setting, not its letter.** Ladders differ (Claude
   has `max` above `xhigh`; Codex stops at `xhigh`). Mirror the *calibrated
   default*, never a ceiling.
3. **Name what has no equivalent** instead of approximating it. An operator who
   thinks a hook still runs is worse off than one who knows it does not.

---

## The prompt

Fill in the two names and paste the block into the TARGET agent, in the project
you want synced. It works in either direction and for any pair in the table.

> **SOURCE** = the agent that is already configured the way you like.
> **TARGET** = the agent you are pasting this into.

```text
You are <TARGET>. Bring yourself to parity with <SOURCE> on this machine and in
this project, so I can switch to you — when <SOURCE>'s usage pool is exhausted,
when its provider is down, or when a task suits you better — and keep working
with the same instructions, memory, commands and tools.

Use docs/agent-parity.md in the roadmodel repo as the surface map if you can
read it; otherwise use your own knowledge of both agents' config layouts.

Work in this order, and SHOW me each diff before you apply it. Do not invent
settings I do not already have in <SOURCE>; where something has no equivalent
in you, say so explicitly rather than approximating it.

STEP 1 — Inventory <SOURCE> (read-only).
Find, for this project and for my user account: its project instructions file,
its user instructions file, its memory store, its skills, its slash commands,
its MCP server registrations, and its model / reasoning-effort / permission
settings. Print a table of what exists, where, and which surfaces I have not
configured at all. Flag every surface you have no equivalent for.

STEP 2 — Instructions, by reference where possible.
If you can be pointed at <SOURCE>'s instructions file (a fallback-filenames
setting, a symlink, or an include), do that instead of copying. Otherwise
create your own instructions file whose FIRST line names the file it was
copied from and the date, so the duplication is visible. If a project-level
and a user-level instructions file both exist, mirror both.

STEP 3 — Memory.
Enable your own memory store if you have one. Import what <SOURCE> already
knows about this project: read its memory index and the entries it points to,
and write their CONTENT (not the file list) into your instructions file under a
heading "## Imported from <SOURCE> memory (<today's date>)", collapsing
duplicates and dropping anything that is only about <SOURCE>'s own UI. Keep it
under ~150 lines — durable facts, not a transcript.

STEP 4 — Skills and slash commands.
For every skill and every slash command <SOURCE> has that you lack, create the
equivalent in your own format, preserving the name so I type the same thing in
both agents. Where your format has no argument placeholder, replace the
placeholder with a sentence saying the arguments arrive as the text after the
command. Do NOT touch anything `roadmodel-update` manages (roadmap-project,
roadmap-phase, roadmap-step, roadmodel-update) — it regenerates those for every
agent and would overwrite your edits.

STEP 5 — MCP servers.
For each MCP server registered in <SOURCE> that you lack, add the equivalent
entry in your own config: stdio servers map command/args/env directly, HTTP
servers use a url. Keep any env-var indirection exactly as it is — never copy a
secret into a config file. List anything you skipped and why.

STEP 6 — Model, effort and permissions, calibrated.
Mirror the INTENT: the same class of model (frontier ↔ frontier, coding-
specialised ↔ coding-specialised), the same calibrated reasoning effort
remembering the ladders differ, and the same permission / sandbox posture. If
<SOURCE> pins a ceiling rather than a default, mirror the DEFAULT. Print the
before/after of every key you change.

STEP 7 — Verify and report.
Restart yourself if needed, then confirm out loud: which instructions file you
are actually reading here; how many skills and slash commands you can see, and
that the four roadmap-* ones are among them; which MCP servers connected and
which failed; and your active model, reasoning effort and permission posture.
Finish with the list of <SOURCE> features you have NO equivalent for, so I know
exactly what I lose by switching to you.
```

### Run it with

Ask roadmodel: `roadmodel score --category agentic --complexity medium` ranks
the models you can actually reach for this task. It is a bounded, well-specified
config task — a mid-tier model at a moderate reasoning effort is the right call,
and the frontier model is not worth its pool draw here. Raise one rung if the
SOURCE agent has an unusual setup (many hooks, many MCP servers, a large
memory store).

---

## After the sync

`roadmodel-update` (`/roadmodel-update`, or
`python scripts/update_projects.py`) keeps three things in parity on every run,
for every agent it detects — Claude Code, Codex, Gemini, Cursor, OpenCode and
the VS Code chat panel:

- **The roadmap commands**, generated from one Claude Code source into each
  agent's own format, so `/roadmap-phase 1` means the same thing everywhere.
  Codex spells it `/prompts:roadmap-phase 1`, because that is how Codex
  addresses a prompt file; everywhere else it is `/roadmap-phase 1`.
- **The roadmodel MCP server**, mirrored from your Claude registration into
  Codex's `config.toml`, Gemini's `settings.json` and OpenCode's config — so
  every agent gets `recommend_model`, `score_candidates`, `read_catalog` and
  `generate_phase_roadmap`, launched exactly the way Claude launches it
  (including any wrapper script that injects provider keys).
- **The reasoning-effort default**, calibrated. A default pinned to the top
  rung (`effortLevel: max`, `model_reasoning_effort: xhigh`) is a standing cost
  on every provider that meters a usage pool, and it is the single easiest way
  to exhaust one mid-week. The updater steps a pinned top rung down to the
  calibrated default and leaves any deliberate lower value — and any *ceiling*
  — alone. Opt out with `--no-calibrate`.

What still needs the prompt above: your own `CLAUDE.md` / `AGENTS.md`, your
memory, your own skills and commands, and your permission posture. Re-run the
memory step when the project's memory index changes materially.
