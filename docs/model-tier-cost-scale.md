# Model Tier Cost Scale

Tier classification is based solely on **Output price per 1M tokens** from each
provider's published API pricing. The four-tier scale below defines the
boundary used in `model-selector.txt`.

## Tier Boundaries


| Tier      | Output price (per 1M tokens) |
| --------- | ---------------------------- |
| Low       | < $10                        |
| Medium    | $10 – $14.99                 |
| High      | $15 – $24.99                 |
| Very High | ≥ $25                        |


*Boundary is inclusive on the lower end of each tier (e.g. exactly $10 → Medium,
exactly $15 → High, exactly $25 → Very High).*

---

## Full Model Pricing Reference

Prices sourced from Cursor's model pricing page (API pool + Auto/Composer pool).
All prices are per 1M tokens. The **Notes** column mirrors the rightmost cell of
each row in Cursor's `models-and-pricing` Markdown source — these are the
hovertext annotations that appear next to the info icon in Cursor's IDE pricing
table and surface material cost / availability / capability constraints.

### Auto + Composer Pool


| Model            | Input | Cache Write | Cache Read | Output | Tier | Notes |
| ---------------- | ----- | ----------- | ---------- | ------ | ---- | ----- |
| Composer 2       | $0.50 | –           | $0.20      | $2.50  | Low  | Hidden by default |
| Auto (pool rate) | $1.25 | $1.25       | $0.25      | $6.00  | Low  | Cursor-managed routing across the Auto + Composer pool; not a fixed model |


### API Pool — Anthropic (Claude)


| Model                       | Input  | Cache Write | Cache Read | Output  | Tier      | Notes |
| --------------------------- | ------ | ----------- | ---------- | ------- | --------- | ----- |
| Claude 4 Sonnet             | $3.00  | $3.75       | $0.30      | $15.00  | High      | Hidden by default; Thinking variant counts as 2 requests in legacy pricing |
| Claude 4 Sonnet 1M          | $6.00  | $7.50       | $0.60      | $22.50  | High      | Hidden by default; Thinking variant counts as 2 requests in legacy pricing; This model can be very expensive due to the large context window; The cost is 2x when the input exceeds 200k tokens |
| Claude 4.5 Haiku            | $1.00  | $1.25       | $0.10      | $5.00   | Low       | Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x |
| Claude 4.5 Opus             | $5.00  | $6.25       | $0.50      | $25.00  | Very High | Hidden by default; Requires Max Mode on request-based plans |
| Claude 4.5 Sonnet           | $3.00  | $3.75       | $0.30      | $15.00  | High      | Hidden by default; Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge) |
| Claude 4.6 Opus             | $5.00  | $6.25       | $0.50      | $25.00  | Very High | Hidden by default; Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge) |
| Claude 4.6 Opus (Fast mode) | $30.00 | $37.50      | $3.00      | $150.00 | Very High | Hidden by default; Requires Max Mode on request-based plans; Limited research preview; Up to 1M tokens in Max Mode at the same per-token rates as shorter context |
| Claude 4.6 Sonnet           | $3.00  | $3.75       | $0.30      | $15.00  | High      | Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge) |
| Claude 4.7 Opus             | $5.00  | $6.25       | $0.50      | $25.00  | Very High | Hidden by default; Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge) |
| Claude Fable 5              | $10.00 | $12.50      | $1.00      | $50.00  | Very High | Requires data retention approval for Enterprise customers, Teams and individual customers with Privacy Mode enabled; Anthropic stores agent input and output data for harm-prevention processes; this data is not used to train or improve Anthropic models or products; Requests that trip a security guardrail are automatically routed to Claude Opus; About 2x the cost of Claude Opus 4.8; Requires Max Mode on request-based plans |
| Claude Opus 4.7 (fast mode) | $30.00 | $37.50      | $3.00      | $150.00 | Very High | Hidden by default; Requires Max Mode on request-based plans; Limited research preview; Up to 1M tokens in Max Mode at the same per-token rates as shorter context |
| Claude Opus 4.8             | $5.00  | $6.25       | $0.50      | $25.00  | Very High | Requires Max Mode on request-based plans; Fast mode (`claude-opus-4-8-fast`) requires Max Mode; Fast mode is 3x lower per-token pricing than Opus 4.7 fast mode; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge) |


### API Pool — Cursor Composer


