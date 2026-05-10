<!-- AUTO-GENERATED. DO NOT EDIT.
Source of truth: docs/model-selector.txt
Regenerate with: python update/render_md.py
-->

# Model Selector

Human-readable rendering of [`docs/model-selector.txt`](model-selector.txt). The `.txt` is the
single source of truth; this file is regenerated from it by
[`update/render_md.py`](../update/render_md.py). Edit the `.txt` and
rerun the renderer.

## Instruction

When this file is referenced with @model-selector.txt, you MUST:
1. Execute the requested task in full — write the roadmap, plan, or
   whatever the user asked for
2. For every prompt or step you write as part of that task, append a
   model selection block immediately before it using the criteria in this
   file (objective, pricing, Max Mode, benchmark sources, task categories,
   model options, selection algorithm, and conversation principles)
3. The selection block is part of the task output, not a replacement for it

## Usage

Reference this file alongside any task. The AI performs the task and
annotates each prompt it writes with the appropriate model selection
block drawn from the criteria in this file.

## Objective

**PRIMARY:** Maximize quality. Recommend the highest-quality model whose
strengths match the prompt's task type, regardless of cost. If Opus 4.7
in Max Mode is the most appropriate fit for a given prompt, recommend
Opus 4.7 in Max Mode.

**SECONDARY (tie-breaker only):** When two or more models are tied in
expected quality for the prompt's task type, recommend the one with the
lower output price per 1M tokens.

Quality always wins. Cost only resolves true ties — never near-ties,
never "close enough." The user is paying for access to every tier and
expects the best outcome for each prompt.

## Pricing Context

All prices below are per 1M tokens, sourced from Cursor's published API
pricing. Use these prices solely as a tie-breaker after the quality
decision is made.

Cost interpretation:
- Output price is the dominant cost driver for code generation, full
  implementations, comprehensive plans, and any long-form response.
- Input price matters most when feeding large context — long files,
  repo-wide search results, multimodal payloads, or sprawling document
  corpora.
- Cache-read price (typically ~10% of input) only matters for sustained
  sessions with reusable system prompts or persistent context.
- Tier placement is based solely on output price per 1M tokens:
  Low &lt; $10, Medium $10–$14.99, High $15–$24.99, Very High ≥ $25.

Routing models (`premium`, `auto`) have variable cost — `auto` draws
from the Auto + Composer pool at ~$6.00/M output; `premium` routes to
the strongest available model and bills at that model's API rate.

## Max Mode Context

Max Mode extends a model's context window to the maximum it supports,
giving the model deeper codebase understanding and producing better
results on complex tasks.

Billing:
- Token-based pricing at the model's API rate; consumes usage faster
  than the default context window.
- Individual plans: billed at the model's API rate (no surcharge).
- Teams plans: non-Auto requests include the Cursor Token Rate.
- Legacy request-based plans: Max Mode adds a 20% surcharge.

Enable Max Mode when ANY of the following hold:
- Complexity is High on the selection-algorithm scoring.
- Primary or secondary task category is `long-context` (large repo,
  multi-file ingestion, full-codebase reasoning).
- Task is a `planning` prompt with many interacting concerns or
  cross-cutting architectural decisions.
- Prompt explicitly requires extended reasoning, deep multi-step
  analysis, or chain-of-thought across many files.

Disable Max Mode for direct, bounded prompts — single-file edits,
isolated bug fixes, well-defined refactors, simple questions, or any
task where default context comfortably fits the inputs.

## Benchmark Sources

Authoritative LLM leaderboards the AI may cite when justifying a model
recommendation. When reasoning about a model's strength in a task
category, ground the rationale in one of these sources by name.

- LMArena — human-preference Elo across general chat (chatbot-arena.com)
- Artificial Analysis Intelligence Index — composite of 10 evaluations
  including GPQA Diamond, Humanity's Last Exam, SciCode,
  Terminal-Bench Hard, and AA-Omniscience
- Aider polyglot — coding across C++, Go, Java, JavaScript, Python, Rust
- SWE-bench Verified — real GitHub issues, 500-instance human-filtered
  subset; gold standard for software-engineering capability
- LiveCodeBench — contamination-free coding benchmark with rolling
  problems from LeetCode / AtCoder / Codeforces; complements
  SWE-bench by measuring algorithmic problem-solving on items the
  models could not have trained on
