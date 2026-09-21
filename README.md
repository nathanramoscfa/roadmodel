# roadmodel

A BYO-key command-line tool that recommends **which AI model on which
platform with which settings** for a given prompt. Point it at a task
description, and it returns a labeled block — `MODEL / BACKUP /
PLATFORM / CONVERSATION / RATIONALE`, plus the setting fields the
chosen platform actually exposes — grounded in a
bundled benchmark and pricing catalog (Cursor pricing, Artificial
Analysis, LiveCodeBench, τ²-bench, SWE-bench, MMMU, LMArena) and
filtered against your own subscriptions and API keys. Built for
developers who use several AI subscriptions (Claude Code, Cursor,
Codex / ChatGPT, raw provider APIs) and want a deterministic answer
to "what should I use for this?" instead of guessing. The same
answer drives a **project-agnostic planning workflow** — roadmap →
phase roadmaps → one step per AI conversation, each with its own
model, branch, PR, and a completion that means done — described in
[The planning workflow](#the-planning-workflow) below.

The same package ships three surfaces, all reading one bundled catalog:

| Surface | What it is | Entry point |
| --- | --- | --- |
| **CLI** | BYO-key recommender: prompt in, `MODEL / PLATFORM / settings` block out | `roadmodel recommend` |
| **MCP server** | The same recommender (plus the catalog and a roadmap generator) exposed as tools to any MCP client — Claude Code, Cursor, Claude Desktop | `roadmodel-mcp` / `roadmodel setup-mcp` |
| **Planning kit** | Project- and phase-roadmap templates with a per-step model recommendation and an enforced step lifecycle, run by the AI already open in your editor at $0 marginal cost | `roadmodel export-kit` + the `/roadmap-*` commands |

[![PyPI version](https://img.shields.io/pypi/v/roadmodel.svg)](https://pypi.org/project/roadmodel/)
[![Python versions](https://img.shields.io/pypi/pyversions/roadmodel.svg)](https://pypi.org/project/roadmodel/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/nathanramoscfa/roadmodel/actions/workflows/tests.yml/badge.svg)](https://github.com/nathanramoscfa/roadmodel/actions/workflows/tests.yml)
[![Phase verify](https://github.com/nathanramoscfa/roadmodel/actions/workflows/phase-verify.yml/badge.svg)](https://github.com/nathanramoscfa/roadmodel/actions/workflows/phase-verify.yml)

## The planning workflow

roadmodel's second job is a **repeatable loop for running a project
with AI coding agents**, in which the recommender is the step that
picks the model. The loop is the same in every repo, in every
language, on every machine where the commands are installed:

```
/roadmap-project        ROADMAP.md — phases, acceptance criteria, and
                        the security / release / operations strategy
/roadmap-phase 1        docs/phase01-roadmap.md — Phase 1 broken into
                        steps; each names its branch, its model and
                        settings, and carries a <task> prompt
/roadmap-step 1 1       a NEW chat runs Step 1: branch → work → PR →
/roadmap-step 1 2       merge → "Step 1 is complete." One step per
…                       conversation; no work straddles two steps
```

What the loop guarantees, independent of the project:

- **One step, one conversation, one PR.** A step is the unit of work
  an agent can finish and a human can review. Its `<task>` block
  carries a six-stage lifecycle — branch, work behind a security
  gate, PR, green checks + squash-merge, retire the branch, declare —
  that the agent must complete before it may call the step done.
- **The model is chosen per step, not per project.** Each step's
  Settings table (model, platform, effort, thinking) comes from
  running the bundled selector against your own subscriptions and
  keys — by the AI already open in your editor, at $0 marginal cost.
- **"Done" means done.** A step ends with "Step N is complete. You
  can now move on to Step N+1." and nothing after it. Every finding
  the step surfaced has already been dispatched — roadmap edited,
  issue opened, note in the PR body — or the agent says the step is
  NOT complete and names what is outstanding.
- **The roadmap on `main` is the ledger.** The step's own PR flips
  its `**Status:**` line to `Complete — PR #n`, so progress is
  recorded exactly when the work merges, and the next step refuses
  to start until the previous one reads Complete.
- **Security, release, and operations are per-step gates, not a
  final phase.** Every step runs the same pre-commit security gate,
  and a step that touches a deployed surface is done at post-deploy
  verification, not at merge.

Setup is once per machine (`/roadmodel-update` keeps every project's
copy current after that); the commands then work in any project.
Step-by-step: [docs/planning-workflow.md](docs/planning-workflow.md).

## Install

```sh
pip install roadmodel
```

Python 3.11 or newer.

## Staying current

roadmodel's benchmark and pricing catalog — and the planning templates — are
**bundled inside the installed wheel**. The CLI, MCP server, and planning kit
all read that offline copy, so they only know about the models and the
template rules that shipped with the version you have. New models, price
changes, availability edits, and template changes land upstream (a daily job
keeps the catalog current) and reach you when a **new release ships them**.

### One environment

```sh
pip install -U roadmodel
```

- **CLI** — the next `roadmodel recommend` uses the fresh catalog. Confirm with
  `roadmodel version`; inspect with `roadmodel catalog show`.
- **MCP server** — upgrade in the environment where `roadmodel-mcp` lives
  (`pip install -U "roadmodel[mcp]"`) and restart the MCP client. Registered
  once at user scope via `roadmodel setup-mcp`, that one environment serves
  every project.
- **Planning kit** — the exported kit is a snapshot at export time, so upgrade
  **then** `roadmodel export-kit . --force` to refresh it. The `/roadmap-project`
  and `/roadmap-phase` commands do both as their Step 0.

### Every project on a machine — `/roadmodel-update`

Projects that each carry roadmodel in their **own** conda env or venv would
otherwise be upgraded one at a time. Instead, from any Claude Code chat:

```
/roadmodel-update                       # every registered project
/roadmodel-update ~/code/app-one …      # register these dirs, then run
/roadmodel-update --install-schedule    # once: also run daily, unattended
```

The command fetches [`scripts/update_projects.py`](scripts/update_projects.py)
(stdlib only, Python 3.9+) and runs it. The script reads
`~/.config/roadmodel/projects.txt` — one project dir per line, optional
`| conda:<name>` / `| venv:<dir>` override — detects each project's environment
(a `.venv`/`venv`/`env` dir, the `name:` in `environment.yml`, a conda env named
like the folder, or a conda env inside the project; never `base` by guesswork),
then **concurrently** upgrades `roadmodel` in every one, re-exports `planning/`
where a kit exists, re-downloads the `/roadmap-*` command files, and prints one
table. Same script on Windows, macOS, and Linux; `--install-schedule [HH:MM]`
registers a daily run (Task Scheduler / launchd / cron, logged to
`~/.config/roadmodel/update.log`) so every project follows each release within a
day. Details: [docs/planning-workflow.md §5](docs/planning-workflow.md).

See [CHANGELOG.md](CHANGELOG.md) for what each release changed.

## MCP server

[MCP](https://modelcontextprotocol.io) (Model Context Protocol) is the open
standard that lets an AI client — Claude Code, Cursor, Claude Desktop — call
tools that live in a separate program: the client starts the server as a
subprocess, asks it what tools it has, and calls them by name while you chat.
roadmodel's server turns the recommender into such a tool, so the AI in your
editor can ask "which model for this task?" and get a structured, deterministic
answer instead of guessing.

Install the MCP runtime with `pip install "roadmodel[mcp]"` to enable
the `roadmodel-mcp` stdio server entrypoint; plain `pip install
roadmodel` keeps the SDK optional and does not install `mcp`. The
server exposes three tools — `recommend_model`,
`generate_phase_roadmap`, and `read_catalog` — to any MCP-compatible
client (Cursor, Claude Code, Claude Desktop, VS Code + Continue).
Per-client registration walk-throughs live in
[docs/mcp-setup.md](docs/mcp-setup.md); tool signatures and return
schemas are documented in [docs/mcp-tools.md](docs/mcp-tools.md).

## Planning kit ($0 marginal recommendations)

To author project/phase roadmaps **with per-step model recommendations**
in another project, export the **planning kit** into it and let the AI
already open in your editor (e.g. Claude Code on a flat plan) run the
selector in its own context — no per-call API spend, just the editor
session you already pay for.

**Cross-platform (recommended).** With roadmodel installed, one command
writes the kit on Windows, macOS, or Linux — no shell or network needed:

```sh
cd /path/to/other-project
roadmodel export-kit            # writes ./planning with selector + cost-scale
                                # + templates + HOW-TO-USE + your user-context
```

It uses the catalog **bundled in the installed wheel**, so refresh with
`pip install -U roadmodel` and re-run `roadmodel export-kit` at the start
of each phase. Flags: `--dest <subdir>`, `--force` (overwrite an existing
kit `user-context.md`), `--user-context <path>`.

**Shell alternative (no install).** A bash script fetches the kit fresh
from this repo's `main` branch instead of from an installed wheel:

```sh
scripts/export-planning-kit.sh /path/to/other-project
```

Flags: `--dest <subdir>`, `--ref <git-ref>`, `--local` (copy from a local
checkout instead of GitHub), `--user-context <path>`. On Windows
PowerShell, call `curl.exe` (not the `curl` alias) if you fetch files by
hand; the `export-kit` command above avoids that entirely.

**Day-to-day:** the kit is driven by the four user-scope commands in
`docs/claude-commands/` — `/roadmap-project`, `/roadmap-phase N`,
`/roadmap-step P M`, `/roadmodel-update` — see
[The planning workflow](#the-planning-workflow) above for the loop and
[docs/planning-workflow.md](docs/planning-workflow.md) for setup and
per-command detail. The same four are generated for **Gemini CLI**
(`~/.gemini/commands/*.toml`), **Codex** and **Cursor** (one
`~/.agents/skills/*/SKILL.md` both read; `$roadmap-step` in Codex,
`/roadmap-step` in Cursor), and **OpenCode**
(`~/.config/opencode/commands/*.md`), installed by `/roadmodel-update`
wherever those tools are present.

Either way the in-editor AI runs the algorithm itself rather than calling
the recommender service. Use the MCP server above instead when you want
deterministic, structured recommendations in a script or CI.

## Quickstart

Three steps from a fresh install to a parsed recommendation block.

**1. Export an API key for any one of the three providers.** Anthropic
shown here; OpenAI and Google work the same way — see
[docs/byo-key-setup.md](docs/byo-key-setup.md) for the full guide.

```sh
export ANTHROPIC_API_KEY=sk-ant-...
```

**2. Run `roadmodel recommend` once to bootstrap your user-context
file.** On the first invocation, the CLI writes a copy of the bundled
template to `~/.config/roadmodel/user-context.md` (or
`$XDG_CONFIG_HOME/roadmodel/user-context.md` when `XDG_CONFIG_HOME` is
set), prints a one-line stderr notice telling you what it did, and
exits without calling the provider. Open the file and replace the
`$XXX` and `Yes/No` placeholders with your actual subscription
amounts and API-key state. The full field-by-field walk-through lives
in [docs/user-context-setup.md](docs/user-context-setup.md).

```sh
roadmodel recommend "Refactor auth middleware across 12 files"
# stderr: Created /home/you/.config/roadmodel/user-context.md from
#         bundled template. Edit it with your real subscription
#         state, then re-run.

$EDITOR ~/.config/roadmodel/user-context.md
```

**3. Re-run.** With the user-context filled in, the same command
calls your chosen provider and prints a parsed recommendation block:

```sh
roadmodel recommend "Refactor auth middleware across 12 files"
```

```text
MODEL: claude-opus-4-7
BACKUP: claude-sonnet-5
PLATFORM: Claude Code
EFFORT: High
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Cross-file coding refactor spanning twelve modules.
PICK: Opus 4.7 is S-tier on coding-agent benchmarks and the only
model in the catalog rated S for long-context recall.
EFFORT: High effort with extended thinking on matches the
multi-file blast radius without over-buying the ceiling.
```

The **setting fields are platform-conditional**: a block carries only
the dials the chosen platform actually has. Claude Code exposes an
effort dial and a thinking toggle, so the example emits `EFFORT` and
`THINKING` and no `MAX MODE` line at all — Claude Code has no Max Mode
control, and a dial a surface lacks is omitted rather than reported as
`Off`. Cursor is the inverse: it emits `MAX MODE` and no `EFFORT` /
`THINKING`. `MODEL`, `BACKUP`, `PLATFORM`, `CONVERSATION`, and
`RATIONALE` are always present.

Pass `--json` to emit the same fields as machine-readable JSON, or
`--file PATH` to read the prompt from disk.

## BYO-key setup

roadmodel ships with no provider key built in — it calls
**your** provider account on every recommendation and charges that
account. Set any one of these environment variables and the CLI
auto-selects that provider (the first present, in table order):

| Provider   | Env var              | Engine API        |
| ---------- | -------------------- | ----------------- |
| Anthropic  | `ANTHROPIC_API_KEY`  | native            |
| OpenAI     | `OPENAI_API_KEY`     | native            |
| Google     | `GOOGLE_API_KEY`     | native            |
| DeepSeek   | `DEEPSEEK_API_KEY`   | OpenAI-compatible |
| xAI        | `XAI_API_KEY`        | OpenAI-compatible |
| Groq       | `GROQ_API_KEY`       | OpenAI-compatible |
| Mistral    | `MISTRAL_API_KEY`    | OpenAI-compatible |
| Z.ai       | `ZAI_API_KEY`        | OpenAI-compatible |
| OpenRouter | `OPENROUTER_API_KEY` | OpenAI-compatible (`--model` required) |
| Together   | `TOGETHER_API_KEY`   | OpenAI-compatible (`--model` required) |

Two more are explicit-only (`--provider` / `ROADMODEL_PROVIDER`):
**`ollama`** — a local [Ollama](https://ollama.com) server, no key,
`ROADMODEL_MODEL` (or `--model`) names the pulled model — and
**`custom`** — any other OpenAI-compatible endpoint via
`ROADMODEL_BASE_URL` + `ROADMODEL_API_KEY` + `ROADMODEL_MODEL`
(vLLM, LM Studio, a corporate gateway). The recommender prompt is
~55k tokens, so a local model needs a ≥64k context window.

The full guide — generating keys in each provider's console, storing
them in a shell profile or `~/.config/roadmodel/config.toml`,
precedence rules, verifying with a smoke call, and which engines
have been eval-verified — is
[docs/byo-key-setup.md](docs/byo-key-setup.md).

## User context setup

roadmodel reads a per-user Markdown file describing your active
subscriptions, API keys, platform preference order (and optional
platform allow/deny list), budget posture, and — in its "Local models
(Ollama)" table — which open-weight models you have pulled onto your
own machine, so the `<access-selection>` step can pick a **platform**
(including `Ollama (local)` at $0 per token, or the `OpenRouter`
aggregator when you declare that key) and **the settings that platform
exposes** alongside the model. The resolved default path is
`~/.config/roadmodel/user-context.md` (or
`$XDG_CONFIG_HOME/roadmodel/user-context.md` when `XDG_CONFIG_HOME`
is set); override it for a single run with `--user-context PATH` or
for a whole shell with `ROADMODEL_USER_CONTEXT=PATH`. The full
walk-through — first-run bootstrap, full precedence chain,
field-by-field schema, when to update — is
[docs/user-context-setup.md](docs/user-context-setup.md).

## Subcommands

| Command                          | What it does                                                                       |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| `roadmodel recommend PROMPT`     | Recommend a model / platform / settings block for the given prompt.                |
| `roadmodel recommend --file P`   | Same, but read the prompt text from file `P`.                                      |
| `roadmodel recommend --json`     | Emit the parsed fields as JSON instead of the labeled text block.                  |
| `roadmodel recommend --provider` | Override which provider answers (`anthropic` / `openai` / `google`).               |
| `roadmodel recommend --model`    | Override the specific model ID on the chosen provider.                             |
| `roadmodel recommend --user-context PATH` | Override the user-context.md location for this invocation.                |
| `roadmodel catalog show`         | Print the bundled `model-selector.txt` (use `--doc tier-cost-scale` for the price doc). |
| `roadmodel catalog path`         | Print the on-disk path of the bundled catalog document (same `--doc` flag).        |
| `roadmodel context show`         | Print the resolved `user-context.md` file.                                         |
| `roadmodel context path`         | Print the resolved `user-context.md` path (or the bootstrap target if missing).    |
| `roadmodel context init`         | Bootstrap `user-context.md` from the bundled template (`--force` to overwrite).    |
| `roadmodel version`              | Print the installed version.                                                       |

## How it works

The CLI ships three documents as package data:
[`model-selector.txt`](docs/model-selector.txt) (the selection
algorithm and the per-model access-methods catalog),
[`model-tier-cost-scale.md`](docs/model-tier-cost-scale.md) (per-token
prices and tier ratings), and
[`user-context.example.md`](docs/user-context.example.md) (the
user-state template). At recommendation time, `roadmodel recommend`
reads your filled-in `user-context.md` from disk, concatenates the
three docs into a single system prompt, and calls the provider you
configured. The provider returns a `MODEL / BACKUP / PLATFORM /
CONVERSATION / RATIONALE` block — plus the setting fields the chosen
platform exposes — following the `<output-format>` specification
inside `model-selector.txt`. `MODEL` is chosen by
`<selection-algorithm>` against your prompt's task category and
complexity; `PLATFORM` and the settings that come with it are filled
by the `<access-selection>` step, which depends on the subscriptions
and API-key state declared in your `user-context.md`. Because the
platform decides which dials exist, the field set varies per block:
an effort/thinking surface emits `EFFORT` + `THINKING`, Cursor emits
`MAX MODE`, and a dial the surface does not have is left out entirely
instead of being reported as `Off` or `N/A`.

## Benchmarks & ratings

Each model carries a per-category capability rating on an **S → D** scale — a rating
is a class several models can share, and the `/models` catalog shows each category's
headline benchmark figure plus the Artificial Analysis Intelligence Index next to the
letters so models within a class can be told apart — and the recommender grounds its
rationale in public benchmarks (SWE-bench Verified, τ²-bench, Terminal-Bench,
Humanity's Last Exam, and more). See
[**docs/benchmarks-and-ratings.md**](docs/benchmarks-and-ratings.md) for what the
scale means and a linked index of every benchmark the recommender cites — in the web
app, each benchmark term in a recommendation's rationale links straight to its source.

## Project status

Phases 1–3 have shipped: the open-source CLI (Phase 1), the MCP server and
catalog v2 (Phase 2), and the marketing site with an anonymous web recommender
at `roadmodel.ai` (Phase 3 — currently pre-launch, behind a gate). Phase 4
(accounts and the AI-assisted roadmap builder) is in progress; the planning
kit and its `/roadmap-*` workflow are the open-source half of that builder and
are what this repo's own phases are executed with. The project was
previously named `model-selector` and was renamed to `roadmodel` ahead of
the public release; the bundled-doc filename `model-selector.txt` is
preserved so existing references in other projects keep working. Until
v1.0.0, expect breaking
changes to the CLI surface between minor versions; each is listed in
[CHANGELOG.md](CHANGELOG.md).

See [ROADMAP.md](ROADMAP.md) for the phase plan and shipping order.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, pull
request scope, the catalog-edit process, and the
[Code of Conduct](CODE_OF_CONDUCT.md) that applies in community
spaces. Report security issues privately per [SECURITY.md](SECURITY.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Bundled
third-party attributions are listed in [NOTICE](NOTICE).