| Model        | Input | Cache Write | Cache Read | Output | Tier   | Notes             |
| ------------ | ----- | ----------- | ---------- | ------ | ------ | ----------------- |
| Composer 1   | $1.25 | –           | $0.125     | $10.00 | Medium | Hidden by default |
| Composer 1.5 | $3.50 | –           | $0.35      | $17.50 | High   | Hidden by default |
| Composer 2   | $0.50 | –           | $0.20      | $2.50  | Low    | Hidden by default |
| Composer 2.5 | $0.50 | –           | $0.20      | $2.50  | Low    | -                 |


### API Pool — Google (Gemini)


| Model                      | Input | Cache Write | Cache Read | Output | Tier   | Notes |
| -------------------------- | ----- | ----------- | ---------- | ------ | ------ | ----- |
| Gemini 2.5 Flash           | $0.30 | –           | $0.03      | $2.50  | Low    | Hidden by default |
| Gemini 3 Flash             | $0.50 | –           | $0.05      | $3.00  | Low    | Hidden by default |
| Gemini 3 Pro               | $2.00 | –           | $0.20      | $12.00 | Medium | Hidden by default |
| Gemini 3 Pro Image Preview | $2.00 | –           | $0.20      | $12.00 | Medium | Hidden by default; Native image generation model optimized for speed, flexibility, and contextual understanding; Text input and output priced the same as Gemini 3 Pro; Image output: $120/1M tokens (~$0.134 per 1K/2K image, ~$0.24 per 4K image); Preview models may change before becoming stable and have more restrictive rate limits |
| Gemini 3.1 Pro             | $2.00 | –           | $0.20      | $12.00 | Medium | -                 |
| Gemini 3.5 Flash           | $1.50 | –           | $0.15      | $9.00  | Low    | -                 |


### API Pool — OpenAI (GPT)


| Model              | Input | Cache Write | Cache Read | Output | Tier      | Notes |
| ------------------ | ----- | ----------- | ---------- | ------ | --------- | ----- |
| GPT-5              | $1.25 | –           | $0.125     | $10.00 | Medium    | Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5-high |
| GPT-5 Fast         | $2.50 | –           | $0.25      | $20.00 | High      | Hidden by default; Faster speed but 2x price; Available reasoning effort variants are gpt-5-high-fast, gpt-5-low-fast |
| GPT-5 Mini         | $0.25 | –           | $0.025     | $2.00  | Low       | Hidden by default |
| GPT-5-Codex        | $1.25 | –           | $0.125     | $10.00 | Medium    | Hidden by default; Agentic and reasoning capabilities |
| GPT-5.1 Codex      | $1.25 | –           | $0.125     | $10.00 | Medium    | Hidden by default; Agentic and reasoning capabilities |
| GPT-5.1 Codex Max  | $1.25 | –           | $0.125     | $10.00 | Medium    | Hidden by default |
| GPT-5.1 Codex Mini | $0.25 | –           | $0.025     | $2.00  | Low       | Hidden by default; Agentic and reasoning capabilities; 4x rate limits compared to GPT-5.1 Codex |
| GPT-5.2            | $1.75 | –           | $0.175     | $14.00 | Medium    | Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high |
| GPT-5.2 Codex      | $1.75 | –           | $0.175     | $14.00 | Medium    | Hidden by default; Agentic and reasoning capabilities |
| GPT-5.3 Codex      | $1.75 | –           | $0.175     | $14.00 | Medium    | Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high |
| GPT-5.4            | $2.50 | –           | $0.25      | $15.00 | High      | Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing |
| GPT-5.4 Mini       | $0.75 | –           | $0.075     | $4.50  | Low       | Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens |
| GPT-5.4 Nano       | $0.20 | –           | $0.02      | $1.25  | Low       | Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens |
| GPT-5.5            | $5.00 | –           | $0.50      | $30.00 | Very High | Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing |


### API Pool — xAI


| Model          | Input | Cache Write | Cache Read | Output | Tier | Notes |
| -------------- | ----- | ----------- | ---------- | ------ | ---- | ----- |
| Grok 4.20      | $2.00 | –           | $0.20      | $6.00  | Low  | Hidden by default; The cost is 2x when the input exceeds 200k tokens |
| Grok 4.3       | $1.25 | –           | $0.20      | $2.50  | Low  | Hidden by default; Requires Max Mode on request-based plans |
| Grok Build 0.1 | $1.00 | –           | $0.20      | $2.00  | Low  | The cost is 2x when the input exceeds 200k tokens; No user-configurable reasoning effort |


### API Pool — Moonshot