- τ²-bench — agentic / tool-use benchmark with a real tool–agent–user
  loop across airline, retail, and banking domains (Sierra Research)
- LiveBench — contamination-resistant multi-domain benchmark
- Terminal-Bench 2.0 — terminal and agent task execution
- GPQA Diamond — graduate-level science reasoning
- AIME — advanced math olympiad problems
- MMMU — multimodal university-level understanding
- HLE (Humanity's Last Exam) — frontier-difficulty general intelligence
- CursorBench — Cursor's proprietary benchmark built from real coding
  sessions with terse prompts and multi-file solutions

## Task Categories

Classify every prompt into one primary category from this list. If the
prompt spans two categories, list both and use the more demanding one
as primary; the other becomes the secondary category for tie-breaking.

- coding — implementation, debugging, refactoring, multi-file edits,
  writing tests, fixing build/lint errors
- planning — architecture decisions, design docs, multi-step plans,
  ambiguity resolution, trade-off analysis, roadmap construction
- agentic — autonomous tool use, terminal commands, long-running
  multi-step execution, end-to-end agent loops
- multimodal — image, video, audio, or screenshot understanding
  alongside text or code
- long-context — large repo or file ingestion, codebase-wide reasoning,
  multi-document synthesis, sustained sessions with persistent context
- knowledge — domain expertise, factual recall, cross-domain accuracy,
  grounded research, low-hallucination requirements
- speed — latency-sensitive completions, high-volume routine work,
  autocomplete-style tasks where wall-clock time dominates utility

## Model Options

Each model entry carries: pricing, S/A/B/C/D tier ratings across the
seven task categories, headline benchmark numbers grounded in the
sources above, and a free-text best-for description.

Tier ratings:
- S — top-1 or top-2 globally in this category
- A — strong, reliable, near-frontier
- B — competent for the category
- C — limited; usable only for trivial work in the category
- D — not suited; do not select for this category

### Very High Cost Tier

#### Opus 4.7 — `opus-4.7`

- **Pricing:** Input $5.00/M · Output $25.00/M
- **Tier ratings:** Coding **S** · Planning **S** · Agentic **A** · Multimodal **A** · Long-context **S** · Knowledge **S** · Speed **D**
- **Headline benchmarks:** AA Intelligence Index 57.3 (#2); LMArena Text #1 (Elo 1503); LMArena WebDev #1 (Elo 1570); AA-Omniscience 26.2 (#2)
- **Pricing notes:** Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching

#### GPT-5.5 — `gpt-5.5`

- **Pricing:** Input $5.00/M · Output $30.00/M
- **Tier ratings:** Coding **S** · Planning **S** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **A** · Speed **D**
- **Headline benchmarks:** AA Intelligence Index 60.2 (#1); LMArena Text Elo 1484 (#8); HLE 25.3%; AA-Omniscience 20.1 (#3)
- **Pricing notes:** Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing
- **Best for:** OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination

### High Cost Tier

#### Sonnet 4.6 — `sonnet-4.6`

- **Pricing:** Input $3.00/M · Output $15.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 51.7; LMArena WebDev Elo 1524 (#6); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage
- **Pricing notes:** Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation

#### GPT-5.4 — `gpt-5.4`

- **Pricing:** Input $2.50/M · Output $15.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **S** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 56.8 (#4); LMArena Text Elo 1485 (#11); GPT-5.4 (xhigh) Output Speed 80.9 tokens/s; lowest factual error rate among GPT models
- **Pricing notes:** Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing
- **Best for:** Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding

### Medium Cost Tier

#### GPT-5.3 Codex — `gpt-5.3-codex`

- **Pricing:** Input $1.75/M · Output $14.00/M
- **Tier ratings:** Coding **S** · Planning **B** · Agentic **S** · Multimodal **D** · Long-context **B** · Knowledge **B** · Speed **B**
- **Headline benchmarks:** GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding
- **Pricing notes:** Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high
- **Best for:** Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed

#### Gemini 3.1 Pro — `gemini-3.1-pro`

- **Pricing:** Input $2.00/M · Output $12.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **A** · Multimodal **S** · Long-context **S** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 38.3% (#1); LMArena Text Elo 1492 (#4); 1M-token context
- **Pricing notes:** -
- **Best for:** True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category

#### Premium (Intelligence) — `premium`

- **Pricing:** Input varies (routes to top-tier model) · Output varies (routes to top-tier model)
- **Tier ratings:** Coding **inherit** · Planning **inherit** · Agentic **inherit** · Multimodal **inherit** · Long-context **inherit** · Knowledge **inherit** · Speed **inherit**
- **Headline benchmarks:** Inherits the routed model's benchmarks
- **Pricing notes:** Cursor-managed routing mode; bills at the routed model's API rate; carries that model's pricing-notes for the duration of the request
- **Best for:** Cursor auto-selects the strongest available model; best when the task is clearly high-complexity but does not map to one specific model's niche advantage, or when you are uncertain which frontier model's strengths best apply

### Low Cost Tier

#### Composer 2 (Fast) — `composer-2`

- **Pricing:** Input $0.50/M · Output $2.50/M
- **Tier ratings:** Coding **A** · Planning **B** · Agentic **A** · Multimodal **D** · Long-context **B** · Knowledge **B** · Speed **S**
- **Headline benchmarks:** CursorBench 61.3 (+37% over Composer 1.5); SWE-bench Multilingual 73.7; Terminal-Bench 2.0 61.7
- **Pricing notes:** -
- **Best for:** Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient

#### Grok 4.3 — `grok-4.3`

- **Pricing:** Input $1.25/M · Output $2.50/M
- **Tier ratings:** Coding **B** · Planning **A** · Agentic **S** · Multimodal **B** · Long-context **S** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 24.5%; LMArena Search Elo 1205
- **Pricing notes:** Requires Max Mode on request-based plans
- **Best for:** Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist

#### Auto (Efficiency) — `auto`

- **Pricing:** Input ~$1.25/M (Auto + Composer pool) · Output ~$6.00/M (Auto + Composer pool)
- **Tier ratings:** Coding **B** · Planning **C** · Agentic **B** · Multimodal **C** · Long-context **C** · Knowledge **C** · Speed **A**
- **Headline benchmarks:** No fixed benchmarks — Cursor routes to a balanced model per request
- **Pricing notes:** Cursor-managed routing across the Auto + Composer pool; not a fixed model
- **Best for:** Simple, well-defined, bounded tasks — routine edits, boilerplate generation, direct questions, and standard refactors where any competent model suffices and manual model selection adds no value

#### Claude 4.5 Haiku — `claude-4.5-haiku`

- **Pricing:** Input $1.00/M · Output $5.00/M
- **Tier ratings:** Coding **B** · Planning **B** · Agentic **B** · Multimodal **B** · Long-context **B** · Knowledge **B** · Speed **S**
- **Headline benchmarks:** AA Intelligence Index 37.1; Output Speed 100.2 tokens/s; AA-Omniscience -4.2; latency leader among Claude family
- **Pricing notes:** Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x
- **Best for:** Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning

#### GPT-5.4 Mini — `gpt-5.4-mini`

- **Pricing:** Input $0.75/M · Output $4.50/M
- **Tier ratings:** Coding **B** · Planning **C** · Agentic **C** · Multimodal **B** · Long-context **B** · Knowledge **B** · Speed **A**
- **Headline benchmarks:** AA Intelligence Index 48.9 (xhigh); Output Speed 154.9 tokens/s; HLE 19.4% (GPT-5-mini)
- **Pricing notes:** Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens
- **Best for:** Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price

#### GPT-5.4 Nano — `gpt-5.4-nano`

- **Pricing:** Input $0.20/M · Output $1.25/M
- **Tier ratings:** Coding **C** · Planning **D** · Agentic **D** · Multimodal **C** · Long-context **C** · Knowledge **C** · Speed **S**
- **Headline benchmarks:** Cheapest GPT-5 family variant; throughput-optimized inference
- **Pricing notes:** Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens
- **Best for:** Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal

## Selection Algorithm

Run this procedure for every prompt that needs a model recommendation.
Quality wins at every step; cost only enters at step 5.

Step 1 — Classify the prompt's task category.
  Pick exactly one PRIMARY category from `<task-categories>`. If the
  prompt clearly spans two, also pick a SECONDARY category and use the
  more demanding one as PRIMARY. Examples:
    - "Implement a multi-file refactor" → PRIMARY coding
    - "Design the auth architecture for our app" → PRIMARY planning
    - "Investigate the screenshot and fix the layout bug" → PRIMARY
      multimodal, SECONDARY coding
    - "Audit the entire repo for race conditions" → PRIMARY
      long-context, SECONDARY coding

Step 2 — Score complexity dimensions.
  Rate each dimension Low / Medium / High:
    - Complexity (how many interacting concerns)
    - Ambiguity (judgment calls or trade-offs needed)
    - Scope (localized vs cross-cutting)
    - Novelty (known pattern vs creative problem-solving)
  Take the maximum of the four ratings as the overall complexity level.

Step 3 — Set the minimum acceptable tier rating in PRIMARY.
    - Overall complexity High → require S in the PRIMARY category
    - Overall complexity Medium → require A or better
    - Overall complexity Low → B or better is acceptable

Step 4 — Filter and rank candidates by quality.
  Filter the model list to those meeting the minimum rating in PRIMARY.
  Among survivors, prefer the model with the highest tier rating in
  PRIMARY. If multiple models tie at the top of PRIMARY, break the tie
  by rating in SECONDARY. If still tied, break by overall coverage —
  number of S/A ratings across the seven categories.

Step 5 — Apply the cost tie-breaker.
  Only if step 4 produced two or more models with identical PRIMARY
  and SECONDARY ratings, recommend the one with the lower
  `output-price-per-1m`. Never use cost to demote a higher-quality
  model.

Step 6 — Decide Max Mode.
  Enable Max Mode iff any of these hold:
    - Overall complexity is High
    - PRIMARY or SECONDARY is `long-context`
    - PRIMARY is `planning` with cross-cutting scope
    - Prompt explicitly requires extended reasoning across many files
  Otherwise leave Max Mode Off.

Guardrails:
  - Never sacrifice quality to save cost — the cost step is a true-tie
    resolver, not a downgrade trigger.
  - For PRIMARY = `multimodal`, only consider models with tier-multimodal
    of S or A (currently: gemini-3.1-pro at S; gpt-5.4, sonnet-4.6,
    opus-4.7, gpt-5.5 at A).
  - For PRIMARY = `long-context`, prefer models with native large
    context (opus-4.7 1M, gemini-3.1-pro 1M, grok-4.3 2M) over forcing
    a smaller-context model into Max Mode truncation.
  - For PRIMARY = `coding` at S-tier requirement, the candidate set is
    gpt-5.3-codex, opus-4.7, gpt-5.5; cost tie-breaker favors
    gpt-5.3-codex when the ratings are equivalent for the prompt.
  - Default to composer-2 for routine multi-file implementation when a
    coding-A rating suffices; escalate only on a concrete capability
    gap.

## Conversation Principles

- Start a New conversation when the prompt is self-contained and carries no dependency on prior turns, when switching to a significantly different domain or task type, or when accumulated context from earlier steps would add noise and increase cost without improving output quality.
- Continue the current conversation when the prompt explicitly builds on decisions, outputs, or context established in immediately prior steps — for example, iterating on a file just created, referencing a plan just written, or following up on an error just encountered.
- In roadmap annotation, treat each phase or major feature boundary as a natural New conversation break unless sequential steps within that phase share tight context dependencies.
- When in doubt, prefer New. A clean context produces more focused, higher-quality results than a bloated one — and input cost scales linearly with context size.

## Output Format

CRITICAL: Respond in EXACTLY this format and ABSOLUTELY NOTHING ELSE.
Do not add any preamble, explanation, or perform any actions.

Single-prompt mode — output one block:

MODEL: [Model Name]
MAX MODE: [On/Off]
CONVERSATION: [New/Continue]
RATIONALE: [1-2 sentences that MUST name (a) the prompt's PRIMARY task
            category, (b) the recommended model's tier rating in that
            category, (c) at least one headline benchmark or named
            leaderboard from <benchmark-sources> supporting the choice,
            and (d) the cost tie-breaker outcome if step 5 of the
            selection-algorithm applied. Also note the conversation
            handling decision.]

Roadmap annotation mode — output one block per prompt, preceded by the
prompt identifier or a brief label, in order:

MODEL: [Model Name]
MAX MODE: [On/Off]
CONVERSATION: [New/Continue]
RATIONALE: [1-2 sentences that MUST name (a) the prompt's PRIMARY task
            category, (b) the recommended model's tier rating in that
            category, (c) at least one headline benchmark or named
            leaderboard from <benchmark-sources> supporting the choice,
            and (d) the cost tie-breaker outcome if step 5 of the
            selection-algorithm applied. Also note the conversation
            handling decision.]
PROMPT: [Prompt # or short label]
