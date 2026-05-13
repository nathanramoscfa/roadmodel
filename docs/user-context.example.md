# User Context

User-specific state the model selector consumes when picking a **platform**
(access method) alongside a model. This file is intentionally separate from
[`model-selector.txt`](model-selector.txt) (the project-generic algorithm)
and [`model-tier-cost-scale.md`](model-tier-cost-scale.md) (the catalog of
per-token prices) so that:

1. The catalog stays generic and shareable.
2. Subscription state changes (a renewal, a downgrade, a new API key) do
   not pollute catalog diffs or trigger the weekly refresh cron.
3. A future Phase 2 `roadmodel` CLI can replace this doc with a
   `roadmodel.toml` config file without altering the algorithm.

The weekly catalog refresh in [`update/prompt.md`](../update/prompt.md)
**must not** modify this file.

## How the selector consumes this file

When [`model-selector.txt`](model-selector.txt) is referenced, the AI
treats this file as the user-state input to the `<access-selection>`
step: it reads the model recommendation produced by `<selection-algorithm>`,
then filters the `<access-methods>` block by what this file says the user
can actually pay for, and picks the cheapest survivor.

If this file is absent, the AI falls back to the default platform
preference order encoded in `<access-selection>` (currently: subscription
pool → subscription-included → per-token API → pay-as-you-go).

---

## Active subscriptions

> **This file is the public template.** Copy it to `docs/user-context.md`
> (gitignored) and replace the placeholder values below with your own real
> monthly subscription amounts and API-key state. The selector reads
> `docs/user-context.md` at runtime — this `.example.md` exists only to
> show the schema and is never read by the selector. Phase 1.2 will swap
> both files for a `roadmodel.toml` config.

| Subscription      | Monthly | Provider  | What it pays for                                                            |
| ----------------- | ------- | --------- | --------------------------------------------------------------------------- |
| Cursor Ultra      | $XXX    | Cursor    | Token-pool budget across every model in Cursor's catalog; no Max Mode surcharge (token-based plan, not legacy request-based). |
| claude.ai Max     | $XXX    | Anthropic | Opus / Sonnet / Haiku usage on claude.ai web, the Claude desktop apps, and Claude Code (CLI + IDE extension) under a shared monthly Max usage budget. Funds ~90% of total token volume. |
| ChatGPT Pro       | $XXX    | OpenAI    | GPT model usage on the ChatGPT app (web / desktop) and Codex CLI under per-model usage caps. Funds ~9% of total token volume. |

## Active API keys

| Provider  | Key present | Notes                                                              |
| --------- | ----------- | ------------------------------------------------------------------ |
| Anthropic | Yes         | Direct API key for pay-as-you-go fallback when Max budget is spent or when a script needs programmatic access outside Claude Code. |
| OpenAI    | Yes         | Direct API key for pay-as-you-go fallback when ChatGPT Pro caps are hit or when a script needs programmatic access outside Codex CLI. |
| Google    | No          | No paid Gemini Advanced; no Google AI Studio API key configured. Gemini accounts for ~1% of usage and runs via Cursor's pool only. |
| xAI       | No          | No direct API key. Grok usage is negligible; Cursor's pool covers it if needed. |

## Inactive / not subscribed

- **ChatGPT Team / Enterprise.** Pro is active; Team and Enterprise
  are not — team-collab and enterprise admin features aren't relevant
  for solo work.
- **Gemini Advanced.** Not subscribed; Google models reachable only via
  Cursor's pool at Cursor's per-token rates. Usage volume (~1%) doesn't
  justify a dedicated subscription.
- **Gemini CLI.** Not configured; would require a Google AI Studio API
  key. Same usage-volume rationale as Gemini Advanced.
- **xAI subscription / API key.** Not configured. Grok usage is
  negligible.

---

## Platform preference order

When multiple access methods can run the chosen model, prefer them in this
order (overrides the generic order in `<access-selection>`). The order
reflects the actual cost picture given the active subscriptions: ~90%
of token volume is Claude, ~9% is GPT (mostly Codex-style coding),
~1% is everything else — so dedicated subscription paths exist for the
two heavy-use providers and Cursor's pool absorbs the rest.

1. **Claude Code (CLI / IDE extension)** for any Claude model — funded
   by the $XXX/mo claude.ai Max subscription. Marginal cost per call is
   $0 until the Max usage budget is exhausted. This is the primary
   surface for ~90% of total work; via Cursor's pool the same Claude
   usage would cost multiples of the Max plan.
2. **Codex (Cursor extension or CLI)** for any GPT or Codex model
   — funded by the $XXX/mo ChatGPT Pro subscription. Marginal cost
   per call is $0 until per-model caps are hit. The Cursor-embedded
   Codex chat panel is the primary UI for interactive multi-file
   editing; Codex CLI is the same engine for terminal / autonomous-
   loop work. Exposes Intelligence as the only reasoning dial (Low
   / Medium / High / Extra High); no Max Mode or Thinking field on
   this surface. Primary GPT surface, accounting for ~9% of total
   token volume.
