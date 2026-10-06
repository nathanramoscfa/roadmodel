---
description: Upgrade roadmodel and shared agent context across registered projects and configured machines (usage: /roadmodel-upgrade [project dirs to register…] [--sync-only | --check] [--local-only] [--skip-roadmap-refresh] [--refresh-roadmaps] [--install-schedule HH:MM])
---
Upgrade roadmodel in every registered project's own environment, refresh its
`planning/` kit and agent commands, and maintain live shared rules, full
project memory, and handoff records. Include explicitly configured SSH peers
unless `--local-only` is given. The operator should not have to open a
terminal — you run everything.

Invocation authorizes updates to registered projects and configured peers;
do not ask again to apply routine repairs. Preserve independent instruction
text, existing settings outside the managed changes, and all memory bodies.
This command does not pull Git history or execute roadmap steps. Roadmap
bookkeeping runs only under the existing refresh behavior described below.

## 1. Select the mode before fetching anything

Parse "$ARGUMENTS" first. In Codex this command is normally the skill
`$roadmodel-upgrade`; `/prompts:roadmodel-upgrade` is the legacy prompt form.

| Mode | Action |
| --- | --- |
| Default | Upgrade packages, kits, commands/runtime, and shared context, then configured peers |
| `--sync-only` | Repair rules, full memory, and handoff setup using installed code; no package upgrades, command downloads, or AI calls |
| `--check` | Verify shared context and configured peers without writes, logging, registration, or self-update |
| `--local-only` | Skip fleet peers in any mode |
| `--skip-roadmap-refresh` | Skip roadmap agents for this full upgrade without changing the saved automatic-refresh preference |
| `--dry-run` | Describe the plan without changes or peer connections |

For `--sync-only`, `--check`, or `--dry-run`, invoke the **installed launcher**
at `~/.config/roadmodel/update_projects.py` directly. Do not download or replace
the launcher first: repair/check must work offline, and a check must not write.
Its companion modules must already be installed. If the launcher or companions
are missing, report that a full upgrade is required; do not silently turn a
check into an installation. These modes do not fetch packages or invoke a
model. Configured peers still use SSH unless `--local-only` is supplied.

For a full upgrade, fetch the launcher to that location (Windows:
`%USERPROFILE%\.config\roadmodel\update_projects.py`), creating the directory
if needed:

`https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main/scripts/update_projects.py`

Use an available downloader such as `curl -fsSL … -o …`, `curl.exe`, or
Python's `urllib.request`. Run it with the machine's default `python`,
`python3`, or `py -3` on Windows. The launcher is stdlib-only, Python 3.9+.
On a full run it upgrades roadmodel in its dedicated
`~/.config/roadmodel/venv`, replaces the launcher and companion modules from
the published wheel, and hands over to that release. The package requires
Python 3.11+; the updater can find a suitable registered project's interpreter.
This uses roadmodel's normal signed-tag/provenance release channel; it is not
a claim that the launcher independently verifies artifact signatures.

## 2. Resolve the registry and fleet

The local registry is `~/.config/roadmodel/projects.txt`: one project dir per
line, `#` comments, optional env override `<dir> | conda:<name>` or
`<dir> | venv:<subdir>`.

- Pass options and their values through to the script, including
  `--install-schedule 09:00`, `--jobs 8`, and `--dry-run`.
- In a mutating run, project-directory arguments become `--add <dir> …`.
  In `--check`, pass directories positionally so checking never changes the
  registry. With no directories, use the existing registry.
- If the registry is missing or empty and no directories were given, locate
  previously specified projects in their known code roots. Ask only for
  information that is still missing; do not ask to reconfirm known paths.
- Read `~/.config/roadmodel/fleet.json` when present. It is private local
  configuration; never commit machine addresses or private project lists.

The fleet schema is an object with `"version": 1` and a `"peers"` object keyed
by machine name. Each peer has `host` (SSH alias/hostname), `platform`
(`windows` or `posix`), an absolute `python` executable, and a nonempty
`projects` list of absolute paths. Optional `launcher` defaults to
`~/.config/roadmodel/update_projects.py`, expanded on the remote machine.
Optional top-level `global_rules_source` is the absolute local path of the
coordinator's authoritative global rules file for replication to peers'
`~/.claude/CLAUDE.md`; changed
remote copies are protected by a hash conflict check. See
`docs/agent-parity.md` for an example. Peers require an installed updater
with its companions, known SSH host keys, and noninteractive authentication.
This command does not discover or bootstrap unconfigured machines.

## 3. Run and verify shared context

```text
python ~/.config/roadmodel/update_projects.py [--add <dir> …] [--jobs N]
```

Context repair runs independently of whether a project's package environment
is healthy. It leaves tracked `AGENTS.md` and `CLAUDE.md` unchanged and installs
private, Git-excluded adapters: `AGENTS.override.md` for Codex,
`CLAUDE.local.md` imports for Claude, and an always-on rule for Antigravity.
Their shared protocol lives in `.agents/shared-context.md`. Existing
independent adapter text is preserved; agents read original project rules in
full and preserve scoped rules. Global Claude rules remain the live source;
Codex, Antigravity/Gemini, and OpenCode get adapters to it. Exact duplicate
global copies are backed up before conversion.

All detailed Claude memory files are retained. The default legacy store is
backed up and redirected to `.roadmodel/memory/`; a custom memory location stays
authoritative. Claude's local setting and the other agents reference the same
store. Worktrees share memory with the main checkout. Private context files
are Git-excluded; tracked personal context, conflicting files, changed
redirects, and unreadable sources are reported as failures.