| Model     | Input | Cache Write | Cache Read | Output | Tier | Notes |
| --------- | ----- | ----------- | ---------- | ------ | ---- | ----- |
| Kimi K2.5 | $0.60 | –           | $0.10      | $3.00  | Low  | Hidden by default |


### API Pool — Z.ai


| Model   | Input | Cache Write | Cache Read | Output | Tier | Notes |
| ------- | ----- | ----------- | ---------- | ------ | ---- | ----- |
| GLM 5.2 | $1.40 | –           | $0.26      | $4.40  | Low  | Hidden by default |


---

<!-- subscription-tiers-reviewed: 2026-06-29 -->

## Subscription Tiers and Access Methods

The per-token tables above are one dimension of cost. Many of the same
models are reachable through flat-monthly subscription plans whose
marginal cost per call is effectively $0 until the subscription's usage
budget or token pool is exhausted. The selector's `<access-selection>`
step uses this table to rank platforms; the user-specific subscription
state lives in [`docs/user-context.md`](user-context.md).

This table is a DERIVED VIEW of each provider's official pricing page,
rebuilt weekly by [`update/update_models.py`](../update/update_models.py)
using Anthropic's `web_search` server-side tool per the rules in
[`update/prompt.md`](../update/prompt.md) § "Subscription tiers". Each
run discovers the canonical pricing page for every provider enumerated
in `<access-methods>` of [`docs/model-selector.txt`](model-selector.txt),
enumerates the consumer tiers shown, and writes the resulting row set
into this table. Manual edits to the table body will be overwritten on
the next run. To change which providers are in scope, edit
`<access-methods>` (which is editorial and remains protected by the
existing model-lifecycle rules); the next cron run picks up the new
provider automatically.

The **`Annual`** column (the full yearly total in USD) is rebuilt by the
same `web_search` pass as the monthly price, with two safeguards (see
[`update/prompt.md`](../update/prompt.md) § "Annual column"): a **sanity
guard** accepts a captured annual `A` for a tier with monthly `M` only
when `8 × M ≤ A ≤ 12 × M` (a real annual discount, never a misparse), and
**preserve-on-miss** keeps the existing cell verbatim when no annual is
found or the guard trips — so a transient fetch miss never downgrades a
known-good price. A tier with no annual plan carries `—` (parsed as a
null `annual_usd`, which suppresses the annual price + savings in the UI
without breaking the tier). To pin or correct an annual price by hand,
edit the cell directly; the next rebuild keeps it unless it re-derives a
guarded value that differs (and then logs the change).

`tests/test_subscription_freshness.py` watches the
`<!-- subscription-tiers-reviewed: YYYY-MM-DD -->` marker above. The
cron bumps the marker to today's date only when every in-scope
provider's rebuild completed without tripping a sanity guard; a stale
marker (>180 days) therefore means the cron has been running but
subscription rebuild has been persistently failing — most likely a
provider has redesigned its pricing page in a way the AI can no longer
parse cleanly. When that happens, eyeball the failing provider's page
and adjust the rebuild rules in [`update/prompt.md`](../update/prompt.md).