3. **Cursor Chat** with a GPT or Codex model selected — funded by
   the $XXX/mo Cursor Ultra token pool. Use when Cursor-native
   features (Max Mode for cross-file reasoning, inline file refs,
   the wider Cursor model catalog) fit the task better than the
   Codex chat panel. Marginal cost is per-token from the Cursor
   pool rather than the ChatGPT Pro flat-fee budget, so prefer
   Codex (#2) when ChatGPT Pro capacity remains.
4. **claude.ai web / desktop** for Claude chat-driven tasks (non-
   coding) — same Max budget as Claude Code.
5. **Cursor Ultra pool** for Google and xAI models (no dedicated
   subscription paths exist) and as a fallback for Claude / GPT models
   when the dedicated subscriptions are near exhaustion. Flat $XXX/mo
   already paid; $0 marginal cost until the pool is exhausted.
6. **Anthropic API direct** as pay-as-you-go fallback for Claude when
   (a) the call is programmatic / scripted outside Claude Code, (b)
   Max budget is exhausted, or (c) the workflow requires headers or
   features not exposed by Claude Code.
7. **OpenAI API direct** as pay-as-you-go fallback for GPT when (a)
   the call is programmatic / scripted outside Codex, (b) ChatGPT
   Pro caps are hit and Cursor Chat is also unavailable, or (c) the
   workflow requires headers or features not exposed by either
   Codex surface or Cursor Chat.
8. **Cursor Composer (Composer 2 default)** for routine multi-file
   editing tasks where Composer 2 at coding-A is sufficient. Cheapest
   output tier ($2.50/M) and the model is purpose-built for the
   Cursor surface.
9. **Google / xAI direct API.** Not applicable — no key present. The
   selector should not recommend these access methods while this
   section says no.

## Default Max Mode and thinking levels

- **Max Mode** — token-based plan, so no per-request surcharge. Apply
  `<max-mode-context>` rules verbatim; do not under-enable Max Mode for
  cost reasons.
- **Claude thinking** — default Off for routine prompts; On (mapped to
  THINKING `Medium`) for any prompt whose `<selection-algorithm>`
  complexity score is Medium; On with a large budget (mapped to
  THINKING `High`) for High-complexity; On with a very large budget
  (mapped to THINKING `XHigh`) for the gnarliest High-complexity
  prompts where novel problem-solving, multi-step proof, or
  chain-of-thought across many files is required. The rationale
  paragraph must name whether thinking is on and at what level.
- **GPT reasoning effort** — when a GPT model is selected and the
  access method exposes the toggle (Codex CLI / OpenAI API / ChatGPT
  app advanced controls), default to `medium`; escalate to `high` for
  any High-complexity prompt; escalate further to `xhigh` /
  `extra-high` (mapped to THINKING `XHigh` in the output format) for
  High-complexity prompts that ALSO involve novel problem-solving,
  multi-step proof, or chain-of-thought across many files — these are
  the prompts that warrant the slower, more expensive Codex variant
  (e.g., `gpt-5.3-codex-high`, `gpt-5.4-high`). Drop to `low` only for
  explicit `speed` PRIMARY tasks. Not applicable when the access
  method is Cursor's pool (Cursor does not expose the toggle).
- **Gemini thinking budget** — when a Gemini model is selected and the
  access method exposes the budget (Gemini CLI / Google API), default
  to the model's medium budget; escalate to a large budget (THINKING
  `High`) for High-complexity prompts; escalate to the model's
  largest budget (THINKING `XHigh`) for the same novel-problem /
  multi-step-proof / cross-file chain-of-thought triggers as GPT
  xhigh. Not applicable via Cursor's pool.

## Budget priority and speed posture

**Budget priority:** `balanced` — quality wins per `<objective>`, but
never burn pay-as-you-go spend when a subscription that is already
paid can serve the call. The selector should treat Cursor Ultra,
claude.ai Max, and ChatGPT Pro as sunk cost when ranking access
methods.

**Speed posture:** speed is NOT a valued dimension — workflows are
batch / asynchronous, not latency-sensitive. Apply these rules:

- **Never recommend a "Fast" variant** of a model (e.g., Opus 4.7
  Fast, GPT-5.4 Fast, GPT-5 Fast, Claude 4.6 Opus Fast mode) when a
  standard non-fast variant of the same base model is available.
  Fast variants in Cursor's catalog typically charge 2x output for
  marginal speed gain (e.g., "Fast mode is 15% faster with 2x
  pricing", "Claude 4.6 Opus Fast mode" at $30/$150 input/output vs.
  standard Opus at $5/$25) — the speed-for-cost trade is never worth
  it here.
- **In `<selection-algorithm>` Step 5** (cost tie-breaker), when the
  tied set contains both a standard and a Fast variant of the same
  base model, the standard variant always wins regardless of any
  other factor — they are tied in quality by construction (same
  base model), so cost decides.
- **In `<access-selection>` Step C**, do not prefer faster-but-more-
  expensive access methods on speed grounds. Subscription-funded
  paths win on cost even when a pay-per-token path would deliver
  the response faster.
- **PRIMARY task category `speed`** should be assigned only when the
  user's prompt explicitly states a latency requirement ("needs to be
  fast", "low-latency", "autocomplete-style", "real-time"). Tasks
  that merely feel "small and routine" should be classified as
  `coding` or `knowledge` at Low complexity — that still lets the
  algorithm pick a cheap fast-by-default model like composer-2 when
  it fits, without elevating speed itself to a goal.

---

## How to update this file

Hand-edit this file when a subscription is added, renewed at a different
tier, cancelled, or when an API key is rotated in or out. Commit the
change separately from any catalog refresh so the diff is readable.

Do **not** add or remove the schema sections above; the selector relies
on their presence. To add a new field (e.g. a per-provider monthly cap
ceiling), update [`model-selector.txt`](model-selector.txt) `<access-selection>`
first so the algorithm knows how to consume it.
