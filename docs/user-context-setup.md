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
gates whether `PLATFORM` can ever be "Anthropic API direct",
"OpenAI API direct", or "Google AI Studio" — the selector will not
recommend a platform you have no key for.

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
(e.g. always-on thinking, or always-off for budget reasons). Note that a
flat, unexhausted subscription declared above opens the `<objective>`
FLAT-FUNDING GATE, which raises effort to the top useful rung on every
budget posture — so an effort-lowering policy here will not fire while
nothing is actually being saved.

### Budget priority and speed posture

Two short paragraphs declaring your `Budget priority` (one of
`cheap | balanced | best`) and your `Speed posture` (whether speed
is a valued dimension at all). The template defaults to
`balanced` budget + speed-not-valued, which suppresses "Fast" model
variants in favour of standard variants at half the per-token
price. Change to `cheap` to bias toward `composer-2` / Haiku /
Flash on tie-breaks, or to `best` to bias toward Opus / Sonnet /
GPT-5 frontier picks regardless of marginal cost.

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
