<!-- AUTO-GENERATED. DO NOT EDIT.
Source of truth: docs/model-selector.txt
Regenerate with: python update/render_md.py
-->

# roadmodel

Human-readable rendering of [`docs/model-selector.txt`](model-selector.txt). The `.txt` is the
single source of truth; this file is regenerated from it by
[`update/render_md.py`](../update/render_md.py). Edit the `.txt` and
rerun the renderer.

## Instruction

When this file is referenced with @model-selector.txt, you MUST:
1. Execute the requested task in full — write the roadmap, plan, or
   whatever the user asked for
2. Read docs/user-context.md to learn the user-specific subscription
   state, API keys, and platform preference order. These are the
   inputs the access-selection step consumes; without them the
   PLATFORM and THINKING fields in the output cannot be filled
   truthfully
3. For every prompt or step you write as part of that task, append a
   model selection block immediately before it using the criteria in
   this file (objective, pricing, Max Mode, thinking, benchmark
   sources, task categories, model options, access methods,
   selection algorithm, access selection, and conversation
   principles)
4. The selection block is part of the task output, not a replacement
   for it

## Usage

Reference this file alongside any task. The AI performs the task and
annotates each prompt it writes with the appropriate model selection
block drawn from the criteria in this file. Each block reports
MODEL, PLATFORM, MAX MODE, THINKING, CONVERSATION, and RATIONALE —
model choice from `<selection-algorithm>`, platform (access method)
choice from `<access-selection>`, with the user-specific subscription
and API-key state read from docs/user-context.md.

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

The per-token rates above are only one dimension of cost. Access
methods (see `<access-methods>`) bundle the same models behind
subscriptions and shared token pools where the marginal cost per
call is effectively $0 until the subscription budget is exhausted.
docs/model-tier-cost-scale.md carries a "Subscription Tiers" section
covering Cursor Pro/Ultra, claude.ai Max, ChatGPT Plus/Pro, Gemini
Advanced, and similar flat-monthly plans. The `<access-selection>`
step picks the cheapest effective path for the user's specific
subscription state — burning sunk-cost subscription budget before
pay-per-token spend is the default posture.

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

Max Mode is a Cursor-surface concept. Access methods outside Cursor
(Anthropic API, Claude Code, Codex, Google API, Gemini CLI,
direct provider APIs) do not expose a Max Mode toggle; they either
accept the model's full native context window by default or expose
a different long-context surface. When the chosen PLATFORM is not
a Cursor surface, MAX MODE in the output should read `Off` (or
`N/A` if the model offers no equivalent extended-context mode).

## Thinking Context

Thinking (also called extended thinking, reasoning effort, or
thinking budget) lets a model spend internal reasoning tokens before
producing its visible response. Providers expose the toggle
differently:

- Claude (Anthropic API, Claude Code, claude.ai): "Extended
  thinking" on/off with a configurable thinking-token budget. Off
  by default for chat; On for hard reasoning tasks.
- OpenAI (Codex, OpenAI API, ChatGPT advanced controls):
  reasoning-effort knob — `minimal`, `low`, `medium`, `high`.
  Higher effort spends more reasoning tokens before visible
  output.
- Gemini (Google API, Gemini CLI): thinking-budget setting in
  tokens.
- Cursor: usually inherits the underlying model's thinking
  behavior but does not expose the toggle in the IDE surface
  (true in both Composer mode and Chat mode).

Output mapping (the THINKING field of the output format):
`Off` / `Low` / `Medium` / `High` / `XHigh` / `N/A`. Map
provider-native scales onto this 6-state field:

- Claude extended thinking Off → `Off`; On with a small/medium
  budget → `Medium`; On with a large budget → `High`; On with a
  very large budget → `XHigh`.
- OpenAI `minimal` → `Off`; `low` → `Low`; `medium` → `Medium`;
  `high` → `High`; `xhigh` / `extra-high` (the high-reasoning
  Codex / GPT variant, e.g. `gpt-5.3-codex-high`) → `XHigh`.
- Gemini thinking-budget 0 → `Off`; small → `Low`; medium →
  `Medium`; large → `High`; very large → `XHigh`.
- `N/A` when the chosen access method does not expose a thinking
  toggle (e.g. Cursor — neither its Composer mode nor its Chat
  mode surfaces the dial), regardless of whether the underlying
  model supports one.

Decision rule (applied during `<access-selection>` Step E):
- Overall complexity from `<selection-algorithm>` Step 2 Low →
  THINKING `Off`.
- Overall complexity Medium → THINKING `Medium`.
- Overall complexity High → THINKING `High`.
- High complexity AND the prompt involves novel problem-solving,
  multi-step proof / verification, or chain-of-thought across
  many files (i.e., the conditions that would push
  `<selection-algorithm>` Step 3 to require S-tier in PRIMARY) →
  THINKING `XHigh`.
- PRIMARY task category `planning` or `knowledge` with
  cross-cutting scope → bump THINKING up at least one level
  (`Off` → `Low`, `Low` → `Medium`, `Medium` → `High`, `High` →
  `XHigh`).
- Chosen access method's `exposes-thinking` attribute is `no` →
  THINKING `N/A`, overriding the above.

Thinking and Max Mode are orthogonal: a Cursor call may have
Max Mode On and THINKING `N/A` (Cursor does not expose the
thinking toggle); a Claude Code call may have Max Mode Off and
THINKING `High` (Anthropic's surface exposes thinking, not Max
Mode).

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
- **Headline benchmarks:** AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1478.7); LMArena WebDev #2 (Elo 1559.3); AA-Omniscience 26.2 (#2)
- **Pricing notes:** Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching

#### GPT-5.5 — `gpt-5.5`

