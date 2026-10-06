# Shared rules and memory across coding agents

`roadmodel-upgrade` maintains shared project context so you can move between
Claude Code, Codex, Antigravity, and OpenCode without repeatedly copying
instructions or summarizing Claude's memory. Run it once on each machine to
install the setup; subsequent sessions read the same live files.

| Task | Codex | Claude Code, Antigravity, OpenCode |
| --- | --- | --- |
| Upgrade tools and repair shared context | `$roadmodel-upgrade` | `/roadmodel-upgrade` |
| Repair context without package upgrades or AI calls | `$roadmodel-upgrade --sync-only` | `/roadmodel-upgrade --sync-only` |
| Check context without changing files | `$roadmodel-upgrade --check` | `/roadmodel-upgrade --check` |
| Upgrade while skipping roadmap agents for this run | `$roadmodel-upgrade --skip-roadmap-refresh` | `/roadmodel-upgrade --skip-roadmap-refresh` |

The agent runs the updater; you do not need to switch to a terminal. Existing
Codex custom prompts also support `/prompts:roadmodel-upgrade`, but the skill
form is preferred. `/roadmap-refresh` updates roadmap bookkeeping and upcoming
model settings; it does not synchronize instructions or memories.

## What is shared

| Surface | Authoritative source | How another agent uses it |
| --- | --- | --- |
| Global rules | Coordinator's `~/.claude/CLAUDE.md` when fleet replication is configured; otherwise each machine's own file | Managed global adapters read the live local source; scoped `~/.claude/rules/` remain applicable on their machine |
| Project rules | Existing `AGENTS.md`, Claude instruction files, and scoped rules | Private client adapters read applicable originals and the shared context protocol |
| Durable project memory | `.roadmodel/memory/`, or an existing explicitly configured Claude memory directory | Every agent reads the full index and relevant detailed entries and writes decisions to this same store |
| Work in progress | `.roadmodel/HANDOFF.md` | Agents preserve the objective, unfinished work, checks, and next action before a handoff |
| Actual checkout state | `.roadmodel/WORKTREE.md` | Session check records the branch, HEAD, working changes, recent commits, and roadmap locations |
| Context inventory | `.roadmodel/context.json` | Lists every memory file and hashes, rule hashes, and source locations |

The default migration preserves every file from Claude's former memory
directory, verifies its contents, keeps a complete backup beside that store,
and redirects the former location to the shared directory. It uses a symlink
on macOS/Linux and a junction on Windows. Claude's local
`autoMemoryDirectory` setting also points at the shared store. An existing
custom memory directory stays authoritative and is exposed through the
project's `.roadmodel/memory/` path. Worktrees share the main checkout's memory;
their handoff and checkout snapshot remain local to each worktree.

This replaces the capped `.agents/memory.md` export. There is no limit that
drops older detailed memories: the manifest includes entries that are absent
from `MEMORY.md` too. The old generated export becomes a pointer; a handwritten
export is preserved. Agents load relevant details as needed rather than
putting every memory body into the initial instruction prompt.

Private memory, handoffs, manifests, client adapters, the session helper, and
Claude local settings are excluded using the repository's local Git
exclusions. The updater reports already tracked private context as an error
instead of silently treating it as private. It leaves tracked project
`AGENTS.md` and `CLAUDE.md` unchanged, so context setup can run while a feature
branch has work in progress.

## How instructions stay current

The project adapters are private files with marked sections; independent
user text in them is preserved:

| Client | Project entry point |
| --- | --- |
| Codex | `AGENTS.override.md`, which directs the agent to read the full existing `AGENTS.md` and applicable Claude files |
| Claude Code | `CLAUDE.local.md`, importing existing `AGENTS.md` and `.agents/shared-context.md` |
| Antigravity | `.agents/rules/roadmodel-context.md`, with `trigger: always_on` |
| OpenCode | Its global adapter explicitly loads `.agents/shared-context.md` and the project's live context; original rules keep their normal entry point |

The shared protocol requires reading applicable ancestor and directory
instructions and preserving the `paths` scope of modular Claude rules when
working in subdirectories. A short Codex adapter keeps startup instructions
within the client's prompt budget; large original instruction files are
read explicitly in full rather than being silently truncated at discovery.

Global Claude instructions remain the live source. Codex's adapter lives in
`~/.codex/AGENTS.md`, or the effective `AGENTS.override.md` when one exists.
Antigravity uses `~/.gemini/GEMINI.md` with its native
`@[Shared global rules](~/.claude/CLAUDE.md)` include. OpenCode uses
`~/.config/opencode/AGENTS.md`. An exact duplicate global copy can be replaced
with an adapter after preserving a backup; distinct client instructions stay
outside the managed block.

Codex and OpenCode adapters explicitly instruct the agent to read the source;
a Markdown reference does not itself inline the file. Global modular rules
are read with their scopes intact. Missing or unreadable sources are reported.
The instructions require rechecking changed sources at new tasks and after
compaction. Start a fresh client session after installing or changing the
adapters, and verify the files the agent actually read. A successful file
check does not prove that an already open conversation loaded new rules.

At session start, the project instructions tell the agent to run, from the
repository root:

