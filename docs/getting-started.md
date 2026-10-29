# Getting started on one machine or two

From a fresh install to a first roadmap, then kept current without you
running anything. Part 1 is one machine. Part 2 adds a second one, a Mac and
a PC say, and explains when to make one of them the coordinator.

Commands in this page are typed in a Claude Code chat (`/roadmap-project`)
or in a terminal (`pip install …`). Codex, Gemini/Antigravity, Cursor and
OpenCode get the same commands; see [agent-parity.md](agent-parity.md) for
how each one spells them.

## Part 1 — one machine

### 1. Install roadmodel and its chat commands

Python 3.11 or newer (on Windows, type `py -3` where this page says
`python3`):

```sh
python3 -m pip install --upgrade roadmodel
python3 -m roadmodel.update_projects --commands-only --local-only
```

The second line installs the five chat commands (`/roadmap-project`,
`/roadmap-phase`, `/roadmap-step`, `/roadmap-refresh`, `/roadmodel-upgrade`)
for every agent it finds. Reload the editor window afterwards (VS Code:
`Developer: Reload Window`), then type `/` in a chat to see them.

### 2. Describe what you can use: `user-context.md`

```sh
roadmodel context init        # creates ~/.config/roadmodel/user-context.md
```

Open that file and fill it in: your subscriptions (Claude, ChatGPT, Google AI
and so on), any API keys you hold, which platforms you prefer, your budget
posture, and any local Ollama models. Every model pick reads it, so a pick
never names something you cannot run. The fields are explained in
[user-context-setup.md](user-context-setup.md).

Keep it current by hand: add or remove a subscription when that changes,
mark a usage pool `tight` or `exhausted` when it runs low. Picks read the file
live, and each project's `planning/` copy follows on the next upgrade.

### 3. Optional: the MCP server

```sh
python3 -m pip install "roadmodel[mcp]"
roadmodel setup-mcp
```

This lets your agent call roadmodel directly (the Settings ladder, candidate
scores, the catalog) instead of running the CLI. One registration serves every
project on the machine. The roadmap commands work without it. Tools:
[mcp-tools.md](mcp-tools.md).

### 4. Register your projects and turn on the automatic upkeep

In a Claude Code chat, once:

```
/roadmodel-upgrade ~/code/app-one ~/code/app-two
/roadmodel-upgrade --install-schedule 09:00
/roadmodel-upgrade --install-sync-schedule
```

- The first registers the projects and upgrades roadmodel in each one's own
  environment.
- The second runs that upgrade every day.
- The third pulls merged changes into each checkout every 15 minutes, so a
  roadmap updated on GitHub is what your editor shows.

From now on, nothing needs running by hand. `/roadmodel-upgrade` alone
upgrades every registered project on demand, and `/roadmodel-upgrade
--refresh-roadmaps` also brings every project's roadmaps current (below).

### 5. Write a project's roadmap

roadmodel does not invent a project. **You give it a brief**: what you want
the project to become. Open a new chat in the project's folder:

```
/roadmap-project docs/brief.md notes.txt
/roadmap-project "A CLI that reconciles bank exports into a ledger. Python, no paid services, v1 by March."
/roadmap-project
```

- Name files (Markdown, plain text, PDF or Word), describe it in quotes, or
  both.
- With nothing, it asks what the project is for, what done looks like, your
  hard constraints, and whether a document already describes it. Then it
  waits for your answer.
- It also reads the code that already exists.

It writes `docs/roadmap/ROADMAP.md`: the phases, their acceptance criteria,
the security, release and operations strategy, and the model that should
write each phase's roadmap. Read it and change what you disagree with. Then,
each in a new chat:

```
/roadmap-phase 1        # Phase 1 broken into steps: docs/roadmap/phase01-roadmap.md
/roadmap-step 1 1       # does Step 1: branch → work → PR → merge
```

Each step names the model and settings to run it with. The full loop is in
[planning-workflow.md](planning-workflow.md).

### What keeps itself current