| Subscription           | Monthly | Annual | Provider  | Access methods unlocked      | Coverage                                                                                                  |
| ---------------------- | ------- | ------ | --------- | ---------------------------- | --------------------------------------------------------------------------------------------------------- |
| Claude Pro             | $20     | $200   | Anthropic | claude-code, claude-web      | <cite index="2-16,2-17">Claude Pro costs $20 per month, or $17 per month when billed annually</cite>; standard entry tier with Opus 4.7, Sonnet 4.6, and Claude 4.5 Haiku on web / desktop and inside Claude Code (CLI + IDE), roughly 5x Free usage. |
| claude.ai Max ($100)   | $100    | —      | Anthropic | claude-code, claude-web      | <cite index="2-21">Claude Max provides 5x the usage of Claude Pro, with priority access during high-traffic periods</cite>; same model coverage as Pro. |
| claude.ai Max ($200)   | $200    | —      | Anthropic | claude-code, claude-web      | <cite index="8-4">Max 20x gives you 20× Pro's per-session limit</cite>; same model coverage as Pro at the highest consumer-tier Claude budget. |
| ChatGPT Go             | $8      | —      | OpenAI    | chatgpt-app, codex-cli       | <cite index="17-27,17-28,17-29">$8/month tier with 10x more messages, unlimited GPT-5.3 Instant, file uploads, and image creation, but ads still shown and missing GPT-5.5 plus Codex / Agent Mode / Deep Research</cite>. |
| ChatGPT Plus           | $20     | —      | OpenAI    | chatgpt-app, codex-cli       | <cite index="14-22,14-23">Full model suite, Deep Research (10 runs/mo), Sora, Codex, Agent Mode; ad-free</cite>; GPT-5.5 default model with GPT-5.4 Thinking and GPT-5.4 Mini also available. |
| ChatGPT Pro ($100)     | $100    | —      | OpenAI    | chatgpt-app, codex-cli       | <cite index="17-22,17-23,17-24,17-25">$100/mo tier launched April 9, 2026, positioned against Claude Max at the same price; includes GPT-5.5, GPT-5.5 Pro, o1 Pro mode, and 5x Plus usage limits, with a launch promotion doubling Codex usage to 10x through May 31, 2026 before dropping to 5x</cite>. |
| ChatGPT Pro ($200)     | $200    | —      | OpenAI    | chatgpt-app, codex-cli       | <cite index="13-28,13-29">Top tier with GPT-5.4 Pro and GPT-5.5 at near-unlimited usage and 1M token context window plus Sora access</cite>; 20x Plus limits, the only consumer tier covering both top-tier model capability and video generation. |
| Google AI Plus         | $4.99   | —      | Google    | gemini-app, gemini-cli       | <cite index="28-5">Google AI Plus plan at $4.99/mo (down from $7.99) with included storage doubled from 200GB to 400GB</cite>; 2x higher usage limits than Free with access to Gemini 3.1 Pro / Nano Banana Pro / Daily Brief / Gemini Omni video and 200 Google Flow Credits. |
| Google AI Pro          | $19.99  | $199.99 | Google   | gemini-app, gemini-cli       | <cite index="40-2">$19.99/month for higher access to Gemini 3 Pro, Deep Research, image generation with Nano Banana Pro, and limited Veo 3.1 Fast video generation, plus 1,000 monthly AI credits</cite>; includes 2 TB Google One storage and YouTube Premium Lite. |
| Google AI Ultra ($100) | $99.99  | —      | Google    | gemini-app, gemini-cli       | <cite index="22-2,22-3">Developer-focused $100/month AI Ultra plan with 5X higher usage limits than the Pro plan in the Gemini app and Google Antigravity, Gemini 3.5 Flash integration, priority access to Antigravity, 20TB of cloud storage, and YouTube Premium individual plan</cite>. |
| Google AI Ultra ($200) | $199.99 | —      | Google    | gemini-app, gemini-cli       | <cite index="39-3">$199.99/month tier with 20x higher usage limits vs. AI Pro and first access to advanced features like Deep Think and Gemini Spark</cite>; <cite index="22-3">price reduced from $250 to $200</cite>; 25,000 monthly AI credits and 30 TB Google One storage. |
| Cursor Pro             | $20     | $192   | Cursor    | cursor                       | <cite index="31-25,31-26,31-27">$20 monthly credit pool across frontier models with optional on-demand purchase; Auto routing usage is unlimited and does not draw from the credit pool</cite>. |
| Cursor Pro+            | $60     | $576   | Cursor    | cursor                       | <cite index="32-22,32-23">$60/month with 3x the usage credits compared to Pro, otherwise identical features</cite>; same model coverage as Pro at roughly 3x the OpenAI / Claude / Gemini usage budget. |
| Cursor Ultra           | $200    | $1920  | Cursor    | cursor                       | <cite index="29-1,29-2">Top individual tier at $200/month with roughly 20 times the usage of Pro and priority access to new features</cite>; same model coverage as Pro. |


The "Access methods unlocked" column references method ids enumerated in
the `<access-methods>` block of
[`docs/model-selector.txt`](model-selector.txt). The dollar values are
list prices at time of writing; verify against each provider's billing
page before publishing.

Subscriptions whose surface is web-chat-only (no CLI / IDE / API path
beyond a chat box) are intentionally omitted — only subscriptions that
unlock at least one access method enumerated in `<access-methods>`
appear here.

---

## Existing model-selector.txt Classification Audit


