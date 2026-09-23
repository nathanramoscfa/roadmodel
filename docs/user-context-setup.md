# User Context Setup

This guide walks through `user-context.md` — the per-user file
roadmodel reads at every `recommend` invocation to pick a
**platform** and the **runtime settings that platform exposes**
alongside the model. If you have
not yet set an API key, start with
[byo-key-setup.md](byo-key-setup.md) and come back here.

## Why this file exists

`model-selector.txt` ships with two pipeline steps. The
`<selection-algorithm>` step is project-generic — it scores models
on the bundled benchmark catalog against a prompt's task category
and complexity. The `<access-selection>` step is **user-specific**:
it takes the candidate model and asks "which access method is
cheapest for *this* user given *which* subscriptions they pay for?"
A generic algorithm cannot pick `PLATFORM` (Claude Code vs. Cursor
vs. raw API) without that subscription state, which is what
`user-context.md` provides — and the PLATFORM in turn decides which
setting fields the recommendation even carries, since a block emits
only the dials the chosen surface exposes (`EFFORT` + `THINKING` on a
reasoning-dial surface, `MAX MODE` on Cursor, and so on).

## First-run bootstrap

On the very first run of `roadmodel recommend`, the CLI detects
that no `user-context.md` exists at the resolved path, copies the
bundled template
([`user-context.example.md`](user-context.example.md)) to your
config home, prints a one-line notice to stderr, and exits with
status `6` without calling the provider:

```
Created /home/you/.config/roadmodel/user-context.md from bundled
template. Edit it with your real subscription state, then re-run.
```

The exact path is `~/.config/roadmodel/user-context.md` — or
`$XDG_CONFIG_HOME/roadmodel/user-context.md` when `XDG_CONFIG_HOME`
is set, which is the standard on most Linux desktop environments.

You can also trigger the bootstrap manually without running a
recommendation:

```sh
roadmodel context init           # writes the file, errors if it exists
roadmodel context init --force   # overwrites an existing file
roadmodel context path           # prints the resolved path
```

After the file is written, open it in `$EDITOR` and replace the
`$XXX` placeholders for monthly subscription amounts and the
`Yes/No` placeholders for API-key state with your real values. The
CLI warns (but does not block) on subsequent runs if `$XXX` is
still present.

## Path resolution precedence

`user_context.resolve` checks these sources in order and uses the
first one that points to an existing file. If none exist, the
default home is returned as the bootstrap target.

1. **`--user-context PATH`** — explicit per-invocation override
   passed on the command line.
2. **`ROADMODEL_USER_CONTEXT`** environment variable — shell-scoped
   override (handy for switching between work and personal
   contexts on one machine).
3. **`$XDG_CONFIG_HOME/roadmodel/user-context.md`** — when the
   `XDG_CONFIG_HOME` env var is set, this is the resolved default.
4. **`~/.config/roadmodel/user-context.md`** — when
   `XDG_CONFIG_HOME` is **not** set, this is the resolved default.

Sources 3 and 4 are mutually exclusive — they are the same
"default config home", branching only on whether `XDG_CONFIG_HOME`
is set in your environment.

There is **no repo fallback**: `user_context.resolve` never inspects
the current working directory or a surrounding git checkout, so a
`docs/user-context.md` sitting in a clone is not picked up. Point at
an in-repo copy explicitly with `--user-context docs/user-context.md`
or `ROADMODEL_USER_CONTEXT=docs/user-context.md` if you want that
file used.

## Keeping it the same on every machine

If you plan from more than one machine, give the file ONE home and let
`roadmodel-update` carry it. Hand-copying drifts on the first edit — and the
file changes every time a usage pool binds.

One machine is the **source**: it publishes its file to a **private** GitHub
repo. Every other machine is a **replica**: it pulls that file before
refreshing its planning kits, so every machine plans against the same context
each morning.

```bash
# once, on the source machine
gh repo create <you>/roadmodel-context --private
python update_projects.py --context-sync <you>/roadmodel-context \
    --context-source /path/to/your/user-context.md

# once, on each other machine
python update_projects.py --context-sync <you>/roadmodel-context
```

After that, every run — including the daily schedule — publishes (source) or
pulls (replica). Edit only on the source: a replica keeps the copy it
replaced as `user-context.md.prev`, but it will be overwritten.