| What | How | You |
| --- | --- | --- |
| roadmodel in every project | the daily `/roadmodel-upgrade` run | nothing |
| the chat commands, the MCP server, `planning/` kits | the same run | nothing |
| checkouts on `main` | the 15-minute sync | nothing |
| roadmaps (shipped steps marked ✅, upcoming Settings re-picked) | automatically when roadmodel's roadmap rules change; `/roadmodel-upgrade --refresh-roadmaps` when you want it now | nothing, or one command |
| what you can use | `~/.config/roadmodel/user-context.md` | edit it when it changes |

A refresh never runs a step and never touches a project with work in flight:
another branch checked out, uncommitted edits, or an open step PR. It retries
that project later.

## Part 2 — two machines

Do Part 1, steps 1 to 4, on **both** machines, each registering the projects
that live on it. Then settle two things.

### Your `user-context.md`: one copy you edit, the other receives it

Pick the machine you will edit it on (the *source*). Publish it to a
**private** GitHub repo from there, and have the other machine pull it before
every upgrade:

```
# on the source machine, once
/roadmodel-upgrade --context-sync <you>/roadmodel-context --context-source ~/.config/roadmodel/user-context.md

# on the other machine, once
/roadmodel-upgrade --context-sync <you>/roadmodel-context
```

Create the repo first (`gh repo create <you>/roadmodel-context --private`).
After that, every daily run publishes from the source and pulls on the other
machine. Edit only on the source. Details and alternatives:
[user-context-setup.md](user-context-setup.md#keeping-it-the-same-on-every-machine).

### Who looks after which machine: independent, or a coordinator

**Independent (the default).** Each machine runs its own daily upgrade, its
own checkout sync and its own roadmap refreshes, for its own projects.
Nothing connects them except the shared `user-context.md`. Choose this when:

- each machine has its own projects, and
- unattended Claude Code sessions on each machine can push and open PRs
  (roadmap refreshes need to).

**A coordinator.** One machine (the *coordinator*) also looks after the other
(the *peer*) over SSH. Its daily run upgrades the peer, can copy one global
rules file to it, and refreshes the peer's projects' roadmaps itself, in
clones of their GitHub remotes. Choose this when:

- unattended sessions on the peer cannot push (Claude Code's auto mode can
  refuse a `git push` on one machine and allow it on another), or
- you want one report, from one machine, covering both.

To set one up:

1. On the peer, do Part 1, steps 1 and 4, and run `/roadmodel-upgrade` once.
   That installs the updater the coordinator will call.
2. Make sure the coordinator can `ssh` to the peer without a password (a key,
   and the peer's host key already accepted) and that `gh` is signed in on
   the coordinator: it opens the peer projects' refresh PRs.
3. On the coordinator, describe the peer in `~/.config/roadmodel/fleet.json`.
   The format, with a worked example, is in
   [agent-parity.md](agent-parity.md). Keep this file private.
4. On the peer, reinstall its schedule so it leaves roadmaps to the
   coordinator, at a time after the coordinator's run:

   ```
   /roadmodel-upgrade --install-schedule 09:30 --keep-pins --skip-roadmap-refresh
   ```

   The peer still needs its own daily run. Some environments cannot be started
   from an SSH session (on Windows, a uv venv whose base Python is a
   junction), and its own run, in your logged-in session, upgrades them.

Then the coordinator's `/roadmodel-upgrade --refresh-roadmaps` refreshes the
roadmaps of every project on both machines, and its daily run does the same
whenever the roadmap rules change. The peer's checkout sync brings each
merged refresh into its checkouts within 15 minutes.

## Where things live

| Path | What it is | In Git? |
| --- | --- | --- |
| `~/.config/roadmodel/user-context.md` | what you can use | never in a public repo |
| `~/.config/roadmodel/projects.txt` | the projects this machine looks after | no |
| `~/.config/roadmodel/fleet.json` | the coordinator's peers | no |
| `~/.config/roadmodel/update.log`, `refresh-logs/` | what the daily runs did | no |
| `<project>/planning/` | the kit: templates, the selector, a copy of your user-context | the kit yes, the user-context copy no |
| `<project>/docs/roadmap/` | `ROADMAP.md` and each `phaseNN-roadmap.md` | yes |