| Model (file id)  | Output  | Correct Tier | Current Tier | Status |
| ---------------- | ------- | ------------ | ------------ | ------ |
| opus-4.7         | $25.00  | Very High    | Very High    | ✓      |
| opus-4.8         | $25.00  | Very High    | Very High    | ✓      |
| claude-fable-5   | $50.00  | Very High    | Very High    | ✓      |
| gpt-5.5          | $30.00  | Very High    | Very High    | ✓      |
| sonnet-4.6       | $15.00  | High         | High         | ✓      |
| gpt-5.4          | $15.00  | High         | High         | ✓      |
| gpt-5.3-codex    | $14.00  | Medium       | Medium       | ✓      |
| gpt-5.2          | $14.00  | Medium       | Medium       | ✓      |
| gemini-3.1-pro   | $12.00  | Medium       | Medium       | ✓      |
| gemini-3-pro     | $12.00  | Medium       | Medium       | ✓      |
| gpt-5            | $10.00  | Medium       | Medium       | ✓      |
| gpt-5.1-codex    | $10.00  | Medium       | Medium       | ✓      |
| gemini-3.5-flash | $9.00   | Low          | Low          | ✓      |
| composer-2       | $2.50   | Low          | Low          | ✓      |
| composer-2.5     | $2.50   | Low          | Low          | ✓      |
| gemini-2.5-flash | $2.50   | Low          | Low          | ✓      |
| gemini-3-flash   | $3.00   | Low          | Low          | ✓      |
| grok-4.3         | $2.50   | Low          | Low          | ✓      |
| kimi-k2.5        | $3.00   | Low          | Low          | ✓      |
| claude-4.5-haiku | $5.00   | Low          | Low          | ✓      |
| gpt-5-mini       | $2.00   | Low          | Low          | ✓      |
| gpt-5.4-mini     | $4.50   | Low          | Low          | ✓      |
| gpt-5.4-nano     | $1.25   | Low          | Low          | ✓      |
| glm-5.2          | $4.40   | Low          | Low          | ✓      |
| glm-4.6          | $2.20   | Low          | Low          | ✓      |
| glm-4.5-air      | $1.10   | Low          | Low          | ✓      |
| deepseek-v4-pro  | $0.87   | Low          | Low          | ✓      |
| deepseek-v4-flash | $0.28  | Low          | Low          | ✓      |
| mistral-medium-3.5 | $7.50 | Low          | Low          | ✓      |
| mistral-small-4  | $0.30   | Low          | Low          | ✓      |
| mistral-large-3  | $1.50   | Low          | Low          | ✓      |
| codestral        | $0.90   | Low          | Low          | ✓      |
| gpt-oss-120b     | $0.60   | Low          | Low          | ✓      |
| gpt-oss-20b      | $0.30   | Low          | Low          | ✓      |


Routing meta-models (Cursor's "Auto" / "Premium" modes; analogous
routers from other providers) are intentionally NOT enumerated in
`docs/model-selector.txt` `<model-options>`. The catalog tracks fixed-
engine models only — a routing model's benchmarks, jurisdiction, and
cost are by construction unknowable in advance, which conflicts with
the selector's per-model tier ratings and the jurisdiction filter
(see `<jurisdiction-context>` in `docs/model-selector.txt` for the
rationale). The "Auto + Composer Pool" table at the top of this
document continues to document Cursor's billing-pool rate for
reference, since that rate determines how Composer 2 / Composer 2.5
calls bill against the pool — but the `auto` and `premium` model
ids no longer appear as recommendable engines.

## Recently Added / Updated Models


