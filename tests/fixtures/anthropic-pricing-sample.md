<!--
Faithful slice of https://platform.claude.com/docs/en/about-claude/pricing.md —
the standard per-token pricing table, used to test
update/extract_anthropic_catalog.py offline. Includes a non-selector model
(Mythos 5), a deprecated row, and a SECOND (Batch API) table at half price to
prove the parser locates the STANDARD table by its "Base Input Tokens" /
"Output Tokens" header and ignores the others. Also includes Sonnet 5's TWO
time-boxed rows (introductory vs standard), which label the period inside the
NAME cell — the shape that made a plain name lookup miss the model entirely.
Refresh from the live docs if the parser's expectations change.
-->
The following table shows pricing for all Claude models:

| Model             | Base Input Tokens | 5m Cache Writes | 1h Cache Writes | Cache Hits & Refreshes | Output Tokens |
|-------------------|-------------------|-----------------|-----------------|----------------------|---------------|
| Claude Fable 5      | $10 / MTok        | $12.50 / MTok   | $20 / MTok      | $1 / MTok | $50 / MTok    |
| Claude Mythos 5 ([limited availability](https://anthropic.com/glasswing)) | $10 / MTok | $12.50 / MTok | $20 / MTok | $1 / MTok | $50 / MTok |
| Claude Opus 4.8     | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok | $25 / MTok    |
| Claude Opus 4.7     | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok | $25 / MTok    |
| Claude Opus 4.1 ([deprecated](/docs/en/about-claude/model-deprecations)) | $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |
| Claude Sonnet 5 [through August 31, 2026](/docs/en/about-claude/pricing#claude-sonnet-5-introductory-pricing) | $2 / MTok | $2.50 / MTok | $4 / MTok | $0.20 / MTok | $10 / MTok |
| Claude Sonnet 5 starting September 1, 2026 | $3 / MTok | $3.75 / MTok | $6 / MTok | $0.30 / MTok | $15 / MTok |
| Claude Sonnet 4.6   | $3 / MTok         | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok | $15 / MTok    |
| Claude Haiku 4.5  | $1 / MTok         | $1.25 / MTok    | $2 / MTok       | $0.10 / MTok | $5 / MTok     |

### Batch API

Batch processing is 50% off standard rates:

| Model           | Input        | Output        |
|-----------------|--------------|---------------|
| Claude Opus 4.8 | $2.50 / MTok | $12.50 / MTok |
| Claude Fable 5  | $5 / MTok     | $25 / MTok    |
