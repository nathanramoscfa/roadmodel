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
| Composer 2       | $0.50 | –           | $0.20      | $2.50  | Low  | -     |
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
| Claude 4.7 Opus             | $5.00  | $6.25       | $0.50      | $25.00  | Very High | Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge) |


### API Pool — Cursor Composer


| Model        | Input | Cache Write | Cache Read | Output | Tier   | Notes             |
| ------------ | ----- | ----------- | ---------- | ------ | ------ | ----------------- |
| Composer 1   | $1.25 | –           | $0.125     | $10.00 | Medium | Hidden by default |
| Composer 1.5 | $3.50 | –           | $0.35      | $17.50 | High   | Hidden by default |
| Composer 2   | $0.50 | –           | $0.20      | $2.50  | Low    | -                 |


### API Pool — Google (Gemini)


| Model                      | Input | Cache Write | Cache Read | Output | Tier   | Notes |
| -------------------------- | ----- | ----------- | ---------- | ------ | ------ | ----- |
| Gemini 2.5 Flash           | $0.30 | –           | $0.03      | $2.50  | Low    | Hidden by default |
| Gemini 3 Flash             | $0.50 | –           | $0.05      | $3.00  | Low    | Hidden by default |
| Gemini 3 Pro               | $2.00 | –           | $0.20      | $12.00 | Medium | Hidden by default |
| Gemini 3 Pro Image Preview | $2.00 | –           | $0.20      | $12.00 | Medium | Hidden by default; Native image generation model optimized for speed, flexibility, and contextual understanding; Text input and output priced the same as Gemini 3 Pro; Image output: $120/1M tokens (~$0.134 per 1K/2K image, ~$0.24 per 4K image); Preview models may change before becoming stable and have more restrictive rate limits |
| Gemini 3.1 Pro             | $2.00 | –           | $0.20      | $12.00 | Medium | -                 |


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


### API Pool — xAI / Moonshot


| Model     | Input | Cache Write | Cache Read | Output | Tier | Notes |
| --------- | ----- | ----------- | ---------- | ------ | ---- | ----- |
| Grok 4.20 | $2.00 | –           | $0.20      | $6.00  | Low  | Hidden by default; The cost is 2x when the input exceeds 200k tokens |
| Grok 4.3  | $1.25 | –           | $0.20      | $2.50  | Low  | Requires Max Mode on request-based plans |
| Kimi K2.5 | $0.60 | –           | $0.10      | $3.00  | Low  | Hidden by default |


---

## Existing model-selector.txt Classification Audit


| Model (file id)  | Output  | Correct Tier | Current Tier | Status |
| ---------------- | ------- | ------------ | ------------ | ------ |
| opus-4.7         | $25.00  | Very High    | Very High    | ✓      |
| gpt-5.5          | $30.00  | Very High    | Very High    | ✓      |
| sonnet-4.6       | $15.00  | High         | High         | ✓      |
| gpt-5.4          | $15.00  | High         | High         | ✓      |
| gpt-5.3-codex    | $14.00  | Medium       | Medium       | ✓      |
| gemini-3.1-pro   | $12.00  | Medium       | Medium       | ✓      |
| premium          | N/A*    | Medium       | Medium       | ✓      |
| composer-2       | $2.50   | Low          | Low          | ✓      |
| grok-4.3         | $2.50   | Low          | Low          | ✓      |
| auto             | ~$6.00* | Low          | Low          | ✓      |
| claude-4.5-haiku | $5.00   | Low          | Low          | ✓      |
| gpt-5.4-mini     | $4.50   | Low          | Low          | ✓      |
| gpt-5.4-nano     | $1.25   | Low          | Low          | ✓      |


*`premium` and `auto` are Cursor-managed routing modes without a fixed output
price. They are classified by their intended use position (premium = strongest
available routing; auto = cost-efficient routing at the Auto + Composer pool
rate of $6.00/M output).

## Recently Added / Updated Models


| Model id  | Output | Tier | Change                                      |
| --------- | ------ | ---- | ------------------------------------------- |
| grok-4.3  | $2.50  | Low  | New — supersedes grok-4.20 in selector list |
