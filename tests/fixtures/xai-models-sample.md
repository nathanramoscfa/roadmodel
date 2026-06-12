<!--
Faithful slice of https://docs.x.ai/developers/models.md — the token-pricing
table plus an image-pricing table (header "Model | Cost") to prove the parser
locates the token table by its "Input / 1M tokens" / "Output / 1M tokens" header
and ignores the others. Only grok-4.3 is in the selector; grok-4.20-* /
grok-build are not mapped. Refresh from the live docs if expectations change.
-->
## Language models

| Model | Context | Input / 1M tokens | Output / 1M tokens |
| --- | --- | --- | --- |
| grok-4.3 | 1M | $1.25 | $2.50 |
| grok-4.3 | 1M | $1.25 | $2.50 |
| grok-4.20-0309-reasoning | 1M | $1.25 | $2.50 |
| grok-build-0.1 | 256k | $1.00 | $2.00 |

*Prices shown per million tokens*

## Image generation

| Model | Cost |
| --- | --- |
| grok-imagine-image | $0.02 / image |
| grok-imagine-image-quality | $0.05 / image |