| Model id         | Output | Tier      | Change                                                                                                                     |
| ---------------- | ------ | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| glm-5.2          | $4.40  | Low       | New 2026-06-27 in cost-scale — z.ai's GLM 5.2 now visible on Cursor's pricing page (provider header "Z.ai"); already present in `<model-options>` via provider-direct `zai-api` method, prices preserved per the Federation rule (provider-direct catalog owns input/output) |
| grok-4.3         | $2.50  | Low       | New — supersedes grok-4.20 in selector list                                                                                |
| gemini-2.5-flash | $2.50  | Low       | New — added 2026-05-21; cheap multimodal Flash model now visible in `<model-options>` for SaaS-backend free-tier picks      |
| gemini-3-flash   | $3.00  | Low       | New — added 2026-05-21; Gemini 3 generation Flash variant; previously Hidden-by-default on Cursor's pricing page            |
| gemini-3-pro     | $12.00 | Medium    | New — added 2026-05-21; Gemini 3 generation Pro variant alongside gemini-3.1-pro                                            |
| gemini-3.5-flash | $9.00  | Low       | New — added 2026-05-24; Gemini 3.5 Flash visible (un-hidden) on Cursor's pricing page; AA Intelligence Index 55.3 (high reasoning) places it as the strongest Flash-tier Gemini |
| gpt-5            | $10.00 | Medium    | New — added 2026-05-21; baseline GPT-5 family flagship                                                                      |
| gpt-5-mini       | $2.00  | Low       | New — added 2026-05-21; cheapest GPT-5 family variant ($2.00/M output)                                                      |
| gpt-5.1-codex    | $10.00 | Medium    | New — added 2026-05-21; earlier-generation Codex variant at $10/M output                                                    |
| composer-2.5     | $2.50  | Low       | New — added 2026-05-21; Composer 2 successor (same output price, equal-output-price replacement rule)                       |
| kimi-k2.5        | $3.00  | Low       | New — added 2026-05-21; Moonshot's Kimi K2.5 (routed via Cursor pool; no direct Moonshot access method enumerated yet)      |
| opus-4.8         | $25.00 | Very High | Benchmarks indexed 2026-06-04 — AA Intelligence Index 61.4 (#1), HLE 45.7%, Terminal-Bench Hard 58.3, τ²-bench retail 94.4%; tier-agentic bumped from A to S based on Terminal-Bench Hard + τ²-bench evidence |
| grok-build-0.1   | $2.00  | Low       | New 2026-05-28 in cost-scale — xAI's Grok Build 0.1 visible on Cursor pricing page; `<model-options>` entry deferred until benchmark sources index it (no published benchmarks yet) |
| auto             | —      | —         | REMOVED 2026-05-21; Cursor-managed routing meta-model. Opaque routing conflicts with per-model tier ratings + jurisdiction filter |
| premium          | —      | —         | REMOVED 2026-05-21; Cursor-managed routing meta-model. Same rationale as `auto` removal                                     |


---

## Provider Jurisdictions

The selector's [`<jurisdiction-context>`](model-selector.txt) filter
consumes this reference table when applying the user's allowed-
jurisdictions list. Each row maps a provider HQ to an ISO-3166-1
alpha-2-style code; the `jurisdiction` attribute on every
`<model>` in `<model-options>` and the `provider-jurisdiction`
attribute on every `<method>` in `<access-methods>` derive from
this table.


| Provider HQ name              | Jurisdiction code | Models in catalog                                                                                                       |
| ----------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Anthropic (San Francisco, US) | `us`              | opus-4.8, opus-4.7, sonnet-4.6, claude-4.5-haiku                                                                        |
| OpenAI (San Francisco, US)    | `us`              | gpt-5.5, gpt-5.4, gpt-5.3-codex, gpt-5.2, gpt-5.1-codex, gpt-5, gpt-5.4-mini, gpt-5.4-nano, gpt-5-mini                  |
| Google (Mountain View, US)    | `us`              | gemini-3.1-pro, gemini-3-pro, gemini-3.5-flash, gemini-3-flash, gemini-2.5-flash                                        |
| xAI (Palo Alto, US)           | `us`              | grok-4.3                                                                                                                |
| Cursor (San Francisco, US)    | `us`              | composer-2, composer-2.5 — note: base weights for these Composer models derive from Moonshot's Kimi K2 series; Cursor's operator status determines the jurisdiction code per `<jurisdiction-context>` (data flow governed by Cursor's privacy policy and US law) |
| Moonshot AI (Beijing, CN)     | `cn`              | kimi-k2.5                                                                                                               |
| DeepSeek (Hangzhou, CN)       | `cn`              | deepseek-v4-pro, deepseek-v4-flash                                                                                      |
| z.ai / Zhipu AI (Beijing, CN) | `cn`              | glm-5.2, glm-4.6, glm-4.5-air                                                                                           |
| Mistral AI (Paris, FR/EU)     | `eu`              | mistral-medium-3.5, mistral-small-4, mistral-large-3, codestral                                                         |
| Groq (Mountain View, US)      | `us`              | gpt-oss-120b, gpt-oss-20b (hosts OpenAI's open-weight gpt-oss; pinned host that defines per-token price + access)        |


Notes on the mapping:

- The jurisdiction code reflects the **operator** — the entity whose
  terms govern the data flow when a call is placed — not the base-
  weight origin. Composer 2 / Composer 2.5 are `us` because Cursor
  operates them; the Moonshot lineage is disclosed in the model's
  `best-for` for users whose compliance posture cares about base-
  weight origin.
- Newly-detected providers default to `unknown` per
  [`update/prompt.md`](../update/prompt.md)'s auto-add rule;
  maintainer fills them in editorially after one refresh cycle.
- This table is the source of truth — the per-model `jurisdiction`
  attribute and the per-method `provider-jurisdiction` attribute
  in `model-selector.txt` MUST match the codes in this table
  byte-for-byte. CI tests enforce the cross-doc invariant.