- **Pricing:** Input $5.00/M · Output $30.00/M
- **Tier ratings:** Coding **S** · Planning **S** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **A** · Speed **D**
- **Headline benchmarks:** AA Intelligence Index 60.2 (#1); LMArena Text Elo 1462.5 (#14); HLE 44.3%; AA-Omniscience 20.1 (#3)
- **Pricing notes:** Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing
- **Best for:** OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination

### High Cost Tier

#### Sonnet 4.6 — `sonnet-4.6`

- **Pricing:** Input $3.00/M · Output $15.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 51.7; LMArena WebDev Elo 1523.6 (#6); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage
- **Pricing notes:** Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation

#### GPT-5.4 — `gpt-5.4`

- **Pricing:** Input $2.50/M · Output $15.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **S** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 56.8 (#4); LMArena Text Elo 1454.1 (#18); GPT-5.4 (xhigh) Output Speed 80.5 tokens/s; lowest factual error rate among GPT models
- **Pricing notes:** Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing
- **Best for:** Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding

### Medium Cost Tier

#### GPT-5.3 Codex — `gpt-5.3-codex`

- **Pricing:** Input $1.75/M · Output $14.00/M
- **Tier ratings:** Coding **S** · Planning **B** · Agentic **S** · Multimodal **D** · Long-context **B** · Knowledge **B** · Speed **B**
- **Headline benchmarks:** GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding
- **Pricing notes:** Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high
- **Best for:** Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed

#### GPT-5.2 — `gpt-5.2`

- **Pricing:** Input $1.75/M · Output $14.00/M
- **Tier ratings:** Coding **B** · Planning **A** · Agentic **B** · Multimodal **C** · Long-context **A** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** MMLU Pro 81.4; GPQA 71.2; LiveCodeBench 66.9; 400K-token context; output speed 68 tokens/s; released 2025-12-10
- **Pricing notes:** Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high
- **Best for:** Earlier-flagship GPT reasoning model (December 2025) with 400K context and broad knowledge coverage (GPQA 71.2, MMLU Pro 81.4); same medium-tier pricing as GPT-5.3 Codex but lacks Codex's autonomous-coding specialization — pick gpt-5.3-codex over gpt-5.2 for coding/agentic tasks; gpt-5.2 fits when broad reasoning at A-tier knowledge and a 400K context window are the primary need at the medium price tier

#### Gemini 3.1 Pro — `gemini-3.1-pro`

- **Pricing:** Input $2.00/M · Output $12.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **A** · Multimodal **S** · Long-context **S** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1483.6 (#4); 1M-token context
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
- **Pricing notes:** Hidden by default
- **Best for:** Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient

#### Grok 4.3 — `grok-4.3`

- **Pricing:** Input $1.25/M · Output $2.50/M
- **Tier ratings:** Coding **B** · Planning **A** · Agentic **S** · Multimodal **B** · Long-context **S** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189
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
- **Headline benchmarks:** AA Intelligence Index 37.1; Output Speed 138.4 tokens/s; AA-Omniscience -4.2; latency leader among Claude family
- **Pricing notes:** Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x
- **Best for:** Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning

#### GPT-5.4 Mini — `gpt-5.4-mini`

- **Pricing:** Input $0.75/M · Output $4.50/M
- **Tier ratings:** Coding **B** · Planning **C** · Agentic **C** · Multimodal **B** · Long-context **B** · Knowledge **B** · Speed **A**
- **Headline benchmarks:** AA Intelligence Index 48.9 (xhigh); Output Speed 162.9 tokens/s; HLE 19.4% (GPT-5-mini)
- **Pricing notes:** Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens
- **Best for:** Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price

#### GPT-5.4 Nano — `gpt-5.4-nano`

- **Pricing:** Input $0.20/M · Output $1.25/M
- **Tier ratings:** Coding **C** · Planning **D** · Agentic **D** · Multimodal **C** · Long-context **C** · Knowledge **C** · Speed **S**
- **Headline benchmarks:** Cheapest GPT-5 family variant; throughput-optimized inference
- **Pricing notes:** Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens
- **Best for:** Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal

## Access Methods

`) bundle the same models behind
    subscriptions and shared token pools where the marginal cost per
    call is effectively $0 until the subscription budget is exhausted.
    docs/model-tier-cost-scale.md carries a "Subscription Tiers" section
    covering Cursor Pro/Ultra, claude.ai Max, ChatGPT Plus/Pro, Gemini
    Advanced, and similar flat-monthly plans. The `<access-selection>`
    step picks the cheapest effective path for the user's specific
    subscription state — burning sunk-cost subscription budget before
    pay-per-token spend is the default posture.
  </pricing-context>

  <max-mode-context>
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

    Max Mode is a Cursor-surface concept. Access methods outside Cursor
    (Anthropic API, Claude Code, Codex, Google API, Gemini CLI,
    direct provider APIs) do not expose a Max Mode toggle; they either
    accept the model's full native context window by default or expose
    a different long-context surface. When the chosen PLATFORM is not
    a Cursor surface, MAX MODE in the output should read `Off` (or
    `N/A` if the model offers no equivalent extended-context mode).
  </max-mode-context>

  <thinking-context>
    Thinking (also called extended thinking, reasoning effort, or
    thinking budget) lets a model spend internal reasoning tokens before
    producing its visible response. Providers expose the toggle
    differently:

    - Claude (Anthropic API, Claude Code, claude.ai): "Extended
      thinking" on/off with a configurable thinking-token budget. Off
      by default for chat; On for hard reasoning tasks.
    - OpenAI (Codex, OpenAI API, ChatGPT advanced controls):
      reasoning-effort knob — `minimal`, `low`, `medium`, `high`.
      Higher effort spends more reasoning tokens before visible
      output.
    - Gemini (Google API, Gemini CLI): thinking-budget setting in
      tokens.
    - Cursor: usually inherits the underlying model's thinking
      behavior but does not expose the toggle in the IDE surface
      (true in both Composer mode and Chat mode).

    Output mapping (the THINKING field of the output format):
    `Off` / `Low` / `Medium` / `High` / `XHigh` / `N/A`. Map
    provider-native scales onto this 6-state field:

    - Claude extended thinking Off → `Off`; On with a small/medium
      budget → `Medium`; On with a large budget → `High`; On with a
      very large budget → `XHigh`.
    - OpenAI `minimal` → `Off`; `low` → `Low`; `medium` → `Medium`;
      `high` → `High`; `xhigh` / `extra-high` (the high-reasoning
      Codex / GPT variant, e.g. `gpt-5.3-codex-high`) → `XHigh`.
    - Gemini thinking-budget 0 → `Off`; small → `Low`; medium →
      `Medium`; large → `High`; very large → `XHigh`.
    - `N/A` when the chosen access method does not expose a thinking
      toggle (e.g. Cursor — neither its Composer mode nor its Chat
      mode surfaces the dial), regardless of whether the underlying
      model supports one.

    Decision rule (applied during `<access-selection>` Step E):
    - Overall complexity from `<selection-algorithm>` Step 2 Low →
      THINKING `Off`.
    - Overall complexity Medium → THINKING `Medium`.
    - Overall complexity High → THINKING `High`.
    - High complexity AND the prompt involves novel problem-solving,
      multi-step proof / verification, or chain-of-thought across
      many files (i.e., the conditions that would push
      `<selection-algorithm>` Step 3 to require S-tier in PRIMARY) →
      THINKING `XHigh`.
    - PRIMARY task category `planning` or `knowledge` with
      cross-cutting scope → bump THINKING up at least one level
      (`Off` → `Low`, `Low` → `Medium`, `Medium` → `High`, `High` →
      `XHigh`).
    - Chosen access method's `exposes-thinking` attribute is `no` →
      THINKING `N/A`, overriding the above.

    Thinking and Max Mode are orthogonal: a Cursor call may have
    Max Mode On and THINKING `N/A` (Cursor does not expose the
    thinking toggle); a Claude Code call may have Max Mode Off and
    THINKING `High` (Anthropic's surface exposes thinking, not Max
    Mode).
  </thinking-context>

  <benchmark-sources>
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
  </benchmark-sources>

  <task-categories>
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
  </task-categories>

  <model-options>
    Each model entry carries: pricing, S/A/B/C/D tier ratings across the
    seven task categories, headline benchmark numbers grounded in the
    sources above, and a free-text best-for description.

    Tier ratings:
    - S — top-1 or top-2 globally in this category
    - A — strong, reliable, near-frontier
    - B — competent for the category
    - C — limited; usable only for trivial work in the category
    - D — not suited; do not select for this category

    <tier cost="very-high">
      <model id="opus-4.7" name="Opus 4.7"
             input-price-per-1m="$5.00" output-price-per-1m="$25.00"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1478.7); LMArena WebDev #2 (Elo 1559.3); AA-Omniscience 26.2 (#2)"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching" />
      <model id="gpt-5.5" name="GPT-5.5"
             input-price-per-1m="$5.00" output-price-per-1m="$30.00"
             tier-coding="S" tier-planning="S" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 60.2 (#1); LMArena Text Elo 1462.5 (#14); HLE 44.3%; AA-Omniscience 20.1 (#3)"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination" />
    </tier>
    <tier cost="high">
      <model id="sonnet-4.6" name="Sonnet 4.6"
             input-price-per-1m="$3.00" output-price-per-1m="$15.00"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 51.7; LMArena WebDev Elo 1523.6 (#6); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation" />
      <model id="gpt-5.4" name="GPT-5.4"
             input-price-per-1m="$2.50" output-price-per-1m="$15.00"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="S"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 56.8 (#4); LMArena Text Elo 1454.1 (#18); GPT-5.4 (xhigh) Output Speed 80.5 tokens/s; lowest factual error rate among GPT models"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding" />
    </tier>
    <tier cost="medium">
      <model id="gpt-5.3-codex" name="GPT-5.3 Codex"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             tier-coding="S" tier-planning="B" tier-agentic="S"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high"
             best-for="Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed" />
      <model id="gpt-5.2" name="GPT-5.2"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             tier-coding="B" tier-planning="A" tier-agentic="B"
             tier-multimodal="C" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="MMLU Pro 81.4; GPQA 71.2; LiveCodeBench 66.9; 400K-token context; output speed 68 tokens/s; released 2025-12-10"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high"
             best-for="Earlier-flagship GPT reasoning model (December 2025) with 400K context and broad knowledge coverage (GPQA 71.2, MMLU Pro 81.4); same medium-tier pricing as GPT-5.3 Codex but lacks Codex's autonomous-coding specialization — pick gpt-5.3-codex over gpt-5.2 for coding/agentic tasks; gpt-5.2 fits when broad reasoning at A-tier knowledge and a 400K context window are the primary need at the medium price tier" />
      <model id="gemini-3.1-pro" name="Gemini 3.1 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1483.6 (#4); 1M-token context"
             pricing-notes="-"
             best-for="True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category" />
      <model id="premium" name="Premium (Intelligence)"
             input-price-per-1m="varies (routes to top-tier model)"
             output-price-per-1m="varies (routes to top-tier model)"
             tier-coding="inherit" tier-planning="inherit" tier-agentic="inherit"
             tier-multimodal="inherit" tier-long-context="inherit"
             tier-knowledge="inherit" tier-speed="inherit"
             headline-benchmarks="Inherits the routed model's benchmarks"
             pricing-notes="Cursor-managed routing mode; bills at the routed model's API rate; carries that model's pricing-notes for the duration of the request"
             best-for="Cursor auto-selects the strongest available model; best when the task is clearly high-complexity but does not map to one specific model's niche advantage, or when you are uncertain which frontier model's strengths best apply" />
    </tier>
    <tier cost="low">
      <model id="composer-2" name="Composer 2 (Fast)"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="CursorBench 61.3 (+37% over Composer 1.5); SWE-bench Multilingual 73.7; Terminal-Bench 2.0 61.7"
             pricing-notes="Hidden by default"
             best-for="Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient" />
      <model id="grok-4.3" name="Grok 4.3"
             input-price-per-1m="$1.25" output-price-per-1m="$2.50"
             tier-coding="B" tier-planning="A" tier-agentic="S"
             tier-multimodal="B" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189"
             pricing-notes="Requires Max Mode on request-based plans"
             best-for="Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist" />
      <model id="auto" name="Auto (Efficiency)"
             input-price-per-1m="~$1.25 (Auto + Composer pool)"
             output-price-per-1m="~$6.00 (Auto + Composer pool)"
             tier-coding="B" tier-planning="C" tier-agentic="B"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="A"
             headline-benchmarks="No fixed benchmarks — Cursor routes to a balanced model per request"
             pricing-notes="Cursor-managed routing across the Auto + Composer pool; not a fixed model"
             best-for="Simple, well-defined, bounded tasks — routine edits, boilerplate generation, direct questions, and standard refactors where any competent model suffices and manual model selection adds no value" />
      <model id="claude-4.5-haiku" name="Claude 4.5 Haiku"
             input-price-per-1m="$1.00" output-price-per-1m="$5.00"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 37.1; Output Speed 138.4 tokens/s; AA-Omniscience -4.2; latency leader among Claude family"
             pricing-notes="Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x"
             best-for="Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning" />
      <model id="gpt-5.4-mini" name="GPT-5.4 Mini"
             input-price-per-1m="$0.75" output-price-per-1m="$4.50"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="A"
             headline-benchmarks="AA Intelligence Index 48.9 (xhigh); Output Speed 162.9 tokens/s; HLE 19.4% (GPT-5-mini)"
             pricing-notes="Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens"
             best-for="Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price" />
      <model id="gpt-5.4-nano" name="GPT-5.4 Nano"
             input-price-per-1m="$0.20" output-price-per-1m="$1.25"
             tier-coding="C" tier-planning="D" tier-agentic="D"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5 family variant; throughput-optimized inference"
             pricing-notes="Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens"
             best-for="Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal" />
    </tier>
  </model-options>

  <access-methods>
    Each access method is a way to run one or more models from
    `<model-options>`. Methods differ in (a) which models they expose,
    (b) how billing works (per-token, subscription-included,
    subscription-pool, subscription-or-key), (c) which capability
    toggles (Max Mode, thinking) they expose, and (d) what credentials
    the user must hold.

    The `<access-selection>` algorithm consumes this list together with
    the user-specific state in docs/user-context.md to pick a PLATFORM
    for the chosen model.

    Billing types:
    - subscription-included — a flat-monthly plan with a usage budget
      pool that the call draws from at $0 marginal cost until the
      budget is exhausted (e.g. claude.ai Max, ChatGPT Plus).
    - subscription-pool — a flat-monthly plan with a shared token pool
      consumed across many models (e.g. Cursor Ultra). $0 marginal
      cost until the pool is exhausted.
    - subscription-or-key — surface accepts either a subscription OR a
      direct API key; if a subscription is active, prefer it.
    - per-token — pay-per-token at the provider's published API rate.

### Anthropic

#### Anthropic API — `anthropic-api`

- **Billing:** per-token (requires anthropic-api-key)
- **Supports models:** opus-4.7,sonnet-4.6,claude-4.5-haiku
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Programmatic / scripted Claude use outside Claude Code — raw API headers, batch endpoints, or features not surfaced by Claude Code. Falls back here when claude.ai Max budget is exhausted.

#### Claude Code — `claude-code`

- **Billing:** subscription-or-key (requires claude-max-subscription OR anthropic-api-key)
- **Supports models:** opus-4.7,sonnet-4.6,claude-4.5-haiku
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Default for Claude coding or terminal tasks when a claude.ai Max subscription is active — $0 marginal cost until the Max budget is exhausted, full tool-use surface, runs as a CLI and as an IDE extension inside Cursor. Heavy Opus usage that would cost over $1,000/mo on per-token API is fully covered by a $100/mo Max plan.

#### claude.ai web / desktop — `claude-web`

- **Billing:** subscription-included (requires claude-max-subscription)
- **Supports models:** opus-4.7,sonnet-4.6,claude-4.5-haiku
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Chat-driven Claude use (no terminal, no codebase tool use) under the same Max budget that funds Claude Code — pick when the task is conversational rather than code-editing.

### OpenAI

#### OpenAI API — `openai-api`

- **Billing:** per-token (requires openai-api-key)
- **Supports models:** gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.4-mini,gpt-5.4-nano
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Programmatic / scripted GPT use when an OpenAI API key is configured. Pay-per-token at OpenAI's published rates.

#### Codex — `codex-cli`

- **Billing:** subscription-or-key (requires chatgpt-subscription OR openai-api-key)
- **Supports models:** gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.4-mini
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Default for GPT-driven autonomous coding sessions when a ChatGPT Plus/Pro subscription is active — pays from the ChatGPT budget instead of the per-token API rate. Best surface for gpt-5.3-codex on long-running terminal / agentic work.

#### ChatGPT (web / desktop) — `chatgpt-app`

- **Billing:** subscription-included (requires chatgpt-subscription)
- **Supports models:** gpt-5.5,gpt-5.4,gpt-5.4-mini
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Chat-driven GPT use without terminal or IDE integration; subscription-funded so marginal cost is $0 until ChatGPT's usage limits kick in.

### Google

#### Google AI Studio API — `google-api`

- **Billing:** per-token (requires google-api-key)
- **Supports models:** gemini-3.1-pro
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Programmatic / scripted Gemini use with a Google API key. Pay-per-token at Google's published rates.

#### Gemini CLI — `gemini-cli`

- **Billing:** subscription-or-key (requires gemini-advanced-subscription OR google-api-key)
- **Supports models:** gemini-3.1-pro
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Terminal-driven Gemini use; the CLI surface for multimodal and long-context Gemini work outside Cursor's pool.

#### Gemini (web / app) — `gemini-app`

- **Billing:** subscription-included (requires gemini-advanced-subscription)
- **Supports models:** gemini-3.1-pro
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Chat-driven Gemini use under the Gemini Advanced subscription budget.

### xAI

#### xAI API — `xai-api`

- **Billing:** per-token (requires xai-api-key)
- **Supports models:** grok-4.3
- **Toggles:** Max Mode — no · Thinking — no
- **Best for:** Direct Grok API access for 2M-context or hallucination-resistant tasks; pay-per-token at xAI's published rates.

### Cursor

#### Cursor — `cursor`

- **Billing:** subscription-pool (requires cursor-pro-or-ultra-subscription)
- **Supports models:** opus-4.7,gpt-5.5,sonnet-4.6,gpt-5.4,gpt-5.3-codex,gemini-3.1-pro,premium,grok-4.3,claude-4.5-haiku,gpt-5.4-mini,gpt-5.4-nano,composer-2,auto
- **Toggles:** Max Mode — yes · Thinking — no
- **Best for:** Cursor IDE — single Platform covering both UI modes (Composer for multi-file autonomous editing; Chat for interactive model-picker). The operator picks the mode at task time based on the chosen Model: composer-2 / auto / premium imply Composer mode; frontier models (opus-4.7, gpt-5.5, sonnet-4.6, etc.) imply Chat mode. All routes through the $0-marginal Cursor pool. Defer to claude-code when the chosen model is Claude and claude.ai Max is active (Max budget is cheaper marginal cost than burning Cursor pool tokens on Claude calls that have a dedicated Anthropic subscription path).

## Selection Algorithm

`, platform (access method)
    choice from `<access-selection>`, with the user-specific subscription
    and API-key state read from docs/user-context.md.
  </usage>

  <objective>
    PRIMARY: Maximize quality. Recommend the highest-quality model whose
    strengths match the prompt's task type, regardless of cost. If Opus 4.7
    in Max Mode is the most appropriate fit for a given prompt, recommend
    Opus 4.7 in Max Mode.

    SECONDARY (tie-breaker only): When two or more models are tied in
    expected quality for the prompt's task type, recommend the one with the
    lower output price per 1M tokens.

    Quality always wins. Cost only resolves true ties — never near-ties,
    never "close enough." The user is paying for access to every tier and
    expects the best outcome for each prompt.
  </objective>

  <pricing-context>
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

    The per-token rates above are only one dimension of cost. Access
    methods (see `<access-methods>`) bundle the same models behind
    subscriptions and shared token pools where the marginal cost per
    call is effectively $0 until the subscription budget is exhausted.
    docs/model-tier-cost-scale.md carries a "Subscription Tiers" section
    covering Cursor Pro/Ultra, claude.ai Max, ChatGPT Plus/Pro, Gemini
    Advanced, and similar flat-monthly plans. The `<access-selection>`
    step picks the cheapest effective path for the user's specific
    subscription state — burning sunk-cost subscription budget before
    pay-per-token spend is the default posture.
  </pricing-context>

  <max-mode-context>
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

    Max Mode is a Cursor-surface concept. Access methods outside Cursor
    (Anthropic API, Claude Code, Codex, Google API, Gemini CLI,
    direct provider APIs) do not expose a Max Mode toggle; they either
    accept the model's full native context window by default or expose
    a different long-context surface. When the chosen PLATFORM is not
    a Cursor surface, MAX MODE in the output should read `Off` (or
    `N/A` if the model offers no equivalent extended-context mode).
  </max-mode-context>

  <thinking-context>
    Thinking (also called extended thinking, reasoning effort, or
    thinking budget) lets a model spend internal reasoning tokens before
    producing its visible response. Providers expose the toggle
    differently:

    - Claude (Anthropic API, Claude Code, claude.ai): "Extended
      thinking" on/off with a configurable thinking-token budget. Off
      by default for chat; On for hard reasoning tasks.
    - OpenAI (Codex, OpenAI API, ChatGPT advanced controls):
      reasoning-effort knob — `minimal`, `low`, `medium`, `high`.
      Higher effort spends more reasoning tokens before visible
      output.
    - Gemini (Google API, Gemini CLI): thinking-budget setting in
      tokens.
    - Cursor: usually inherits the underlying model's thinking
      behavior but does not expose the toggle in the IDE surface
      (true in both Composer mode and Chat mode).

    Output mapping (the THINKING field of the output format):
    `Off` / `Low` / `Medium` / `High` / `XHigh` / `N/A`. Map
    provider-native scales onto this 6-state field:

    - Claude extended thinking Off → `Off`; On with a small/medium
      budget → `Medium`; On with a large budget → `High`; On with a
      very large budget → `XHigh`.
    - OpenAI `minimal` → `Off`; `low` → `Low`; `medium` → `Medium`;
      `high` → `High`; `xhigh` / `extra-high` (the high-reasoning
      Codex / GPT variant, e.g. `gpt-5.3-codex-high`) → `XHigh`.
    - Gemini thinking-budget 0 → `Off`; small → `Low`; medium →
      `Medium`; large → `High`; very large → `XHigh`.
    - `N/A` when the chosen access method does not expose a thinking
      toggle (e.g. Cursor — neither its Composer mode nor its Chat
      mode surfaces the dial), regardless of whether the underlying
      model supports one.

    Decision rule (applied during `<access-selection>` Step E):
    - Overall complexity from `<selection-algorithm>` Step 2 Low →
      THINKING `Off`.
    - Overall complexity Medium → THINKING `Medium`.
    - Overall complexity High → THINKING `High`.
    - High complexity AND the prompt involves novel problem-solving,
      multi-step proof / verification, or chain-of-thought across
      many files (i.e., the conditions that would push
      `<selection-algorithm>` Step 3 to require S-tier in PRIMARY) →
      THINKING `XHigh`.
    - PRIMARY task category `planning` or `knowledge` with
      cross-cutting scope → bump THINKING up at least one level
      (`Off` → `Low`, `Low` → `Medium`, `Medium` → `High`, `High` →
      `XHigh`).
    - Chosen access method's `exposes-thinking` attribute is `no` →
      THINKING `N/A`, overriding the above.

    Thinking and Max Mode are orthogonal: a Cursor call may have
    Max Mode On and THINKING `N/A` (Cursor does not expose the
    thinking toggle); a Claude Code call may have Max Mode Off and
    THINKING `High` (Anthropic's surface exposes thinking, not Max
    Mode).
  </thinking-context>

  <benchmark-sources>
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
  </benchmark-sources>

  <task-categories>
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
  </task-categories>

  <model-options>
    Each model entry carries: pricing, S/A/B/C/D tier ratings across the
    seven task categories, headline benchmark numbers grounded in the
    sources above, and a free-text best-for description.

    Tier ratings:
    - S — top-1 or top-2 globally in this category
    - A — strong, reliable, near-frontier
    - B — competent for the category
    - C — limited; usable only for trivial work in the category
    - D — not suited; do not select for this category

    <tier cost="very-high">
      <model id="opus-4.7" name="Opus 4.7"
             input-price-per-1m="$5.00" output-price-per-1m="$25.00"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1478.7); LMArena WebDev #2 (Elo 1559.3); AA-Omniscience 26.2 (#2)"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching" />
      <model id="gpt-5.5" name="GPT-5.5"
             input-price-per-1m="$5.00" output-price-per-1m="$30.00"
             tier-coding="S" tier-planning="S" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 60.2 (#1); LMArena Text Elo 1462.5 (#14); HLE 44.3%; AA-Omniscience 20.1 (#3)"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination" />
    </tier>
    <tier cost="high">
      <model id="sonnet-4.6" name="Sonnet 4.6"
             input-price-per-1m="$3.00" output-price-per-1m="$15.00"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 51.7; LMArena WebDev Elo 1523.6 (#6); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation" />
      <model id="gpt-5.4" name="GPT-5.4"
             input-price-per-1m="$2.50" output-price-per-1m="$15.00"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="S"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 56.8 (#4); LMArena Text Elo 1454.1 (#18); GPT-5.4 (xhigh) Output Speed 80.5 tokens/s; lowest factual error rate among GPT models"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding" />
    </tier>
    <tier cost="medium">
      <model id="gpt-5.3-codex" name="GPT-5.3 Codex"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             tier-coding="S" tier-planning="B" tier-agentic="S"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high"
             best-for="Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed" />
      <model id="gpt-5.2" name="GPT-5.2"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             tier-coding="B" tier-planning="A" tier-agentic="B"
             tier-multimodal="C" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="MMLU Pro 81.4; GPQA 71.2; LiveCodeBench 66.9; 400K-token context; output speed 68 tokens/s; released 2025-12-10"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high"
             best-for="Earlier-flagship GPT reasoning model (December 2025) with 400K context and broad knowledge coverage (GPQA 71.2, MMLU Pro 81.4); same medium-tier pricing as GPT-5.3 Codex but lacks Codex's autonomous-coding specialization — pick gpt-5.3-codex over gpt-5.2 for coding/agentic tasks; gpt-5.2 fits when broad reasoning at A-tier knowledge and a 400K context window are the primary need at the medium price tier" />
      <model id="gemini-3.1-pro" name="Gemini 3.1 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1483.6 (#4); 1M-token context"
             pricing-notes="-"
             best-for="True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category" />
      <model id="premium" name="Premium (Intelligence)"
             input-price-per-1m="varies (routes to top-tier model)"
             output-price-per-1m="varies (routes to top-tier model)"
             tier-coding="inherit" tier-planning="inherit" tier-agentic="inherit"
             tier-multimodal="inherit" tier-long-context="inherit"
             tier-knowledge="inherit" tier-speed="inherit"
             headline-benchmarks="Inherits the routed model's benchmarks"
             pricing-notes="Cursor-managed routing mode; bills at the routed model's API rate; carries that model's pricing-notes for the duration of the request"
             best-for="Cursor auto-selects the strongest available model; best when the task is clearly high-complexity but does not map to one specific model's niche advantage, or when you are uncertain which frontier model's strengths best apply" />
    </tier>
    <tier cost="low">
      <model id="composer-2" name="Composer 2 (Fast)"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="CursorBench 61.3 (+37% over Composer 1.5); SWE-bench Multilingual 73.7; Terminal-Bench 2.0 61.7"
             pricing-notes="Hidden by default"
             best-for="Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient" />
      <model id="grok-4.3" name="Grok 4.3"
             input-price-per-1m="$1.25" output-price-per-1m="$2.50"
             tier-coding="B" tier-planning="A" tier-agentic="S"
             tier-multimodal="B" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189"
             pricing-notes="Requires Max Mode on request-based plans"
             best-for="Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist" />
      <model id="auto" name="Auto (Efficiency)"
             input-price-per-1m="~$1.25 (Auto + Composer pool)"
             output-price-per-1m="~$6.00 (Auto + Composer pool)"
             tier-coding="B" tier-planning="C" tier-agentic="B"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="A"
             headline-benchmarks="No fixed benchmarks — Cursor routes to a balanced model per request"
             pricing-notes="Cursor-managed routing across the Auto + Composer pool; not a fixed model"
             best-for="Simple, well-defined, bounded tasks — routine edits, boilerplate generation, direct questions, and standard refactors where any competent model suffices and manual model selection adds no value" />
      <model id="claude-4.5-haiku" name="Claude 4.5 Haiku"
             input-price-per-1m="$1.00" output-price-per-1m="$5.00"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 37.1; Output Speed 138.4 tokens/s; AA-Omniscience -4.2; latency leader among Claude family"
             pricing-notes="Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x"
             best-for="Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning" />
      <model id="gpt-5.4-mini" name="GPT-5.4 Mini"
             input-price-per-1m="$0.75" output-price-per-1m="$4.50"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="A"
             headline-benchmarks="AA Intelligence Index 48.9 (xhigh); Output Speed 162.9 tokens/s; HLE 19.4% (GPT-5-mini)"
             pricing-notes="Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens"
             best-for="Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price" />
      <model id="gpt-5.4-nano" name="GPT-5.4 Nano"
             input-price-per-1m="$0.20" output-price-per-1m="$1.25"
             tier-coding="C" tier-planning="D" tier-agentic="D"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5 family variant; throughput-optimized inference"
             pricing-notes="Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens"
             best-for="Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal" />
    </tier>
  </model-options>

  <access-methods>
    Each access method is a way to run one or more models from
    `<model-options>`. Methods differ in (a) which models they expose,
    (b) how billing works (per-token, subscription-included,
    subscription-pool, subscription-or-key), (c) which capability
    toggles (Max Mode, thinking) they expose, and (d) what credentials
    the user must hold.

    The `<access-selection>` algorithm consumes this list together with
    the user-specific state in docs/user-context.md to pick a PLATFORM
    for the chosen model.

    Billing types:
    - subscription-included — a flat-monthly plan with a usage budget
      pool that the call draws from at $0 marginal cost until the
      budget is exhausted (e.g. claude.ai Max, ChatGPT Plus).
    - subscription-pool — a flat-monthly plan with a shared token pool
      consumed across many models (e.g. Cursor Ultra). $0 marginal
      cost until the pool is exhausted.
    - subscription-or-key — surface accepts either a subscription OR a
      direct API key; if a subscription is active, prefer it.
    - per-token — pay-per-token at the provider's published API rate.

    <method id="anthropic-api" name="Anthropic API"
            provider="anthropic" billing="per-token"
            requires="anthropic-api-key"
            supports-models="opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Programmatic / scripted Claude use outside Claude Code — raw API headers, batch endpoints, or features not surfaced by Claude Code. Falls back here when claude.ai Max budget is exhausted." />
    <method id="claude-code" name="Claude Code"
            provider="anthropic" billing="subscription-or-key"
            requires="claude-max-subscription OR anthropic-api-key"
            supports-models="opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Default for Claude coding or terminal tasks when a claude.ai Max subscription is active — $0 marginal cost until the Max budget is exhausted, full tool-use surface, runs as a CLI and as an IDE extension inside Cursor. Heavy Opus usage that would cost over $1,000/mo on per-token API is fully covered by a $100/mo Max plan." />
    <method id="claude-web" name="claude.ai web / desktop"
            provider="anthropic" billing="subscription-included"
            requires="claude-max-subscription"
            supports-models="opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Chat-driven Claude use (no terminal, no codebase tool use) under the same Max budget that funds Claude Code — pick when the task is conversational rather than code-editing." />
    <method id="openai-api" name="OpenAI API"
            provider="openai" billing="per-token"
            requires="openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.4-mini,gpt-5.4-nano"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Programmatic / scripted GPT use when an OpenAI API key is configured. Pay-per-token at OpenAI's published rates." />
    <method id="codex-cli" name="Codex"
            provider="openai" billing="subscription-or-key"
            requires="chatgpt-subscription OR openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.4-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Default for GPT-driven autonomous coding sessions when a ChatGPT Plus/Pro subscription is active — pays from the ChatGPT budget instead of the per-token API rate. Best surface for gpt-5.3-codex on long-running terminal / agentic work." />
    <method id="chatgpt-app" name="ChatGPT (web / desktop)"
            provider="openai" billing="subscription-included"
            requires="chatgpt-subscription"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.4-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Chat-driven GPT use without terminal or IDE integration; subscription-funded so marginal cost is $0 until ChatGPT's usage limits kick in." />
    <method id="google-api" name="Google AI Studio API"
            provider="google" billing="per-token"
            requires="google-api-key"
            supports-models="gemini-3.1-pro"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Programmatic / scripted Gemini use with a Google API key. Pay-per-token at Google's published rates." />
    <method id="gemini-cli" name="Gemini CLI"
            provider="google" billing="subscription-or-key"
            requires="gemini-advanced-subscription OR google-api-key"
            supports-models="gemini-3.1-pro"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Terminal-driven Gemini use; the CLI surface for multimodal and long-context Gemini work outside Cursor's pool." />
    <method id="gemini-app" name="Gemini (web / app)"
            provider="google" billing="subscription-included"
            requires="gemini-advanced-subscription"
            supports-models="gemini-3.1-pro"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Chat-driven Gemini use under the Gemini Advanced subscription budget." />
    <method id="xai-api" name="xAI API"
            provider="xai" billing="per-token"
            requires="xai-api-key"
            supports-models="grok-4.3"
            exposes-max-mode="no" exposes-thinking="no"
            best-for="Direct Grok API access for 2M-context or hallucination-resistant tasks; pay-per-token at xAI's published rates." />
    <method id="cursor" name="Cursor"
            provider="cursor" billing="subscription-pool"
            requires="cursor-pro-or-ultra-subscription"
            supports-models="opus-4.7,gpt-5.5,sonnet-4.6,gpt-5.4,gpt-5.3-codex,gemini-3.1-pro,premium,grok-4.3,claude-4.5-haiku,gpt-5.4-mini,gpt-5.4-nano,composer-2,auto"
            exposes-max-mode="yes" exposes-thinking="no"
            best-for="Cursor IDE — single Platform covering both UI modes (Composer for multi-file autonomous editing; Chat for interactive model-picker). The operator picks the mode at task time based on the chosen Model: composer-2 / auto / premium imply Composer mode; frontier models (opus-4.7, gpt-5.5, sonnet-4.6, etc.) imply Chat mode. All routes through the $0-marginal Cursor pool. Defer to claude-code when the chosen model is Claude and claude.ai Max is active (Max budget is cheaper marginal cost than burning Cursor pool tokens on Claude calls that have a dedicated Anthropic subscription path)." />
  </access-methods>

  <selection-algorithm>
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

## Access Selection

`, with the user-specific subscription
    and API-key state read from docs/user-context.md.
  </usage>

  <objective>
    PRIMARY: Maximize quality. Recommend the highest-quality model whose
    strengths match the prompt's task type, regardless of cost. If Opus 4.7
    in Max Mode is the most appropriate fit for a given prompt, recommend
    Opus 4.7 in Max Mode.

    SECONDARY (tie-breaker only): When two or more models are tied in
    expected quality for the prompt's task type, recommend the one with the
    lower output price per 1M tokens.

    Quality always wins. Cost only resolves true ties — never near-ties,
    never "close enough." The user is paying for access to every tier and
    expects the best outcome for each prompt.
  </objective>

  <pricing-context>
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

    The per-token rates above are only one dimension of cost. Access
    methods (see `<access-methods>`) bundle the same models behind
    subscriptions and shared token pools where the marginal cost per
    call is effectively $0 until the subscription budget is exhausted.
    docs/model-tier-cost-scale.md carries a "Subscription Tiers" section
    covering Cursor Pro/Ultra, claude.ai Max, ChatGPT Plus/Pro, Gemini
    Advanced, and similar flat-monthly plans. The `<access-selection>`
    step picks the cheapest effective path for the user's specific
    subscription state — burning sunk-cost subscription budget before
    pay-per-token spend is the default posture.
  </pricing-context>

  <max-mode-context>
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

    Max Mode is a Cursor-surface concept. Access methods outside Cursor
    (Anthropic API, Claude Code, Codex, Google API, Gemini CLI,
    direct provider APIs) do not expose a Max Mode toggle; they either
    accept the model's full native context window by default or expose
    a different long-context surface. When the chosen PLATFORM is not
    a Cursor surface, MAX MODE in the output should read `Off` (or
    `N/A` if the model offers no equivalent extended-context mode).
  </max-mode-context>

  <thinking-context>
    Thinking (also called extended thinking, reasoning effort, or
    thinking budget) lets a model spend internal reasoning tokens before
    producing its visible response. Providers expose the toggle
    differently:

    - Claude (Anthropic API, Claude Code, claude.ai): "Extended
      thinking" on/off with a configurable thinking-token budget. Off
      by default for chat; On for hard reasoning tasks.
    - OpenAI (Codex, OpenAI API, ChatGPT advanced controls):
      reasoning-effort knob — `minimal`, `low`, `medium`, `high`.
      Higher effort spends more reasoning tokens before visible
      output.
    - Gemini (Google API, Gemini CLI): thinking-budget setting in
      tokens.
    - Cursor: usually inherits the underlying model's thinking
      behavior but does not expose the toggle in the IDE surface
      (true in both Composer mode and Chat mode).

    Output mapping (the THINKING field of the output format):
    `Off` / `Low` / `Medium` / `High` / `XHigh` / `N/A`. Map
    provider-native scales onto this 6-state field:

    - Claude extended thinking Off → `Off`; On with a small/medium
      budget → `Medium`; On with a large budget → `High`; On with a
      very large budget → `XHigh`.
    - OpenAI `minimal` → `Off`; `low` → `Low`; `medium` → `Medium`;
      `high` → `High`; `xhigh` / `extra-high` (the high-reasoning
      Codex / GPT variant, e.g. `gpt-5.3-codex-high`) → `XHigh`.
    - Gemini thinking-budget 0 → `Off`; small → `Low`; medium →
      `Medium`; large → `High`; very large → `XHigh`.
    - `N/A` when the chosen access method does not expose a thinking
      toggle (e.g. Cursor — neither its Composer mode nor its Chat
      mode surfaces the dial), regardless of whether the underlying
      model supports one.

    Decision rule (applied during `<access-selection>` Step E):
    - Overall complexity from `<selection-algorithm>` Step 2 Low →
      THINKING `Off`.
    - Overall complexity Medium → THINKING `Medium`.
    - Overall complexity High → THINKING `High`.
    - High complexity AND the prompt involves novel problem-solving,
      multi-step proof / verification, or chain-of-thought across
      many files (i.e., the conditions that would push
      `<selection-algorithm>` Step 3 to require S-tier in PRIMARY) →
      THINKING `XHigh`.
    - PRIMARY task category `planning` or `knowledge` with
      cross-cutting scope → bump THINKING up at least one level
      (`Off` → `Low`, `Low` → `Medium`, `Medium` → `High`, `High` →
      `XHigh`).
    - Chosen access method's `exposes-thinking` attribute is `no` →
      THINKING `N/A`, overriding the above.

    Thinking and Max Mode are orthogonal: a Cursor call may have
    Max Mode On and THINKING `N/A` (Cursor does not expose the
    thinking toggle); a Claude Code call may have Max Mode Off and
    THINKING `High` (Anthropic's surface exposes thinking, not Max
    Mode).
  </thinking-context>

  <benchmark-sources>
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
  </benchmark-sources>

  <task-categories>
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
  </task-categories>

  <model-options>
    Each model entry carries: pricing, S/A/B/C/D tier ratings across the
    seven task categories, headline benchmark numbers grounded in the
    sources above, and a free-text best-for description.

    Tier ratings:
    - S — top-1 or top-2 globally in this category
    - A — strong, reliable, near-frontier
    - B — competent for the category
    - C — limited; usable only for trivial work in the category
    - D — not suited; do not select for this category

    <tier cost="very-high">
      <model id="opus-4.7" name="Opus 4.7"
             input-price-per-1m="$5.00" output-price-per-1m="$25.00"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1478.7); LMArena WebDev #2 (Elo 1559.3); AA-Omniscience 26.2 (#2)"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching" />
      <model id="gpt-5.5" name="GPT-5.5"
             input-price-per-1m="$5.00" output-price-per-1m="$30.00"
             tier-coding="S" tier-planning="S" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 60.2 (#1); LMArena Text Elo 1462.5 (#14); HLE 44.3%; AA-Omniscience 20.1 (#3)"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination" />
    </tier>
    <tier cost="high">
      <model id="sonnet-4.6" name="Sonnet 4.6"
             input-price-per-1m="$3.00" output-price-per-1m="$15.00"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 51.7; LMArena WebDev Elo 1523.6 (#6); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation" />
      <model id="gpt-5.4" name="GPT-5.4"
             input-price-per-1m="$2.50" output-price-per-1m="$15.00"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="S"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 56.8 (#4); LMArena Text Elo 1454.1 (#18); GPT-5.4 (xhigh) Output Speed 80.5 tokens/s; lowest factual error rate among GPT models"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding" />
    </tier>
    <tier cost="medium">
      <model id="gpt-5.3-codex" name="GPT-5.3 Codex"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             tier-coding="S" tier-planning="B" tier-agentic="S"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high"
             best-for="Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed" />
      <model id="gpt-5.2" name="GPT-5.2"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             tier-coding="B" tier-planning="A" tier-agentic="B"
             tier-multimodal="C" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="MMLU Pro 81.4; GPQA 71.2; LiveCodeBench 66.9; 400K-token context; output speed 68 tokens/s; released 2025-12-10"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high"
             best-for="Earlier-flagship GPT reasoning model (December 2025) with 400K context and broad knowledge coverage (GPQA 71.2, MMLU Pro 81.4); same medium-tier pricing as GPT-5.3 Codex but lacks Codex's autonomous-coding specialization — pick gpt-5.3-codex over gpt-5.2 for coding/agentic tasks; gpt-5.2 fits when broad reasoning at A-tier knowledge and a 400K context window are the primary need at the medium price tier" />
      <model id="gemini-3.1-pro" name="Gemini 3.1 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1483.6 (#4); 1M-token context"
             pricing-notes="-"
             best-for="True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category" />
      <model id="premium" name="Premium (Intelligence)"
             input-price-per-1m="varies (routes to top-tier model)"
             output-price-per-1m="varies (routes to top-tier model)"
             tier-coding="inherit" tier-planning="inherit" tier-agentic="inherit"
             tier-multimodal="inherit" tier-long-context="inherit"
             tier-knowledge="inherit" tier-speed="inherit"
             headline-benchmarks="Inherits the routed model's benchmarks"
             pricing-notes="Cursor-managed routing mode; bills at the routed model's API rate; carries that model's pricing-notes for the duration of the request"
             best-for="Cursor auto-selects the strongest available model; best when the task is clearly high-complexity but does not map to one specific model's niche advantage, or when you are uncertain which frontier model's strengths best apply" />
    </tier>
    <tier cost="low">
      <model id="composer-2" name="Composer 2 (Fast)"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="CursorBench 61.3 (+37% over Composer 1.5); SWE-bench Multilingual 73.7; Terminal-Bench 2.0 61.7"
             pricing-notes="Hidden by default"
             best-for="Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient" />
      <model id="grok-4.3" name="Grok 4.3"
             input-price-per-1m="$1.25" output-price-per-1m="$2.50"
             tier-coding="B" tier-planning="A" tier-agentic="S"
             tier-multimodal="B" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189"
             pricing-notes="Requires Max Mode on request-based plans"
             best-for="Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist" />
      <model id="auto" name="Auto (Efficiency)"
             input-price-per-1m="~$1.25 (Auto + Composer pool)"
             output-price-per-1m="~$6.00 (Auto + Composer pool)"
             tier-coding="B" tier-planning="C" tier-agentic="B"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="A"
             headline-benchmarks="No fixed benchmarks — Cursor routes to a balanced model per request"
             pricing-notes="Cursor-managed routing across the Auto + Composer pool; not a fixed model"
             best-for="Simple, well-defined, bounded tasks — routine edits, boilerplate generation, direct questions, and standard refactors where any competent model suffices and manual model selection adds no value" />
      <model id="claude-4.5-haiku" name="Claude 4.5 Haiku"
             input-price-per-1m="$1.00" output-price-per-1m="$5.00"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 37.1; Output Speed 138.4 tokens/s; AA-Omniscience -4.2; latency leader among Claude family"
             pricing-notes="Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x"
             best-for="Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning" />
      <model id="gpt-5.4-mini" name="GPT-5.4 Mini"
             input-price-per-1m="$0.75" output-price-per-1m="$4.50"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="A"
             headline-benchmarks="AA Intelligence Index 48.9 (xhigh); Output Speed 162.9 tokens/s; HLE 19.4% (GPT-5-mini)"
             pricing-notes="Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens"
             best-for="Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price" />
      <model id="gpt-5.4-nano" name="GPT-5.4 Nano"
             input-price-per-1m="$0.20" output-price-per-1m="$1.25"
             tier-coding="C" tier-planning="D" tier-agentic="D"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5 family variant; throughput-optimized inference"
             pricing-notes="Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens"
             best-for="Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal" />
    </tier>
  </model-options>

  <access-methods>
    Each access method is a way to run one or more models from
    `<model-options>`. Methods differ in (a) which models they expose,
    (b) how billing works (per-token, subscription-included,
    subscription-pool, subscription-or-key), (c) which capability
    toggles (Max Mode, thinking) they expose, and (d) what credentials
    the user must hold.

    The `<access-selection>` algorithm consumes this list together with
    the user-specific state in docs/user-context.md to pick a PLATFORM
    for the chosen model.

    Billing types:
    - subscription-included — a flat-monthly plan with a usage budget
      pool that the call draws from at $0 marginal cost until the
      budget is exhausted (e.g. claude.ai Max, ChatGPT Plus).
    - subscription-pool — a flat-monthly plan with a shared token pool
      consumed across many models (e.g. Cursor Ultra). $0 marginal
      cost until the pool is exhausted.
    - subscription-or-key — surface accepts either a subscription OR a
      direct API key; if a subscription is active, prefer it.
    - per-token — pay-per-token at the provider's published API rate.

    <method id="anthropic-api" name="Anthropic API"
            provider="anthropic" billing="per-token"
            requires="anthropic-api-key"
            supports-models="opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Programmatic / scripted Claude use outside Claude Code — raw API headers, batch endpoints, or features not surfaced by Claude Code. Falls back here when claude.ai Max budget is exhausted." />
    <method id="claude-code" name="Claude Code"
            provider="anthropic" billing="subscription-or-key"
            requires="claude-max-subscription OR anthropic-api-key"
            supports-models="opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Default for Claude coding or terminal tasks when a claude.ai Max subscription is active — $0 marginal cost until the Max budget is exhausted, full tool-use surface, runs as a CLI and as an IDE extension inside Cursor. Heavy Opus usage that would cost over $1,000/mo on per-token API is fully covered by a $100/mo Max plan." />
    <method id="claude-web" name="claude.ai web / desktop"
            provider="anthropic" billing="subscription-included"
            requires="claude-max-subscription"
            supports-models="opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Chat-driven Claude use (no terminal, no codebase tool use) under the same Max budget that funds Claude Code — pick when the task is conversational rather than code-editing." />
    <method id="openai-api" name="OpenAI API"
            provider="openai" billing="per-token"
            requires="openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.4-mini,gpt-5.4-nano"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Programmatic / scripted GPT use when an OpenAI API key is configured. Pay-per-token at OpenAI's published rates." />
    <method id="codex-cli" name="Codex"
            provider="openai" billing="subscription-or-key"
            requires="chatgpt-subscription OR openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.4-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Default for GPT-driven autonomous coding sessions when a ChatGPT Plus/Pro subscription is active — pays from the ChatGPT budget instead of the per-token API rate. Best surface for gpt-5.3-codex on long-running terminal / agentic work." />
    <method id="chatgpt-app" name="ChatGPT (web / desktop)"
            provider="openai" billing="subscription-included"
            requires="chatgpt-subscription"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.4-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Chat-driven GPT use without terminal or IDE integration; subscription-funded so marginal cost is $0 until ChatGPT's usage limits kick in." />
    <method id="google-api" name="Google AI Studio API"
            provider="google" billing="per-token"
            requires="google-api-key"
            supports-models="gemini-3.1-pro"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Programmatic / scripted Gemini use with a Google API key. Pay-per-token at Google's published rates." />
    <method id="gemini-cli" name="Gemini CLI"
            provider="google" billing="subscription-or-key"
            requires="gemini-advanced-subscription OR google-api-key"
            supports-models="gemini-3.1-pro"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Terminal-driven Gemini use; the CLI surface for multimodal and long-context Gemini work outside Cursor's pool." />
    <method id="gemini-app" name="Gemini (web / app)"
            provider="google" billing="subscription-included"
            requires="gemini-advanced-subscription"
            supports-models="gemini-3.1-pro"
            exposes-max-mode="no" exposes-thinking="yes"
            best-for="Chat-driven Gemini use under the Gemini Advanced subscription budget." />
    <method id="xai-api" name="xAI API"
            provider="xai" billing="per-token"
            requires="xai-api-key"
            supports-models="grok-4.3"
            exposes-max-mode="no" exposes-thinking="no"
            best-for="Direct Grok API access for 2M-context or hallucination-resistant tasks; pay-per-token at xAI's published rates." />
    <method id="cursor" name="Cursor"
            provider="cursor" billing="subscription-pool"
            requires="cursor-pro-or-ultra-subscription"
            supports-models="opus-4.7,gpt-5.5,sonnet-4.6,gpt-5.4,gpt-5.3-codex,gemini-3.1-pro,premium,grok-4.3,claude-4.5-haiku,gpt-5.4-mini,gpt-5.4-nano,composer-2,auto"
            exposes-max-mode="yes" exposes-thinking="no"
            best-for="Cursor IDE — single Platform covering both UI modes (Composer for multi-file autonomous editing; Chat for interactive model-picker). The operator picks the mode at task time based on the chosen Model: composer-2 / auto / premium imply Composer mode; frontier models (opus-4.7, gpt-5.5, sonnet-4.6, etc.) imply Chat mode. All routes through the $0-marginal Cursor pool. Defer to claude-code when the chosen model is Claude and claude.ai Max is active (Max budget is cheaper marginal cost than burning Cursor pool tokens on Claude calls that have a dedicated Anthropic subscription path)." />
  </access-methods>

  <selection-algorithm>
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
  </selection-algorithm>

  <access-selection>
    After `<selection-algorithm>` picks a MODEL and a Max Mode setting,
    run this procedure to pick a PLATFORM (access method) and a
    THINKING level. Read docs/user-context.md first to learn the user's
    subscription state, API keys, and platform preference order — the
    PLATFORM choice is meaningless without that input.

    Step A — Filter access methods by model support.
      Reduce `<access-methods>` to those whose `supports-models`
      attribute lists the chosen model id. The result is the candidate
      set of platforms.

    Step B — Filter by credential availability.
      Reduce the candidate set to access methods whose `requires`
      clause is satisfied by the user's active subscriptions or API
      keys per docs/user-context.md. Drop any method whose credential
      the user does not have.

    Step C — Rank by effective marginal cost.
      Order survivors lowest-cost first:
        1. `subscription-included` and `subscription-or-key` methods
           backed by an active subscription (marginal cost $0 until
           the subscription's usage budget is exhausted).
        2. `subscription-pool` methods backed by an active pool
           (marginal cost $0 until the pool is exhausted).
        3. `subscription-or-key` methods backed only by an API key,
           and `per-token` methods (real dollars per call).
      Within a tier, prefer the access method whose surface matches
      the task — Claude Code over claude.ai web for coding, Codex
      over ChatGPT app for autonomous coding sessions. Cursor's
      Composer vs Chat UI modes are both reached via the single
      `cursor` access method — the operator picks the mode at task
      time based on the chosen Model (composer-2 / auto / premium
      imply Composer mode; frontier models imply Chat mode).

    Step D — Apply user-context.md preference overrides.
      docs/user-context.md may set a preferred platform order. When
      the user's preference puts a method ahead of a cheaper-on-paper
      one, honor the preference — it reflects subscription-utilization
      economics the catalog cannot see (e.g. burning Max budget that
      would otherwise expire vs preserving Cursor pool tokens for
      OpenAI / Google calls that have no other paid path on this
      account).

    Step E — Determine the THINKING level.
      Apply the decision rule in `<thinking-context>` against the
      overall complexity from `<selection-algorithm>` Step 2. If the
      chosen access method's `exposes-thinking` attribute is `no`,
      set THINKING `N/A` regardless of complexity.

    Step F — Resolve MAX MODE against the chosen PLATFORM.
      Max Mode is a Cursor-surface concept. If the chosen access
      method's `exposes-max-mode` attribute is `no`, set MAX MODE
      `Off` in the output even when `<selection-algorithm>` Step 6
      enabled it — Max Mode does not apply outside Cursor. The
      `<selection-algorithm>` rationale for enabling Max Mode (long
      context, cross-cutting reasoning) still holds; it just manifests
      as native context-window use on non-Cursor surfaces.

    Step G — Emit PLATFORM, THINKING, and MAX MODE in the output.
      The PLATFORM field is the `name` attribute of the chosen access
      method. The RATIONALE must name (a) the subscription or API key
      that pays for the call (or note the lack thereof), and (b) why
      the THINKING level was chosen (or why it is `N/A`).

    Guardrails:
    - Never recommend an access method whose credential the user does
      not have. If the candidate set in Step B is empty, the model
      chosen in `<selection-algorithm>` is unreachable for this user;
      fall back to the next-best model whose access methods ARE
      reachable, and add a rationale clause noting the substitution
      and why the first-choice model was unreachable.
    - Never burn pay-per-token spend when a subscription that is
      already paid can serve the call. Subscriptions are sunk cost;
      a per-token call is real cash out.
    - When the chosen model is a Cursor-only model (composer-2, auto,
      premium), the only valid access method is `cursor` (the
      operator uses Composer mode for composer-2 / auto and Chat
      mode for premium — `premium` is a Cursor-managed routing
      label inside Chat).
    - When the chosen model is Claude (opus-4.7, sonnet-4.6, claude-
      4.5-haiku) AND the user has both claude-max-subscription and
      cursor-pro-or-ultra-subscription active, prefer claude-code (or
      claude-web for non-coding tasks) over `cursor` — the Max
      subscription is dedicated Claude budget that the Cursor pool
      cannot substitute for, while the Cursor pool can absorb OpenAI /
      Google / xAI calls that have no other paid path.

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
PLATFORM: [Access Method Name]
MAX MODE: [On/Off]
THINKING: [Off/Low/Medium/High/XHigh/N/A]
CONVERSATION: [New/Continue]
RATIONALE: [2-3 sentences that MUST name (a) the prompt's PRIMARY task
            category, (b) the recommended model's tier rating in that
            category, (c) at least one headline benchmark or named
            leaderboard from <benchmark-sources> supporting the choice,
            (d) the cost tie-breaker outcome if step 5 of the
            selection-algorithm applied, (e) the subscription or API
            key that pays for the chosen PLATFORM (or note its
            absence), and (f) why the THINKING level was set as
            stated (or why it is N/A). Also note the conversation
            handling decision.]

Roadmap annotation mode — output one block per prompt, preceded by the
prompt identifier or a brief label, in order:

MODEL: [Model Name]
PLATFORM: [Access Method Name]
MAX MODE: [On/Off]
THINKING: [Off/Low/Medium/High/XHigh/N/A]
CONVERSATION: [New/Continue]
RATIONALE: [2-3 sentences that MUST name (a) the prompt's PRIMARY task
            category, (b) the recommended model's tier rating in that
            category, (c) at least one headline benchmark or named
            leaderboard from <benchmark-sources> supporting the choice,
            (d) the cost tie-breaker outcome if step 5 of the
            selection-algorithm applied, (e) the subscription or API
            key that pays for the chosen PLATFORM (or note its
            absence), and (f) why the THINKING level was set as
            stated (or why it is N/A). Also note the conversation
            handling decision.]
PROMPT: [Prompt # or short label]
