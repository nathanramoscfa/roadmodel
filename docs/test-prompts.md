# roadmodel test prompts

A growable set of prompts for exercising the `/recommend` page on
`roadmodel.ai` — so you can test each model tier, thinking mode, Max Mode, and
platform without inventing a prompt every time.

**How these were chosen.** Each prompt is deliberately unambiguous for its
target (per the selector algorithm in `docs/model-selector.txt`), then
**validated live against the signed-in frontier engine** (Gemini 2.5 Pro — what
you get when signed in) by firing it twice and confirming the recommendation is
stable. The recommender is somewhat non-deterministic, so "reliable" means both
runs agreed; the flaky ones are called out.

> Validation date: 2026-06-06, signed-in (frontier) path. Re-validate after an
> engine change (`RECOMMENDER_FRONTIER_ENABLED`, a roadmodel package bump, or a
> catalog refresh). The anonymous/free tier (Gemini 2.5 Flash) is less stable
> and may pick differently.

## Reliable prompts (both runs agreed)

| Target | Prompt | Reliably recommends |
|---|---|---|
| **Opus 4.x + Claude Code + Orchestration** | Design and plan a from-scratch migration of our 200-service monolith to an event-driven architecture across 4 regions, resolving every consistency, rollback, and data-ownership trade-off with justification. | Opus 4.8 / Claude Code / thinking On (Ultracode in the rationale) |
| **Opus (rigorous knowledge)** | Rigorously prove the Cauchy–Schwarz inequality from first principles and explain the intuition behind each step. | Opus 4.x / Claude Code / On *(4.7↔4.8 is a true tie)* |
| **GPT-5.3 Codex (terminal coding)** | Refactor this 30-file Go microservice entirely from the terminal: extract packages, add unit tests, and fix the build, working through the CLI. | GPT-5.3 Codex / Codex |
| **Gemini 3.1 Pro (multimodal / long-context, Max Mode)** | Analyze a 2-hour product demo video together with its full transcript and 80 slides, and synthesize the top user-experience risks across all three. | Gemini 3.1 Pro / Cursor / Max Mode On |
| **Sonnet 4.6 (structured tool-use)** | Implement a well-specified multi-step ETL pipeline that makes reliable tool calls across 10 REST APIs, following the provided spec exactly. | Sonnet 4.6 / Cursor |
| **Grok 4.3 (2M long-context)** | Search and cross-reference a 1.8-million-token legal contract corpus for internal contradictions, keeping cost low. | Grok 4.3 / Cursor |
| **Cheapest / fastest (speed)** | Classify 50,000 short tweets as positive or negative sentiment, as fast and cheaply as possible; accuracy is secondary. | GPT-5.4 Nano / OpenAI API / thinking Off |
| **Trivial (thinking N/A)** | What is the capital of France? | GPT-5.4 Nano / Cursor / N/A |

## How the output axes show up (so you can target them)

- **Thinking:** `Off` on trivial/speed prompts; `On` / an effort level on Claude
  Code picks (Opus); **`N/A` on any Cursor or OpenAI-API pick** (those surfaces
  don't expose the thinking dial). The finer `XHigh` vs `High` distinction lives
  in the rationale *text*, not the settings chip.
- **Max Mode:** only appears on **Cursor** picks (it is a Cursor-surface
  concept). The Gemini-multimodal and Grok long-context prompts turn it On.
- **Orchestration (Ultracode):** the big migration/planning prompt is the
  trigger (PRIMARY planning + cross-cutting scope + High complexity + Claude
  Code).

## Known-flaky targets (use with awareness)

- **GPT-5.5 specifically** — an autonomous-agent prompt (e.g. "Build a fully
  autonomous agent that monitors production logs, diagnoses incidents, and
  remediates with no human in the loop") flips **GPT-5.5 ↔ Opus 4.8**. Both are
  agentic-S; the engine can't reliably break the tie.
- **Composer 2.5** — routine multi-file edits (e.g. "rename a variable across 12
  files") get **escalated to Codex/Opus**, not Composer. The frontier engine
  over-escalates routine work (the `#185` over-quality residual on the frontier
  tier; tracked by the soak). Hard to trigger Composer reliably right now.

## Re-validating / extending

Add a row here when you find a reliable prompt. To re-validate the whole set
against the current engine, fire each prompt at `/api/recommend` with a
signed-in session twice and confirm the model + platform are stable (the
`scripts/soak-recommend.ts` harness is the reusable basis).
