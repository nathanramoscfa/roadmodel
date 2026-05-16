# roadmodel

A BYO-key command-line tool that recommends **which AI model on which
platform with which settings** for a given prompt. Point it at a task
description, and it returns a six-field block — `MODEL / PLATFORM /
MAX MODE / THINKING / CONVERSATION / RATIONALE` — grounded in a
bundled benchmark and pricing catalog (Cursor pricing, Artificial
Analysis, LiveCodeBench, τ²-bench, SWE-bench, MMMU, LMArena) and
filtered against your own subscriptions and API keys. Built for
developers who use several AI subscriptions (Claude Code, Cursor,
Codex / ChatGPT, raw provider APIs) and want a deterministic answer
to "what should I use for this?" instead of guessing.

[![PyPI version](https://img.shields.io/pypi/v/roadmodel.svg)](https://pypi.org/project/roadmodel/)
[![Python versions](https://img.shields.io/pypi/pyversions/roadmodel.svg)](https://pypi.org/project/roadmodel/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/nathanramoscfa/roadmodel/actions/workflows/tests.yml/badge.svg)](https://github.com/nathanramoscfa/roadmodel/actions/workflows/tests.yml)
[![Phase verify](https://github.com/nathanramoscfa/roadmodel/actions/workflows/phase-verify.yml/badge.svg)](https://github.com/nathanramoscfa/roadmodel/actions/workflows/phase-verify.yml)

## Install

```sh
pip install roadmodel
```

Python 3.11 or newer.

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
calls your chosen provider and prints a parsed six-field block:

```sh
roadmodel recommend "Refactor auth middleware across 12 files"
```

```
MODEL: claude-opus-4-7
PLATFORM: Claude Code
MAX MODE: On
THINKING: High
CONVERSATION: New
RATIONALE: Coding PRIMARY with cross-file scope and High complexity.
Opus 4.7 is S-tier on coding-agent benchmarks and the only model in
the catalog rated S for long-context recall. PLATFORM Claude Code
is funded by claude.ai Max ($0 marginal); THINKING High per the
selection-algorithm rule for High-complexity coding.
```

Pass `--json` to emit the same fields as machine-readable JSON, or
`--file PATH` to read the prompt from disk.

## BYO-key setup

roadmodel ships with no provider key built in — it calls
**your** Anthropic / OpenAI / Google account on every recommendation
and charges your account. Set any one of the three environment
variables and the CLI auto-selects that provider:

| Provider  | Env var             |
| --------- | ------------------- |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI    | `OPENAI_API_KEY`    |
| Google    | `GOOGLE_API_KEY`    |

The full guide — generating keys in each provider's console, storing
them in a shell profile or `~/.config/roadmodel/config.toml`,
precedence rules, and verifying with a smoke call — is
[docs/byo-key-setup.md](docs/byo-key-setup.md).

## User context setup

roadmodel reads a per-user Markdown file describing your active
subscriptions, API keys, platform preference order, and budget
posture so the `<access-selection>` step can pick a **platform** and
**thinking level** alongside the model. The resolved default path is
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
| `roadmodel recommend PROMPT`     | Recommend a six-field block for the given prompt.                                  |
| `roadmodel recommend --file P`   | Same, but read the prompt text from file `P`.                                      |
| `roadmodel recommend --json`     | Emit the parsed six fields as JSON instead of the labeled text block.              |
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
configured. The provider returns a `MODEL / PLATFORM / MAX MODE /
THINKING / CONVERSATION / RATIONALE` block following the
`<output-format>` specification inside `model-selector.txt`. `MODEL`
is chosen by `<selection-algorithm>` against your prompt's task
category and complexity; `PLATFORM` and `THINKING` are filled by the
`<access-selection>` step, which depends on the subscriptions and
API-key state declared in your `user-context.md`.

## Project status

roadmodel is in **Phase 1** — the open-source CLI release. Phase 2
adds an MCP server alongside the CLI; later phases add a hosted
SaaS at `roadmodel.ai`. The project was previously named `model-selector`
and was renamed to `roadmodel` ahead of the public release; the
canonical bundled-doc filename `model-selector.txt` is preserved so
existing references in other projects keep working. Until v1.0.0,
expect breaking changes to the CLI surface as Phase 2 lands.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, pull
request scope, the catalog-edit process, and the
[Code of Conduct](CODE_OF_CONDUCT.md) that applies in community
spaces. Report security issues privately per [SECURITY.md](SECURITY.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Bundled
third-party attributions are listed in [NOTICE](NOTICE).
