# Recommender engine differential eval

Probes: 12 · baseline: `gemini-2.5-pro` · anon context (user_context_text=None)

## Summary

| engine | GA | parsed | lat(s) | healthy | on-catalog | fields | sections | no-leak | no-demote | pick-agree vs base |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `gemini-2.5-flash` | GA | 12/12 | 3.1 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | None |
| `gpt-5-mini` | GA | 12/12 | 6.9 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | None |
| `ollama:gemma3:12b` | preview | 10/12 | 11.8 | 0.8 | 0.7 | 1.0 | 0.9 | 1.0 | 1.0 | None |
| `ollama:qwen3-vl-64k` | preview | 0/4 | — | — | — | — | — | — | — | _ProviderCallError: Ollama response contained reasoning but no visible text (the model spent its whole output budget thinking). Raise --max-output-tokens or disable thinking with -_ |
| `ollama:qwen3-vl-64k@8192` | preview | 0/1 | — | — | — | — | — | — | — | _ProviderCallError: Ollama response contained reasoning but no visible text (the model spent its whole output budget thinking). Raise --max-output-tokens or disable thinking with -_ |

## Per-probe Quality pick (model) by engine

| probe | `gemini-2.5-flash` | `gpt-5-mini` | `ollama:gemma3:12b` |
|---|---|---|---|
| creative | Claude Opus 5 | Fable 5.1 | — |
| coding-cli | Claude Opus 5 | Fable 5.1 | Claude Opus 5 |
| planning | Claude Opus 5 | Fable 5.1 | — |
| data-analysis | Claude Fable 5.1 | Fable 5.1 | Claude Opus 5 |
| legacy-refactor | Claude Fable 5.1 | Fable 5.1 | Claude Opus 5 |
| math-proof | Claude Fable 5.1 | Claude Opus 5 | Claude Opus 5 |
| vision-ocr | Claude Fable 5.1 | Fable 5.1 | Claude Opus 5 |
| ambiguous | Claude Opus 5 | Claude Fable 5.1 | Claude 3 Opus |
| non-english | Claude Opus 5 | Fable 5.1 | Claude Opus 5 |
| cost-bulk | Claude Sonnet 5 | Gemini 3.1 Pro | Claude Opus 5 |
| fenced-json | Claude Opus 5 | Fable 5.1 | Claude 3 Opus |
| agentic-tooluse | Claude Fable 5.1 | Fable 5.1 | Claude Opus 5 |
