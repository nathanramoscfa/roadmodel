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
All prices are per 1M tokens.

### Auto + Composer Pool


| Model             | Input | Cache Write | Cache Read | Output | Tier |
| ----------------- | ----- | ----------- | ---------- | ------ | ---- |
| Composer 2        | $0.50 | –           | $0.20      | $2.50  | Low  |
| Composer 2 (Fast) | $1.50 | –           | $0.35      | $7.50  | Low  |
| Auto (pool rate)  | $1.25 | $1.25       | $0.25      | $6.00  | Low  |


### API Pool — Anthropic (Claude)


| Model                  | Input  | Cache Write | Cache Read | Output  | Tier |
| ---------------------- | ------ | ----------- | ---------- | ------- | ---- |
| Claude 4 Sonnet        | $3.00  | $3.75       | $0.30      | $15.00  | High |
| Claude 4 Sonnet 1M     | $6.00  | $7.50       | $0.60      | $22.50  | High |
| Claude 4.5 Haiku       | $1.00  | $1.25       | $0.10      | $5.00   | Low  |
| Claude 4.5 Opus        | $5.00  | $6.25       | $0.50      | $25.00  | Very High |
| Claude 4.5 Sonnet      | $3.00  | $3.75       | $0.30      | $15.00  | High      |
| Claude 4.6 Opus        | $5.00  | $6.25       | $0.50      | $25.00  | Very High |
| Claude 4.6 Opus (Fast) | $30.00 | $37.50      | $3.00      | $150.00 | Very High |
| Claude 4.6 Sonnet      | $3.00  | $3.75       | $0.30      | $15.00  | High      |
| Claude 4.7 Opus        | $5.00  | $6.25       | $0.50      | $25.00  | Very High |


### API Pool — Cursor Composer


| Model        | Input | Cache Write | Cache Read | Output | Tier   |
| ------------ | ----- | ----------- | ---------- | ------ | ------ |
| Composer 1   | $1.25 | –           | $0.125     | $10.00 | Medium |
| Composer 1.5 | $3.50 | –           | $0.35      | $17.50 | High   |
| Composer 2   | $0.50 | –           | $0.20      | $2.50  | Low    |


### API Pool — Google (Gemini)


| Model                      | Input | Cache Write | Cache Read | Output | Tier   |
| -------------------------- | ----- | ----------- | ---------- | ------ | ------ |
| Gemini 2.5 Flash           | $0.30 | –           | $0.03      | $2.50  | Low    |
| Gemini 3 Flash             | $0.50 | –           | $0.05      | $3.00  | Low    |
| Gemini 3 Pro               | $2.00 | –           | $0.20      | $12.00 | Medium |
| Gemini 3 Pro Image Preview | $2.00 | –           | $0.20      | $12.00 | Medium |
| Gemini 3.1 Pro             | $2.00 | –           | $0.20      | $12.00 | Medium |


### API Pool — OpenAI (GPT)


| Model              | Input | Cache Write | Cache Read | Output | Tier   |
| ------------------ | ----- | ----------- | ---------- | ------ | ------ |
| GPT-5              | $1.25 | –           | $0.125     | $10.00 | Medium |
| GPT-5 Fast         | $2.50 | –           | $0.25      | $20.00 | High   |
| GPT-5 Mini         | $0.25 | –           | $0.025     | $2.00  | Low    |
| GPT-5-Codex        | $1.25 | –           | $0.125     | $10.00 | Medium |
| GPT-5.1 Codex      | $1.25 | –           | $0.125     | $10.00 | Medium |
| GPT-5.1 Codex Max  | $1.25 | –           | $0.125     | $10.00 | Medium |
| GPT-5.1 Codex Mini | $0.25 | –           | $0.025     | $2.00  | Low    |
| GPT-5.2            | $1.75 | –           | $0.175     | $14.00 | Medium |
| GPT-5.2 Codex      | $1.75 | –           | $0.175     | $14.00 | Medium |
| GPT-5.3 Codex      | $1.75 | –           | $0.175     | $14.00 | Medium |
| GPT-5.4            | $2.50 | –           | $0.25      | $15.00 | High   |
| GPT-5.4 Mini       | $0.75 | –           | $0.075     | $4.50  | Low    |
| GPT-5.4 Nano       | $0.20 | –           | $0.02      | $1.25  | Low    |
| GPT-5.5            | $5.00 | –           | $0.50      | $30.00 | Very High |


### API Pool — xAI / Moonshot


| Model     | Input | Cache Write | Cache Read | Output | Tier |
| --------- | ----- | ----------- | ---------- | ------ | ---- |
| Grok 4.20 | $2.00 | –           | $0.20      | $6.00  | Low  |
| Grok 4.3  | $1.25 | –           | $0.20      | $2.50  | Low  |
| Kimi K2.5 | $0.60 | –           | $0.10      | $3.00  | Low  |


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
