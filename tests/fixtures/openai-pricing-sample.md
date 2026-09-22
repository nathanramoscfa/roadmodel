<!--
Faithful slice of https://developers.openai.com/api/docs/pricing.md — the
Markdown pricing tables that replaced the old JS/JSX `rows={[...]}` arrays
(docs migration, 2026-09), used to test update/extract_openai_catalog.py
offline. Includes the STANDARD table and a BATCH table (same model names at
half price) to prove the parser scopes to the "### Standard pricing data"
heading and ignores the discounted panes; a `-pro` row and gpt-5.1 (declined,
not mapped) to prove they are skipped silently; and `gpt-6-astra` plus a
synthetic `gpt-7-nova` to prove an unmapped, undeclined model is FLAGGED in
unexpected_slugs rather than dropped. Refresh from the live docs if the
parser's expectations change.
-->

Prices per 1M tokens.

Standard

### Standard pricing data

| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7-nova | $12.00 | $1.20 | $15.00 | $60.00 | $24.00 | $2.40 | $30.00 | $90.00 |
| gpt-6-astra | $10.00 | $1.00 | $12.50 | $50.00 | $20.00 | $2.00 | $25.00 | $75.00 |
| gpt-5.6-sol | $4.00 | $0.40 | $5.00 | $20.00 | $8.00 | $0.80 | $10.00 | $30.00 |
| gpt-5.6-terra | $2.00 | $0.20 | $2.50 | $12.00 | $4.00 | $0.40 | $5.00 | $18.00 |
| gpt-5.6-luna | $0.20 | $0.02 | $0.25 | $1.20 | $0.40 | $0.04 | $0.50 | $1.80 |
| gpt-5.5 (<272K context length) | $5.00 | $0.50 | - | $30.00 | $10.00 | $1.00 | - | $45.00 |
| gpt-5.5-pro (<272K context length) | $30.00 | - | - | $180.00 | $60.00 | - | - | $270.00 |
| gpt-5.4 (<272K context length) | $2.50 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |
| gpt-5.4-mini | $0.75 | $0.075 | - | $4.50 | $1.50 | $0.15 | - | $6.75 |
| gpt-5.4-nano | $0.20 | $0.02 | - | $1.25 | $0.40 | $0.04 | - | $1.88 |
| gpt-5.2 | $1.75 | $0.175 | - | $14.00 | $3.50 | $0.35 | - | $21.00 |
| gpt-5.1 | $1.25 | $0.125 | - | $10.00 | $2.50 | $0.25 | - | $15.00 |
| gpt-5 | $1.25 | $0.125 | - | $10.00 | $2.50 | $0.25 | - | $15.00 |
| gpt-5-mini | $0.25 | $0.025 | - | $2.00 | $0.50 | $0.05 | - | $3.00 |
| gpt-4o-2024-05-13 | $5.00 | - | - | $15.00 | $10.00 | - | - | $22.50 |
| o3 | $2.00 | $0.50 | - | $8.00 | $4.00 | $1.00 | - | $12.00 |

Batch

### Batch pricing data

| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-astra | $5.00 | $0.50 | $6.25 | $25.00 | $10.00 | $1.00 | $12.50 | $37.50 |
| gpt-5.5 (<272K context length) | $2.50 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |
| gpt-5.4-mini | $0.375 | $0.0375 | - | $2.25 | $0.75 | $0.075 | - | $3.38 |