Point the source machine's default path at the source file
(`ln -s /path/to/your/user-context.md ~/.config/roadmodel/user-context.md`) so
the CLI, the MCP server and the kits all read the one file. The updater warns
when a separate copy at the default path would never be published.

**Keep the repo private.** This file names your subscriptions and accounts.
Never commit it to a public repository — in this repo, `docs/user-context.md`
is gitignored, and a test fails if that ever changes.

## Field-by-field walk-through

The sections below mirror
[`user-context.example.md`](user-context.example.md) one-to-one so
the two docs can be read side-by-side.

### Active subscriptions

A Markdown table of every AI subscription you currently pay for, with
columns `Subscription | Monthly | Provider | What it pays for`. Replace
the `$XXX` placeholders with the real monthly cost (e.g. `$200`) and
edit the "What it pays for" cell to describe what the plan covers
(model access, request caps, token pool size, Max Mode pricing
posture). The `<access-selection>` step reads this table to decide
which platforms have $0 marginal cost for a given model.

Example row:

```
| claude.ai Max | $200 | Anthropic | Opus / Sonnet / Haiku usage on
claude.ai web, the Claude desktop apps, and Claude Code (CLI + IDE
extension) under a shared monthly Max usage budget. |
```

If you have no AI subscriptions, leave the table empty — the
selector then defaults every recommendation to a per-token API path.

### Active API keys

A Markdown table of provider API keys you have configured locally
(`Provider | Key present | Notes`). `Yes` / `No` in the middle
column is what the selector reads; the notes column documents why
(e.g. "pay-as-you-go fallback when Max budget is spent"). This
gates whether `PLATFORM` can ever be a provider-direct API — the
selector will not recommend a platform you have no key for. One row
per provider the catalog federates: Anthropic, OpenAI, Google, xAI,
DeepSeek, Mistral, Groq (which hosts the open-weight gpt-oss models),
Z.ai (GLM), and OpenRouter. A `Yes` on DeepSeek or Z.ai only takes
effect once `cn` is also in your allowed-jurisdictions list (see
below); a `Yes` on Mistral is what makes the EU-sovereignty picks
recommendable.

The **OpenRouter** row is different in kind: it is an aggregator key
(one key, most of the catalog, paid per token) rather than a maker's
key. A `Yes` unlocks the `openrouter` access method — `PLATFORM:
OpenRouter` — for every model its `supports-models` lists, at the
maker's list price plus OpenRouter's platform fee, so the catalog
price is a floor for that platform. OpenRouter may serve a request
from any of its upstream hosts; the model-level jurisdiction filter
still decides which models are eligible, and the selector prefers a
maker's own method when you hold that key too.

### Local models (Ollama)