The updater installs `.roadmodel/context.py`, `.roadmodel/context.json`,
`.roadmodel/HANDOFF.md`, and `.roadmodel/WORKTREE.md`. Existing handoff text is
preserved; the checkout snapshot is refreshed. Project instructions tell each
agent to run `python .roadmodel/context.py --session` from the repository root,
then read the live memory index, relevant entries, and handoff. Agents write
new durable decisions to the shared store and maintain the handoff before
ending or switching. The helper makes no model calls or package upgrades.
Writable state lives in `.roadmodel/`, within ordinary workspace permissions,
while static client adapters remain in their protected configuration paths.

This shares saved rules, memories, and written work state; it does not import
full conversation transcripts or guarantee identical model behavior. Check
which sources the agent actually read. Fresh sessions are needed after
instruction changes; existing conversations may retain earlier instructions.

## 4. Full upgrade behavior

A full run detects each project's env (`.venv`/`venv`/`env` dir →
`environment.yml` name → conda env named like the folder → conda env inside
the project), upgrades `roadmodel` concurrently, then upgrades `roadmodel[mcp]`
in the env behind Claude Code's roadmodel MCP registration. The
`MCP server env:` line reports it; restart sessions to load a new server.

It re-exports `planning/` where one exists (`--init-kit` creates one everywhere)
and refreshes the five commands for detected agents: Claude commands and skill
copies, legacy Gemini TOML commands, Antigravity skills under
`~/.gemini/config/skills/` (IDE/2.0) and
`~/.gemini/antigravity-cli/skills/` (CLI), shared Codex/Cursor skills under `~/.agents/skills/`,
Codex prompt compatibility files, OpenCode commands, and VS Code prompt files.
`--agents claude,gemini,antigravity,codex,cursor,opencode,vscode` overrides
detection. Runtime synchronization retains the existing roadmodel MCP and
provider-default behavior; use `--keep-pins` to retain pinned model/effort
defaults. Context-only repair does not change these runtime settings.

`--commands-only` refreshes commands and existing runtime/user-context
integration; it does not synchronize project memory or run the fleet.
It is insufficient for an agent handoff. `--no-parity` skips local shared
context during a full upgrade; use only when explicitly requested.

At the end, configured peers run their installed updater. Every remote run
has `--local-only` to prevent recursive fleet updates. Full coordinated
upgrades use `--skip-roadmap-refresh` on peers; repair/check propagate their
own mode. Mutating peer runs register listed paths and append to the remote
update log. Checks neither register paths nor request logging. Named peer
failures affect the exit status; inspect that peer's local log or local check
for details. Fleet operations can replicate the configured global rules file;
they do not merge project memory between machines.

## 5. Unattended runs (once per machine)

`--install-schedule [HH:MM]` registers a daily run for this user, default
09:00: launchd on macOS, Task Scheduler on Windows, and cron on Linux.
It runs the installed launcher with `--log`, appending to
`~/.config/roadmodel/update.log`. Each full run follows published releases
and refreshes the launcher and companion modules, so repeated manual fetching
is unnecessary. On Windows a start missed while the PC was off runs once it
is back. `--uninstall-schedule` removes it.

Install a schedule on each machine; a coordinator can additionally update its
configured peers. Keep the machines' run times from overlapping. Schedules
and registries are local; installing one schedule does not install another
on a peer. When the operator has requested automatic upkeep, install and
verify it within that authorization.

## 6. Refresh every project's roadmaps

`--refresh-roadmaps` runs `/roadmap-refresh` in every registered project on
this machine after the upgrade, concurrently (`--refresh-jobs N`, default 3). Each runs as
Claude Code headless (`claude -p`) in a fresh clone of the project, so the
operator's checkout is never touched. The unattended session asks nothing, settles unverified
steps from cited evidence, runs static checks only, leaves other PRs alone,
and uses Claude Code's `auto` permission mode. It takes its PR through CI to
a merge. Projects with git-excluded roadmaps (`private/`) are refreshed in place.

A project where work may be in flight is skipped and named: another checked-out
branch, uncommitted edits outside `planning/`, a roadmap not yet committed,
or an open PR from a branch its roadmaps name.

The daily full run does the same automatically when the roadmap rules change:
the `/roadmap-refresh` or `/roadmap-step` command, or roadmap templates and
prompts. Catalog-only releases do not trigger it; step execution rechecks
Settings. Skipped projects are retried on a later run. `--auto-refresh off`
disables this automatic behavior on the machine; `--auto-refresh on` restores
it. Logs live in `~/.config/roadmodel/refresh-logs/`.

For a tool/context upgrade while Claude is unavailable, use
`--skip-roadmap-refresh`; it preserves the saved preference. It conflicts
with `--refresh-roadmaps`. `--sync-only` and `--check` never run roadmap agents
and cannot be combined with refresh, command-only, or schedule operations.

## 7. Report

Show the result table and shared-context/fleet status. If the first line reads
`*** self-update FAILED`, include the reason: the run used its local copy,
which may be stale. Explain every failed project or peer; do not report the
whole fleet as ready when any member failed. For `no env found`, inspect its
environment and add a supported override when identifiable. For pip failures,
show the relevant last lines and diagnosis. Memory or rule failures need
their exact source path; never claim successful loading from file existence.

If a `Roadmap refresh:` section appears, include merged PR links, skipped
reasons, or the log path for work needing attention. If commands changed,
reload the editor (`Developer: Reload Window`). If rules changed, start fresh
agent sessions and verify loaded sources. Report installed schedules and log
paths. Registries, fleet configuration, updater state, schedules, and private
context stay local; the updater makes no Git commits.