```text
python .roadmodel/context.py --session
```

The helper performs local checks, refreshes the manifest and checkout
snapshot, and reports the number of complete memory files and a context
revision. It makes no model calls or package upgrades. The agent then reads
the live memory index, relevant entries, and handoff. The helper cannot infer
an unfinished conversation's intent; the agent maintains that narrative in
`HANDOFF.md`.

Writable memory and handoff files live under `.roadmodel/` because clients
such as Codex protect agent configuration directories from routine writes.
The static adapters stay in their client-specific locations. This lets
agents update project memory under normal workspace permissions without
requesting approval for every memory write.

## Multiple machines and automatic upkeep

Each machine has its own `~/.config/roadmodel/projects.txt` registry, installed
updater and companions, credentials, and local schedule. Registry entries are
absolute project paths, optionally followed by an environment override:

```text
/home/developer/code/example-app | venv:.venv
```

On Windows the registry lives under `%USERPROFILE%\.config\roadmodel`, and
project paths can use drive letters. Register each machine's own directories;
running the updater on one machine does not make another machine's filesystem
local.

A coordinator can update named SSH peers through its private
`~/.config/roadmodel/fleet.json`:

```json
{
  "version": 1,
  "global_rules_source": "/home/developer/.claude/CLAUDE.md",
  "peers": {
    "workstation": {
      "host": "workstation-ssh",
      "platform": "windows",
      "python": "C:\\Python313\\python.exe",
      "launcher": "~/.config/roadmodel/update_projects.py",
      "projects": ["D:\\Code\\example-app", "D:\\Code\\example-library"]
    }
  }
}
```

`platform` is `windows` or `posix`; `python` and project paths must be absolute.
`launcher` is optional and defaults to the path shown, expanded on the peer.
`host` is an existing SSH alias or hostname, optionally `user@host`. Peers need
the installed updater and companions, a known SSH host key, and working
noninteractive authentication. The coordinator does not discover machines or
bootstrap remote software. Keep this configuration private and out of Git.

Optional `global_rules_source` is an absolute local path selecting one
authoritative global rules file on the coordinator. Mutating runs replicate
it to `~/.claude/CLAUDE.md` on peers
before their adapters are synchronized. Replication records hashes and refuses
to overwrite divergent remote edits. Edit the coordinator's source for shared
changes; reconcile reported conflicts explicitly. This replicates the named
file, not arbitrary imported files or the entire modular rules directory.
Without this option, global sources remain independent on each machine.

Ordinary upgrades register the peer's listed projects and run its updater.
Every peer invocation includes `--local-only`, so peers never recurse into
their own fleets. Coordinated full upgrades also skip model-backed roadmap
refreshes on peers. `--sync-only` and `--check` carry the same mode to peers;
`--local-only` skips all peers. An unreachable or failed peer produces a named
failure and a nonzero result; other machines still run.

`--sync-only` and `--check` use the installed launcher and companions without
fetching or self-updating. They make no package or model requests. Checks do
not write files or register projects, though configured peers are contacted
over SSH. Add `--local-only` for a fully local check or repair; `--dry-run`
validates and describes fleet actions without connecting to peers.

Install a daily schedule on each machine with `--install-schedule 09:00`:
launchd on macOS, Task Scheduler on Windows, and cron on Linux. Schedules use
the installed launcher and append to `~/.config/roadmodel/update.log`.
Windows catches a missed start when the machine returns. A coordinator's
schedule can also reach its configured peers; each machine's own schedule
provides upkeep when the coordinator is unavailable. Choose times that avoid
overlapping runs. A machine lock prevents simultaneous upgrades; a busy run
reports a failure so it can be retried. The schedule's normal full upgrade follows published
roadmodel releases and refreshes its own launcher and companion modules.

Fleet orchestration does not merge a repository's memory between separate
clones on different machines. If you use the same repository on multiple
machines, synchronize its private memory store separately with conflict
handling. Different projects retain separate project memories.

## Other agent capabilities

A full upgrade continues to distribute the five roadmap command/skill files
and mirror the roadmodel MCP registration into supported clients. It also
retains the existing provider-default behavior: pinned default model and effort
settings are removed unless `--keep-pins` is used; ceilings are retained.
`--sync-only` touches neither runtime model pins nor MCP or permission settings.
Client permissions, hooks, plugins, and unrelated skills keep their native
behavior; copying prose cannot make those mechanisms interchangeable.

Antigravity skill copies are installed in both documented global locations:
`~/.gemini/config/skills/` for the IDE/2.0 client and
`~/.gemini/antigravity-cli/skills/` for the CLI. Both expose a skill as a slash
command; the copies are generated from the same command source.

OpenRouter is an API provider. OpenCode using OpenRouter gets the OpenCode
integration above. Other OpenRouter clients need their own supported
instruction integration; an API endpoint does not discover local files.
Cursor and VS Code receive their supported commands and project guidance, but
this updater does not install their global rule adapters.

Shared files preserve saved rules, durable memories, and written work state.
They do not transfer full chat transcripts, unsaved reasoning, or guarantee
identical model behavior. Verify loaded sources and use a fresh session when
switching clients after configuration changes.