Two small tables declaring what you can run **on this machine**
through a local [Ollama](https://ollama.com) runtime:

```
| Runtime          | Present |
| ---------------- | ------- |
| Ollama installed | Yes     |

| Catalog model id | Tag pulled  | Quantization | Notes |
| ---------------- | ----------- | ------------ | ----- |
| gpt-oss-20b      | gpt-oss:20b | MXFP4        | fits 16 GB |
```

The first column is the **catalog model id** (from `<model-options>`),
not the Ollama tag; the second is the exact tag `ollama list` shows.
The selector funds the `ollama` access method — `PLATFORM: Ollama
(local)`, $0 per token, no data leaves the machine — **only** for the
models listed here and only while the presence row says `Yes`. Unlike
an API key you have not configured (which stays a valid, merely
unfunded, path), an undeclared local method is **dropped**: hardware
you do not have is not money you might spend. Every local pick carries
a quantization caveat in its rationale, because the catalog's tier
ratings describe the provider-hosted weights and a quantized local
pull runs about one tier below them for coding and reasoning. Only
models the `ollama` method's `supports-models` lists — open weights
under a licence that permits local use — are ever recommended here.

This section is about being *recommended* to run a model locally. Using
a local model as the recommender's own engine (`roadmodel recommend
--provider ollama`) is a separate setup with its own constraints — see
[`byo-key-setup.md`](byo-key-setup.md), "Local Ollama".

### Inactive / not subscribed

A bulleted list of subscriptions you considered and rejected, with a
one-line rationale per item. Not consumed by the selector
mechanically, but kept in the prompt so the model's reasoning
acknowledges the trade-offs you have already made and does not
recommend platforms you have explicitly chosen against (e.g.
"Gemini Advanced — not subscribed, usage volume too low").

### Platform preference order

A numbered list of platforms ranked by your preferred default order.
This **overrides** the generic order in `<access-selection>` when
multiple access methods could run the chosen model. The
`<access-selection>` step walks this list top-to-bottom and picks
the first entry that can serve the model and has $0 marginal cost
remaining. The example template's order
(Claude Code → Codex → Cursor → claude.ai → Anthropic API → OpenAI
API → Google API) is a good starting point if you hold the same
subscription bundle the template describes; otherwise re-order to
match your actual cost picture.

This list is a **soft** preference: it reorders access methods that
already survived filtering, and a strong enough fit can outrank it.
To rule a platform **out** entirely, use the hard filter below.

### Allowed / excluded platforms

Two optional keys — `platforms.allowed` and `platforms.excluded` —
naming **access-method ids** from the `<access-methods>` block of
`model-selector.txt` (`claude-code`, `cursor`, `codex-cli`,
`chatgpt-app`, `anthropic-api`, `openai-api`, `google-api`, …), not
display names and not provider names:

```text
platforms.allowed:   claude-code, codex-cli, anthropic-api
platforms.excluded:  cursor
```

`<access-selection>` **Step A00** applies both as **hard filters
before any scoring**, the same way the jurisdiction list filters
models. A non-empty `platforms.allowed` drops every access method not
on it; `platforms.excluded` drops every method on it. This is the
difference from *Platform preference order* above: that list changes
the ORDER of the candidates, this one changes WHO the candidates are.

The filter also **outranks** the selector's "never hard-exclude an
unfunded access method" guardrail. That guardrail keeps a lack of
money from suppressing a better pick — an unfunded method is still
recommended, with the spend disclosed, because you might choose to pay
it. Declaring a platform excluded says something else: you do not
operate that surface, so a recommendation routed through it would hand
you dials you cannot set. When they conflict, your list wins, and the
selector must disclose the drop in its RATIONALE rather than
substituting silently.

**The section is optional and safe to omit.** If your
`user-context.md` predates these keys — every hand-edited file does —
Step A00 is a no-op, every access method stays eligible, and behavior
is identical to before the keys existed. An absent or empty allowlist
means "no opt-out declared", never "allow nothing". Bootstrapping a
fresh file with `roadmodel context init` (into a temp path, then
copying the section over) is the easy way to pick up the template's
current wording.

### Default effort, thinking, and Max Mode

Bulleted policies describing the default runtime settings the selector
should emit, and how to escalate them with prompt complexity. Output
contract v2 keeps these as SEPARATE fields, so state them separately:

- **`EFFORT`** carries the reasoning LEVEL — `Low` / `Medium` / `High` /
  `XHigh` / `Max`, plus `Ultracode` on Claude Code only. Recommended
  starting point: `Low` for routine prompts, `Medium` for
  Medium-complexity, `High` for High-complexity, `XHigh` for the
  gnarliest novel-problem / multi-step-proof prompts.
- **`THINKING`** is a two-position toggle — `On` or `Off`, nothing else.
  It never carries an effort word: `THINKING: Max` is not a setting any
  surface can apply, which is why the level lives in `EFFORT`.
- **`MAX MODE`** applies to Cursor alone. On every other platform no Max
  Mode line is emitted at all.

Edit only if you have a strong cost or latency preference that diverges
(e.g. always-on thinking, or always-off for budget reasons). The
complexity ladder is the final effort value under the default `capped`
consumption headroom (next section). Only a declared `uncapped`
headroom opens the `<objective>` FLAT-FUNDING GATE, which holds the
frontier tier and raises effort to the top useful rung on every budget
posture — so an effort-lowering policy here is a no-op only for a user
who has said they never hit their limits.

### Budget priority and speed posture

Three short paragraphs declaring your `Budget priority` (one of
`cheap | balanced | best`), your `Consumption headroom` (one of
`capped | uncapped`) and your `Speed posture` (whether speed
is a valued dimension at all). The template defaults to
`balanced` budget + `capped` headroom + speed-not-valued, which
suppresses "Fast" model variants in favour of standard variants at
half the per-token price and keeps reasoning effort at the
complexity-ladder value. Change budget to `cheap` to bias toward
`composer-2` / Haiku / Flash on tie-breaks, or to `best` to bias
toward Opus / Sonnet / GPT-5 frontier picks regardless of marginal
cost.

`Consumption headroom` is the effort axis. `capped` (default) says the
subscription's session / weekly usage pools can bind, so effort AND
tier follow the ladders — a weekly pool is metered by both the model
and the effort level, and a bounded step on a mid-tier model at
`Medium`/`High` leaves budget for the steps that need the frontier
model at `XHigh`/`Max`. `uncapped` is an opt-in for users who have
never hit a limit on that plan: it emits the top useful effort on
every pick and opens the `<objective>` FLAT-FUNDING GATE (frontier
tier held on every posture). A top-price tier is not by itself a
reason to declare `uncapped`.

### Usage-pool status

An optional table with one row per subscription usage pool (for
example the claude.ai weekly pool and its 5-hour session pool) and a
`State` of `headroom | tight | exhausted` plus the reset time.
`<access-selection>` Step C uses it to decide which funded paths are
really $0 in the current window: a `tight` pool is reserved for
High-complexity work and routine tasks go to another funded pool that
reaches an adequate model; an `exhausted` pool's platforms rank as
pay-per-token (usage credits bill at list price) until the reset, or
as unfunded if the row says `overflow off`. This is the hook that
makes a second coding-agent subscription (Codex on ChatGPT, Antigravity
on Google AI) an automatic fallback when the primary pool runs dry.
Hand-edit it when a cap binds; clear it when the window resets.

## When to update

Hand-edit `user-context.md` whenever your subscription or API-key
state changes:

- **Adding a subscription** — add a row to *Active subscriptions*
  and adjust *Platform preference order* if the new plan should be
  preferred over an existing one.
- **Renewing at a different tier** — update the `Monthly` and
  "What it pays for" cells; re-rank platform preference if the new
  tier changes the cost picture.
- **Cancelling a subscription** — remove the row from *Active
  subscriptions*, demote or remove the platform from the
  preference order, and move the entry into *Inactive / not
  subscribed* with a rationale.
- **Hitting a usage cap** — set the pool's row in *Usage-pool status*
  to `tight` (before) or `exhausted` (after) with the reset time; put
  it back to `headroom` when the window resets. If you find yourself
  doing this most weeks, the `Consumption headroom` posture should be
  `capped` (it is the default) — not `uncapped`.
- **Rotating an API key** — flip the `Key present` cell to `No`
  while the key is unset, then back to `Yes` after the new key is
  configured per [byo-key-setup.md](byo-key-setup.md). The
  selector should not recommend that direct-API platform during
  the gap.

Commit edits separately from any other change so the diff is
readable.

## Sharing across machines

`user-context.md` is **local-only**. It lives in your config home
(or wherever your `--user-context` / `ROADMODEL_USER_CONTEXT`
override points) and is never bundled into the `roadmodel` wheel.
If you use roadmodel on more than one machine, sync the file
yourself via whichever secret-management workflow you already trust
— a [dotfiles repo](https://dotfiles.github.io/), 1Password
Secrets Automation / `op inject`, `chezmoi`, an encrypted vault,
etc. Treat it like a `.env` file: not catastrophic if it leaks (it
contains subscription metadata, not API keys), but not something
to commit to a public repo either.

Phase 2 of the [public roadmap](../private/ROADMAP.md) may replace
this Markdown file with a config-driven equivalent
(`roadmodel.toml`). The schema will stay equivalent; the user-state
input model will not.

## Privacy

`user-context.md` is read at runtime, concatenated into the system
prompt, and sent to whichever provider you have configured
(Anthropic, OpenAI, or Google) on every `recommend` call. Treat the
file's contents as user data going to that provider, subject to
that provider's data-handling and retention policies. roadmodel
itself stores nothing — there is no telemetry, no server-side
state, and no upload anywhere except the direct provider call.

If a particular subscription detail is sensitive (e.g. you do not
want to reveal a specific monthly spend amount to a third-party
provider), redact or generalise that cell. The selector tolerates
fuzzy values like `~$200` or `$XXX-range` in the `Monthly` column;
it cares about the relative ordering of subscriptions, not the
exact dollar figures.
