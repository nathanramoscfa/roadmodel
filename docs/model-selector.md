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

Routing meta-models (Cursor's "Auto" / "Premium" modes; analogous
routers from other providers) are NOT enumerated in `<model-options>`.
The catalog tracks fixed-engine models only — a routing model's
benchmarks, jurisdiction, and cost are by construction unknowable in
advance, which conflicts with the selector's per-model tier ratings
and the `<jurisdiction-context>` filter. Users who want routing
behavior should pick a specific fixed engine directly.

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
- Teams plans: requests against fixed-model surfaces include the
  Cursor Token Rate.
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

`.
    The catalog tracks fixed-engine models only — a routing model's
    benchmarks, jurisdiction, and cost are by construction unknowable in
    advance, which conflicts with the selector's per-model tier ratings
    and the `<jurisdiction-context>` filter. Users who want routing
    behavior should pick a specific fixed engine directly.

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
    - Teams plans: requests against fixed-model surfaces include the
      Cursor Token Rate.
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

  <orchestration-context>
    Orchestration (Claude Code's Dynamic Workflows feature, shipped
    with Opus 4.8 in May 2026) lets the model fan a single prompt
    out across parallel subagents from a script Claude writes and
    the runtime executes. Up to 1,000 agents per run, 16 concurrent.
    Intermediate results live in script variables, not the model's
    context window. Workflows can adversarially cross-check
    findings before reporting.

    Providers expose orchestration differently:

    - Claude Code (CLI, IDE extension): per-prompt opt-in by
      including the word "workflow" in the prompt; session-wide
      opt-in via /effort ultracode. Ultracode pins reasoning at
      xhigh AND auto-authors a workflow for every substantive
      task in the session.
    - All other surfaces (Cursor, Codex, Gemini CLI, claude.ai
      web, ChatGPT app, direct APIs): no equivalent built-in
      orchestration primitive at time of writing.

    Output mapping (the ORCHESTRATION field of the output format):
    `None` / `PerPrompt` / `Ultracode` / `N/A`.

    - Claude Code default → `None` (single-agent turn-by-turn).
    - Claude Code with `workflow` keyword on this prompt only →
      `PerPrompt`.
    - Claude Code with `/effort ultracode` session-wide → `Ultracode`.
    - Any non-Claude-Code platform → `N/A`.

    Decision rule (applied during <access-selection>):
    - PRIMARY task category `planning` with cross-cutting scope AND
      overall complexity High AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - PRIMARY task category `long-context` with multi-source
      cross-checking required (e.g., codebase audit, migration
      sweep, cited research) AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - Single well-scoped deliverable (one file, one bug fix, one
      refactor) → `None` even on Claude Code.
    - Chosen access method's `exposes-orchestration` attribute is
      `no` → `N/A` regardless of the above.

    Cost note: Ultracode lifts the per-prompt token-cost ceiling
    ("token cost is not a constraint" per Anthropic's built-in
    framing). On claude.ai Max ($200/mo), per-call $ cost is $0
    marginal, but session budget burns 10-100x faster than High.
    Recommend Ultracode as a deliberate per-step opt-in, not as
    a default — pair with a session-budget-awareness clause in
    the rationale.

    Orchestration, thinking, and Max Mode are three orthogonal
    axes. Cursor + Max Mode + THINKING N/A + ORCHESTRATION N/A
    is valid. Claude Code + THINKING XHigh + ORCHESTRATION
    Ultracode is valid. Claude Code + THINKING XHigh +
    ORCHESTRATION None is also valid (Extra high effort, no
    auto-workflow).
  </orchestration-context>

  <jurisdiction-context>
    Some users restrict which model providers are acceptable based on
    the provider's HQ jurisdiction — typically driven by data-
    sovereignty, vendor-trust, regulatory-compliance, or export-control
    concerns. The selector supports this via the `jurisdiction`
    attribute on every `<model>` element and the
    `provider-jurisdiction` attribute on every `<method>` element,
    combined with an allowed-jurisdictions list the user supplies in
    `docs/user-context.md` (or the SaaS-side `profiles` row).

    Valid jurisdiction codes (ISO-3166-1 alpha-2-style, lowercase):

    - `us` — United States. Today: Anthropic, OpenAI, Google, xAI,
      Cursor.
    - `eu` — European Union member state.
    - `uk` — United Kingdom.
    - `ca` — Canada.
    - `au` — Australia.
    - `jp` — Japan.
    - `kr` — South Korea.
    - `cn` — China. Today: Moonshot (Kimi). Future Chinese-HQ
      entrants inherit this code.
    - `ru` — Russia. (No models on Cursor's pricing page from this
      jurisdiction at time of writing.)
    - `unknown` — provider HQ has not been editorially verified yet.
      Newly-auto-added models receive this code until the maintainer
      fills it in; the auto-add rule in `update/prompt.md` emits a
      warning so these don't ship silently.

    Default allowed list (assumed when `docs/user-context.md` carries
    no `<allowed-jurisdictions>` section):
    `[us, eu, uk, ca, au, jp, kr]` — a "five eyes plus close-aligned
    democracies" baseline. Users add or remove entries to widen or
    narrow.

    The base weights of a model and the operator of a model may
    carry different jurisdictions. The `jurisdiction` attribute
    reflects the OPERATOR — the entity whose terms govern the data
    flow when a call is placed. Composer 2 / Composer 2.5 are
    `us`-jurisdiction because Cursor operates them, even though
    their base weights derive from Moonshot's Kimi K2 series; the
    data path is governed by Cursor's privacy policy and US law.
    When base-weights origin matters for a user's compliance
    posture, the `best-for` attribute discloses the lineage so the
    user can decide whether to widen the filter further.

    Routing meta-models (e.g., Cursor's "Auto" and "Premium" modes;
    OpenRouter-style routers; any "router-of-routers") are NOT
    enumerated in `<model-options>` precisely because their routing
    is opaque — the selector cannot guarantee a specific call's
    jurisdiction without knowing the routed engine, and the routing
    decision is the routing provider's, not the user's. As of
    2026-05-21 roadmodel exposes only fixed-engine models. Users
    who want routing behavior should pick a specific fixed engine
    directly and accept that the underlying provider may pool-route
    among models of the same family.
  </jurisdiction-context>

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

### Very High Cost Tier

#### Opus 4.7 — `opus-4.7`

- **Pricing:** Input $5.00/M · Output $25.00/M
- **Tier ratings:** Coding **S** · Planning **S** · Agentic **A** · Multimodal **A** · Long-context **S** · Knowledge **S** · Speed **D**
- **Headline benchmarks:** AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1480.8); LMArena WebDev #2 (Elo 1562.4); AA-Omniscience 26.2 (#2)
- **Pricing notes:** Hidden by default; Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching

#### Opus 4.8 — `opus-4.8`

- **Pricing:** Input $5.00/M · Output $25.00/M
- **Tier ratings:** Coding **S** · Planning **S** · Agentic **A** · Multimodal **A** · Long-context **S** · Knowledge **S** · Speed **D**
- **Headline benchmarks:** AA Intelligence Index 61.4 (#1); HLE 45.7%; Terminal-Bench Hard 58.3%; τ²-bench airline pass_1 ~ (benchmark coverage expanding)
- **Pricing notes:** Requires Max Mode on request-based plans; Fast mode (`claude-opus-4-8-fast`) requires Max Mode; Fast mode is 3x lower per-token pricing than Opus 4.7 fast mode; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Anthropic's Opus 4.7 successor at the same very-high tier pricing — placeholder tier ratings inherited from opus-4.7 pending benchmark coverage; the 3x cheaper fast-mode per-token rate (vs opus-4.7 fast mode) is the headline cost-structure change to surface in the next editorial pass

#### GPT-5.5 — `gpt-5.5`

- **Pricing:** Input $5.00/M · Output $30.00/M
- **Tier ratings:** Coding **S** · Planning **S** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **A** · Speed **D**
- **Headline benchmarks:** AA Intelligence Index 60.2 (#1); LMArena Text Elo 1463.9 (#16); HLE 44.3%; AA-Omniscience 20.1 (#3)
- **Pricing notes:** Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing
- **Best for:** OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination

### High Cost Tier

#### Sonnet 4.6 — `sonnet-4.6`

- **Pricing:** Input $3.00/M · Output $15.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 51.7; LMArena WebDev Elo 1522.9 (#7); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage
- **Pricing notes:** Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)
- **Best for:** Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation

#### GPT-5.4 — `gpt-5.4`

- **Pricing:** Input $2.50/M · Output $15.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **S** · Multimodal **A** · Long-context **A** · Knowledge **S** · Speed **B**
- **Headline benchmarks:** AA Intelligence Index 56.8 (#4); LMArena Text Elo 1456.3 (#19); GPT-5.4 (xhigh) Output Speed 91.9 tokens/s; lowest factual error rate among GPT models
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
- **Headline benchmarks:** AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1481.4 (#5); 1M-token context
- **Pricing notes:** -
- **Best for:** True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category

#### Gemini 3 Pro — `gemini-3-pro`

- **Pricing:** Input $2.00/M · Output $12.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **A** · Multimodal **S** · Long-context **S** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** Gemini 3 generation Pro variant predating the 3.1 refresh; 1M-token context; native multimodal across text/image/video/audio/code
- **Pricing notes:** Hidden by default
- **Best for:** Gemini 3 family Pro model at the same medium-tier pricing as gemini-3.1-pro — pick gemini-3.1-pro over gemini-3-pro when both are available since 3.1 carries the updated benchmarks and is the canonical visible Gemini Pro; gemini-3-pro fits when reproducing earlier Gemini-3-generation outputs or when the 3.1 refresh's behavioral changes are undesirable for a specific workload

#### GPT-5 — `gpt-5`

- **Pricing:** Input $1.25/M · Output $10.00/M
- **Tier ratings:** Coding **A** · Planning **A** · Agentic **A** · Multimodal **B** · Long-context **A** · Knowledge **A** · Speed **B**
- **Headline benchmarks:** Earlier flagship GPT-5 family entry with agentic and reasoning capabilities at medium-tier output pricing; specific AA / LMArena numbers pending benchmark refresh
- **Pricing notes:** Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5-high
- **Best for:** OpenAI's baseline GPT-5 family flagship — broad reasoning capability at medium-tier pricing ($10/M output), useful when a balanced GPT-5-class model is needed without the premium of GPT-5.4 / 5.5 and without the codex coding specialization; superseded by GPT-5.2 / 5.3 / 5.4 for most production use cases but available on Cursor's pool

#### GPT-5.1 Codex — `gpt-5.1-codex`

- **Pricing:** Input $1.25/M · Output $10.00/M
- **Tier ratings:** Coding **S** · Planning **B** · Agentic **A** · Multimodal **D** · Long-context **B** · Knowledge **B** · Speed **B**
- **Headline benchmarks:** Earlier-generation Codex specialization at medium-tier output pricing; strong terminal and tool-use proficiency carried forward from the Codex lineage
- **Pricing notes:** Hidden by default; Agentic and reasoning capabilities
- **Best for:** Earlier Codex generation at the same medium-tier pricing as gpt-5.3-codex but $10/M output (gpt-5.3-codex is $14/M) — the lowest-cost S-tier coding model on the medium tier; prefer gpt-5.3-codex when latest-generation Codex quality matters, prefer gpt-5.1-codex when reproducing earlier-Codex-generation outputs or when the slightly cheaper output price compounds against a high-volume coding workload

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
- **Headline benchmarks:** AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189.2
- **Pricing notes:** Requires Max Mode on request-based plans
- **Best for:** Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist

#### Claude 4.5 Haiku — `claude-4.5-haiku`

- **Pricing:** Input $1.00/M · Output $5.00/M
- **Tier ratings:** Coding **B** · Planning **B** · Agentic **B** · Multimodal **B** · Long-context **B** · Knowledge **B** · Speed **S**
- **Headline benchmarks:** AA Intelligence Index 37.1; Output Speed 132.7 tokens/s; AA-Omniscience -4.2; latency leader among Claude family
- **Pricing notes:** Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x
- **Best for:** Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning

#### GPT-5.4 Mini — `gpt-5.4-mini`

- **Pricing:** Input $0.75/M · Output $4.50/M
- **Tier ratings:** Coding **B** · Planning **C** · Agentic **C** · Multimodal **B** · Long-context **B** · Knowledge **B** · Speed **A**
- **Headline benchmarks:** AA Intelligence Index 48.9 (xhigh); Output Speed 172.8 tokens/s; HLE 26.6% (GPT-5.4-mini xhigh)
- **Pricing notes:** Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens
- **Best for:** Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price

#### GPT-5.4 Nano — `gpt-5.4-nano`

- **Pricing:** Input $0.20/M · Output $1.25/M
- **Tier ratings:** Coding **C** · Planning **D** · Agentic **D** · Multimodal **C** · Long-context **C** · Knowledge **C** · Speed **S**
- **Headline benchmarks:** Cheapest GPT-5.4 family variant; throughput-optimized inference
- **Pricing notes:** Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens
- **Best for:** Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal

#### Composer 2.5 — `composer-2.5`

- **Pricing:** Input $0.50/M · Output $2.50/M
- **Tier ratings:** Coding **A** · Planning **B** · Agentic **A** · Multimodal **D** · Long-context **B** · Knowledge **B** · Speed **S**
- **Headline benchmarks:** Composer 2 family successor at the same output price ($2.50/M); Cursor's release notes claim substantial intelligence + behavior improvements over Composer 2 trained on ~25x more synthetic tasks; specific benchmark numbers pending republish (CursorBench 61.3 + SWE-bench Multilingual 73.7 + Terminal-Bench 2.0 61.7 from Composer 2 carry forward as floors)
- **Pricing notes:** -
- **Best for:** Composer 2's successor at the same output price — Cursor's purpose-built multi-file agentic editor with frontier-level coding quality and speed-optimized inference; prefer over Composer 2 when both are available since 2.5 supersedes 2 within the same series per the equal-output-price replacement rule (Composer 2 is now Hidden by default on Cursor's pricing page)

#### Gemini 2.5 Flash — `gemini-2.5-flash`

- **Pricing:** Input $0.30/M · Output $2.50/M
- **Tier ratings:** Coding **B** · Planning **B** · Agentic **B** · Multimodal **A** · Long-context **A** · Knowledge **B** · Speed **S**
- **Headline benchmarks:** High-throughput Gemini Flash variant with native multimodal grounding; 1M-token context; designed for low-cost high-volume inference
- **Pricing notes:** Hidden by default
- **Best for:** Google's cheap, fast, multimodal Flash model at $0.30/M output — the cost-efficient pick for high-volume structured-output tasks (model recommendation, classification, light planning with strong system-prompt grounding) where multimodal capability matters and frontier-class reasoning does not; powers free-tier SaaS surfaces where per-call cost discipline is essential and the bundled templates do the structural heavy lifting

#### Gemini 3 Flash — `gemini-3-flash`

- **Pricing:** Input $0.50/M · Output $3.00/M
- **Tier ratings:** Coding **B** · Planning **A** · Agentic **A** · Multimodal **S** · Long-context **S** · Knowledge **A** · Speed **S**
- **Headline benchmarks:** Gemini 3 generation Flash variant; native multimodal across text/image/video/audio; 1M-token context; throughput-optimized inference
- **Pricing notes:** Hidden by default
- **Best for:** Gemini 3 generation's cheap-tier model — meaningfully stronger planning, agentic, knowledge ratings than 2.5 Flash at slightly higher cost ($3.00/M output vs $2.50/M), with native multimodal-S; pick over 2.5 Flash when the task benefits from Gemini 3 family improvements and per-call cost discipline still matters

#### Gemini 3.5 Flash — `gemini-3.5-flash`

- **Pricing:** Input $1.50/M · Output $9.00/M
- **Tier ratings:** Coding **B** · Planning **A** · Agentic **A** · Multimodal **B** · Long-context **B** · Knowledge **A** · Speed **S**
- **Headline benchmarks:** AA Intelligence Index 55.3 (high reasoning); τ²-bench retail pass_1 45.6 (Gemini 3.5 Flash); Output Speed 217.6 tokens/s
- **Pricing notes:** -
- **Best for:** Auto-added cheap-tier Google model; pending editorial best-for refinement.

#### GPT-5 Mini — `gpt-5-mini`

- **Pricing:** Input $0.25/M · Output $2.00/M
- **Tier ratings:** Coding **B** · Planning **C** · Agentic **C** · Multimodal **B** · Long-context **B** · Knowledge **B** · Speed **S**
- **Headline benchmarks:** Cheapest GPT-5 family variant at $2.00/M output; throughput-optimized inference
- **Pricing notes:** Hidden by default
- **Best for:** The cheapest GPT-5 family variant at $2.00/M output — well-suited for trivial text tasks, simple lookups, rapid classification, and high-throughput pipelines where the cost-per-call is the binding constraint; not appropriate for multi-step planning or autonomous agentic execution; competitive with Gemini 2.5 Flash on cost but lacks Gemini's native multimodal-A rating

#### Kimi K2.5 — `kimi-k2.5`

- **Pricing:** Input $0.60/M · Output $3.00/M
- **Tier ratings:** Coding **B** · Planning **B** · Agentic **B** · Multimodal **C** · Long-context **B** · Knowledge **B** · Speed **B**
- **Headline benchmarks:** Moonshot AI's Kimi K2 series successor at $3.00/M output; competitive cost positioning across general text tasks; specific benchmark numbers pending refresh
- **Pricing notes:** Hidden by default
- **Best for:** Moonshot's affordable mid-volume model — a non-Google / non-OpenAI / non-Anthropic option at low-tier pricing for cost-conscious code and text generation when provider diversity is desired (vendor-risk hedging, regional preferences); routed via Cursor's pool only — no direct Moonshot access method is currently enumerated in the access-methods block

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
    - Teams plans: requests against fixed-model surfaces include the
      Cursor Token Rate.
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

  <orchestration-context>
    Orchestration (Claude Code's Dynamic Workflows feature, shipped
    with Opus 4.8 in May 2026) lets the model fan a single prompt
    out across parallel subagents from a script Claude writes and
    the runtime executes. Up to 1,000 agents per run, 16 concurrent.
    Intermediate results live in script variables, not the model's
    context window. Workflows can adversarially cross-check
    findings before reporting.

    Providers expose orchestration differently:

    - Claude Code (CLI, IDE extension): per-prompt opt-in by
      including the word "workflow" in the prompt; session-wide
      opt-in via /effort ultracode. Ultracode pins reasoning at
      xhigh AND auto-authors a workflow for every substantive
      task in the session.
    - All other surfaces (Cursor, Codex, Gemini CLI, claude.ai
      web, ChatGPT app, direct APIs): no equivalent built-in
      orchestration primitive at time of writing.

    Output mapping (the ORCHESTRATION field of the output format):
    `None` / `PerPrompt` / `Ultracode` / `N/A`.

    - Claude Code default → `None` (single-agent turn-by-turn).
    - Claude Code with `workflow` keyword on this prompt only →
      `PerPrompt`.
    - Claude Code with `/effort ultracode` session-wide → `Ultracode`.
    - Any non-Claude-Code platform → `N/A`.

    Decision rule (applied during <access-selection>):
    - PRIMARY task category `planning` with cross-cutting scope AND
      overall complexity High AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - PRIMARY task category `long-context` with multi-source
      cross-checking required (e.g., codebase audit, migration
      sweep, cited research) AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - Single well-scoped deliverable (one file, one bug fix, one
      refactor) → `None` even on Claude Code.
    - Chosen access method's `exposes-orchestration` attribute is
      `no` → `N/A` regardless of the above.

    Cost note: Ultracode lifts the per-prompt token-cost ceiling
    ("token cost is not a constraint" per Anthropic's built-in
    framing). On claude.ai Max ($200/mo), per-call $ cost is $0
    marginal, but session budget burns 10-100x faster than High.
    Recommend Ultracode as a deliberate per-step opt-in, not as
    a default — pair with a session-budget-awareness clause in
    the rationale.

    Orchestration, thinking, and Max Mode are three orthogonal
    axes. Cursor + Max Mode + THINKING N/A + ORCHESTRATION N/A
    is valid. Claude Code + THINKING XHigh + ORCHESTRATION
    Ultracode is valid. Claude Code + THINKING XHigh +
    ORCHESTRATION None is also valid (Extra high effort, no
    auto-workflow).
  </orchestration-context>

  <jurisdiction-context>
    Some users restrict which model providers are acceptable based on
    the provider's HQ jurisdiction — typically driven by data-
    sovereignty, vendor-trust, regulatory-compliance, or export-control
    concerns. The selector supports this via the `jurisdiction`
    attribute on every `<model>` element and the
    `provider-jurisdiction` attribute on every `

### Anthropic

#### Anthropic API — `anthropic-api`

- **Billing:** per-token (requires anthropic-api-key)
- **Supports models:** opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Programmatic / scripted Claude use outside Claude Code — raw API headers, batch endpoints, or features not surfaced by Claude Code. Falls back here when claude.ai Max budget is exhausted.

#### Claude Code — `claude-code`

- **Billing:** subscription-or-key (requires claude-max-subscription OR anthropic-api-key)
- **Supports models:** opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Default for Claude coding or terminal tasks when a claude.ai Max subscription is active — $0 marginal cost until the Max budget is exhausted, full tool-use surface, runs as a CLI and as an IDE extension inside Cursor. Heavy Opus usage that would cost over $1,000/mo on per-token API is fully covered by a $100/mo Max plan.

#### claude.ai web / desktop — `claude-web`

- **Billing:** subscription-included (requires claude-max-subscription)
- **Supports models:** opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Chat-driven Claude use (no terminal, no codebase tool use) under the same Max budget that funds Claude Code — pick when the task is conversational rather than code-editing.

### OpenAI

#### OpenAI API — `openai-api`

- **Billing:** per-token (requires openai-api-key)
- **Supports models:** gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.1-codex,gpt-5,gpt-5.4-mini,gpt-5.4-nano,gpt-5-mini
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Programmatic / scripted GPT use when an OpenAI API key is configured. Pay-per-token at OpenAI's published rates.

#### Codex — `codex-cli`

- **Billing:** subscription-or-key (requires chatgpt-subscription OR openai-api-key)
- **Supports models:** gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.1-codex,gpt-5,gpt-5.4-mini,gpt-5-mini
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Default for GPT-driven autonomous coding sessions when a ChatGPT Plus/Pro subscription is active — pays from the ChatGPT budget instead of the per-token API rate. Best surface for gpt-5.3-codex / gpt-5.1-codex on long-running terminal / agentic work.

#### ChatGPT (web / desktop) — `chatgpt-app`

- **Billing:** subscription-included (requires chatgpt-subscription)
- **Supports models:** gpt-5.5,gpt-5.4,gpt-5,gpt-5.4-mini,gpt-5-mini
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Chat-driven GPT use without terminal or IDE integration; subscription-funded so marginal cost is $0 until ChatGPT's usage limits kick in.

### Google

#### Google AI Studio API — `google-api`

- **Billing:** per-token (requires google-api-key)
- **Supports models:** gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Programmatic / scripted Gemini use with a Google API key. Pay-per-token at Google's published rates. Powers the roadmodel SaaS free-tier surfaces (/recommend on Gemini 2.5 Flash; /roadmap on Gemini 2.5 Flash with 3.1 Pro escalation).

#### Gemini CLI — `gemini-cli`

- **Billing:** subscription-or-key (requires gemini-advanced-subscription OR google-api-key)
- **Supports models:** gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash
- **Toggles:** Max Mode — no · Thinking — yes
- **Best for:** Terminal-driven Gemini use; the CLI surface for multimodal and long-context Gemini work outside Cursor's pool.

#### Gemini (web / app) — `gemini-app`

- **Billing:** subscription-included (requires gemini-advanced-subscription)
- **Supports models:** gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash
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
- **Supports models:** opus-4.8,opus-4.7,gpt-5.5,sonnet-4.6,gpt-5.4,gpt-5.3-codex,gpt-5.2,gemini-3.1-pro,gemini-3-pro,gpt-5,gpt-5.1-codex,grok-4.3,claude-4.5-haiku,gpt-5.4-mini,gpt-5.4-nano,composer-2,composer-2.5,gemini-2.5-flash,gemini-3-flash,gemini-3.5-flash,gpt-5-mini,kimi-k2.5
- **Toggles:** Max Mode — yes · Thinking — no
- **Best for:** Cursor IDE — single Platform covering both UI modes (Composer for multi-file autonomous editing; Chat for interactive model-picker). The operator picks the mode at task time based on the chosen Model: composer-2 / composer-2.5 imply Composer mode; frontier models (opus-4.7, gpt-5.5, sonnet-4.6, etc.) imply Chat mode. Cursor's own Auto and Premium routing modes are deliberately NOT enumerated as roadmodel-recommendable models because their routing is opaque (see `jurisdiction-context` for the rationale) — operators who want routing behavior pick a specific fixed model and let Cursor's pool handle the call. All routes through the $0-marginal Cursor pool. Defer to claude-code when the chosen model is Claude and claude.ai Max is active (Max budget is cheaper marginal cost than burning Cursor pool tokens on Claude calls that have a dedicated Anthropic subscription path).

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

    Routing meta-models (Cursor's "Auto" / "Premium" modes; analogous
    routers from other providers) are NOT enumerated in `<model-options>`.
    The catalog tracks fixed-engine models only — a routing model's
    benchmarks, jurisdiction, and cost are by construction unknowable in
    advance, which conflicts with the selector's per-model tier ratings
    and the `<jurisdiction-context>` filter. Users who want routing
    behavior should pick a specific fixed engine directly.

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
    - Teams plans: requests against fixed-model surfaces include the
      Cursor Token Rate.
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

  <orchestration-context>
    Orchestration (Claude Code's Dynamic Workflows feature, shipped
    with Opus 4.8 in May 2026) lets the model fan a single prompt
    out across parallel subagents from a script Claude writes and
    the runtime executes. Up to 1,000 agents per run, 16 concurrent.
    Intermediate results live in script variables, not the model's
    context window. Workflows can adversarially cross-check
    findings before reporting.

    Providers expose orchestration differently:

    - Claude Code (CLI, IDE extension): per-prompt opt-in by
      including the word "workflow" in the prompt; session-wide
      opt-in via /effort ultracode. Ultracode pins reasoning at
      xhigh AND auto-authors a workflow for every substantive
      task in the session.
    - All other surfaces (Cursor, Codex, Gemini CLI, claude.ai
      web, ChatGPT app, direct APIs): no equivalent built-in
      orchestration primitive at time of writing.

    Output mapping (the ORCHESTRATION field of the output format):
    `None` / `PerPrompt` / `Ultracode` / `N/A`.

    - Claude Code default → `None` (single-agent turn-by-turn).
    - Claude Code with `workflow` keyword on this prompt only →
      `PerPrompt`.
    - Claude Code with `/effort ultracode` session-wide → `Ultracode`.
    - Any non-Claude-Code platform → `N/A`.

    Decision rule (applied during <access-selection>):
    - PRIMARY task category `planning` with cross-cutting scope AND
      overall complexity High AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - PRIMARY task category `long-context` with multi-source
      cross-checking required (e.g., codebase audit, migration
      sweep, cited research) AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - Single well-scoped deliverable (one file, one bug fix, one
      refactor) → `None` even on Claude Code.
    - Chosen access method's `exposes-orchestration` attribute is
      `no` → `N/A` regardless of the above.

    Cost note: Ultracode lifts the per-prompt token-cost ceiling
    ("token cost is not a constraint" per Anthropic's built-in
    framing). On claude.ai Max ($200/mo), per-call $ cost is $0
    marginal, but session budget burns 10-100x faster than High.
    Recommend Ultracode as a deliberate per-step opt-in, not as
    a default — pair with a session-budget-awareness clause in
    the rationale.

    Orchestration, thinking, and Max Mode are three orthogonal
    axes. Cursor + Max Mode + THINKING N/A + ORCHESTRATION N/A
    is valid. Claude Code + THINKING XHigh + ORCHESTRATION
    Ultracode is valid. Claude Code + THINKING XHigh +
    ORCHESTRATION None is also valid (Extra high effort, no
    auto-workflow).
  </orchestration-context>

  <jurisdiction-context>
    Some users restrict which model providers are acceptable based on
    the provider's HQ jurisdiction — typically driven by data-
    sovereignty, vendor-trust, regulatory-compliance, or export-control
    concerns. The selector supports this via the `jurisdiction`
    attribute on every `<model>` element and the
    `provider-jurisdiction` attribute on every `<method>` element,
    combined with an allowed-jurisdictions list the user supplies in
    `docs/user-context.md` (or the SaaS-side `profiles` row).

    Valid jurisdiction codes (ISO-3166-1 alpha-2-style, lowercase):

    - `us` — United States. Today: Anthropic, OpenAI, Google, xAI,
      Cursor.
    - `eu` — European Union member state.
    - `uk` — United Kingdom.
    - `ca` — Canada.
    - `au` — Australia.
    - `jp` — Japan.
    - `kr` — South Korea.
    - `cn` — China. Today: Moonshot (Kimi). Future Chinese-HQ
      entrants inherit this code.
    - `ru` — Russia. (No models on Cursor's pricing page from this
      jurisdiction at time of writing.)
    - `unknown` — provider HQ has not been editorially verified yet.
      Newly-auto-added models receive this code until the maintainer
      fills it in; the auto-add rule in `update/prompt.md` emits a
      warning so these don't ship silently.

    Default allowed list (assumed when `docs/user-context.md` carries
    no `<allowed-jurisdictions>` section):
    `[us, eu, uk, ca, au, jp, kr]` — a "five eyes plus close-aligned
    democracies" baseline. Users add or remove entries to widen or
    narrow.

    The base weights of a model and the operator of a model may
    carry different jurisdictions. The `jurisdiction` attribute
    reflects the OPERATOR — the entity whose terms govern the data
    flow when a call is placed. Composer 2 / Composer 2.5 are
    `us`-jurisdiction because Cursor operates them, even though
    their base weights derive from Moonshot's Kimi K2 series; the
    data path is governed by Cursor's privacy policy and US law.
    When base-weights origin matters for a user's compliance
    posture, the `best-for` attribute discloses the lineage so the
    user can decide whether to widen the filter further.

    Routing meta-models (e.g., Cursor's "Auto" and "Premium" modes;
    OpenRouter-style routers; any "router-of-routers") are NOT
    enumerated in `<model-options>` precisely because their routing
    is opaque — the selector cannot guarantee a specific call's
    jurisdiction without knowing the routed engine, and the routing
    decision is the routing provider's, not the user's. As of
    2026-05-21 roadmodel exposes only fixed-engine models. Users
    who want routing behavior should pick a specific fixed engine
    directly and accept that the underlying provider may pool-route
    among models of the same family.
  </jurisdiction-context>

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
             jurisdiction="us"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1480.8); LMArena WebDev #2 (Elo 1562.4); AA-Omniscience 26.2 (#2)"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching" />
      <model id="opus-4.8" name="Opus 4.8"
             input-price-per-1m="$5.00" output-price-per-1m="$25.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 61.4 (#1); HLE 45.7%; Terminal-Bench Hard 58.3%; τ²-bench airline pass_1 ~ (benchmark coverage expanding)"
             pricing-notes="Requires Max Mode on request-based plans; Fast mode (`claude-opus-4-8-fast`) requires Max Mode; Fast mode is 3x lower per-token pricing than Opus 4.7 fast mode; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Anthropic's Opus 4.7 successor at the same very-high tier pricing — placeholder tier ratings inherited from opus-4.7 pending benchmark coverage; the 3x cheaper fast-mode per-token rate (vs opus-4.7 fast mode) is the headline cost-structure change to surface in the next editorial pass" />
      <model id="gpt-5.5" name="GPT-5.5"
             input-price-per-1m="$5.00" output-price-per-1m="$30.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="S" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 60.2 (#1); LMArena Text Elo 1463.9 (#16); HLE 44.3%; AA-Omniscience 20.1 (#3)"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination" />
    </tier>
    <tier cost="high">
      <model id="sonnet-4.6" name="Sonnet 4.6"
             input-price-per-1m="$3.00" output-price-per-1m="$15.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 51.7; LMArena WebDev Elo 1522.9 (#7); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation" />
      <model id="gpt-5.4" name="GPT-5.4"
             input-price-per-1m="$2.50" output-price-per-1m="$15.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="S"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 56.8 (#4); LMArena Text Elo 1456.3 (#19); GPT-5.4 (xhigh) Output Speed 91.9 tokens/s; lowest factual error rate among GPT models"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding" />
    </tier>
    <tier cost="medium">
      <model id="gpt-5.3-codex" name="GPT-5.3 Codex"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="B" tier-agentic="S"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high"
             best-for="Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed" />
      <model id="gpt-5.2" name="GPT-5.2"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="B"
             tier-multimodal="C" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="MMLU Pro 81.4; GPQA 71.2; LiveCodeBench 66.9; 400K-token context; output speed 68 tokens/s; released 2025-12-10"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high"
             best-for="Earlier-flagship GPT reasoning model (December 2025) with 400K context and broad knowledge coverage (GPQA 71.2, MMLU Pro 81.4); same medium-tier pricing as GPT-5.3 Codex but lacks Codex's autonomous-coding specialization — pick gpt-5.3-codex over gpt-5.2 for coding/agentic tasks; gpt-5.2 fits when broad reasoning at A-tier knowledge and a 400K context window are the primary need at the medium price tier" />
      <model id="gemini-3.1-pro" name="Gemini 3.1 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1481.4 (#5); 1M-token context"
             pricing-notes="-"
             best-for="True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category" />
      <model id="gemini-3-pro" name="Gemini 3 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="Gemini 3 generation Pro variant predating the 3.1 refresh; 1M-token context; native multimodal across text/image/video/audio/code"
             pricing-notes="Hidden by default"
             best-for="Gemini 3 family Pro model at the same medium-tier pricing as gemini-3.1-pro — pick gemini-3.1-pro over gemini-3-pro when both are available since 3.1 carries the updated benchmarks and is the canonical visible Gemini Pro; gemini-3-pro fits when reproducing earlier Gemini-3-generation outputs or when the 3.1 refresh's behavioral changes are undesirable for a specific workload" />
      <model id="gpt-5" name="GPT-5"
             input-price-per-1m="$1.25" output-price-per-1m="$10.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="B" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="Earlier flagship GPT-5 family entry with agentic and reasoning capabilities at medium-tier output pricing; specific AA / LMArena numbers pending benchmark refresh"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5-high"
             best-for="OpenAI's baseline GPT-5 family flagship — broad reasoning capability at medium-tier pricing ($10/M output), useful when a balanced GPT-5-class model is needed without the premium of GPT-5.4 / 5.5 and without the codex coding specialization; superseded by GPT-5.2 / 5.3 / 5.4 for most production use cases but available on Cursor's pool" />
      <model id="gpt-5.1-codex" name="GPT-5.1 Codex"
             input-price-per-1m="$1.25" output-price-per-1m="$10.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="Earlier-generation Codex specialization at medium-tier output pricing; strong terminal and tool-use proficiency carried forward from the Codex lineage"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities"
             best-for="Earlier Codex generation at the same medium-tier pricing as gpt-5.3-codex but $10/M output (gpt-5.3-codex is $14/M) — the lowest-cost S-tier coding model on the medium tier; prefer gpt-5.3-codex when latest-generation Codex quality matters, prefer gpt-5.1-codex when reproducing earlier-Codex-generation outputs or when the slightly cheaper output price compounds against a high-volume coding workload" />
    </tier>
    <tier cost="low">
      <model id="composer-2" name="Composer 2 (Fast)"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="CursorBench 61.3 (+37% over Composer 1.5); SWE-bench Multilingual 73.7; Terminal-Bench 2.0 61.7"
             pricing-notes="Hidden by default"
             best-for="Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient" />
      <model id="grok-4.3" name="Grok 4.3"
             input-price-per-1m="$1.25" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="S"
             tier-multimodal="B" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189.2"
             pricing-notes="Requires Max Mode on request-based plans"
             best-for="Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist" />
      <model id="claude-4.5-haiku" name="Claude 4.5 Haiku"
             input-price-per-1m="$1.00" output-price-per-1m="$5.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 37.1; Output Speed 132.7 tokens/s; AA-Omniscience -4.2; latency leader among Claude family"
             pricing-notes="Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x"
             best-for="Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning" />
      <model id="gpt-5.4-mini" name="GPT-5.4 Mini"
             input-price-per-1m="$0.75" output-price-per-1m="$4.50"
             jurisdiction="us"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="A"
             headline-benchmarks="AA Intelligence Index 48.9 (xhigh); Output Speed 172.8 tokens/s; HLE 26.6% (GPT-5.4-mini xhigh)"
             pricing-notes="Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens"
             best-for="Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price" />
      <model id="gpt-5.4-nano" name="GPT-5.4 Nano"
             input-price-per-1m="$0.20" output-price-per-1m="$1.25"
             jurisdiction="us"
             tier-coding="C" tier-planning="D" tier-agentic="D"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5.4 family variant; throughput-optimized inference"
             pricing-notes="Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens"
             best-for="Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal" />
      <model id="composer-2.5" name="Composer 2.5"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="Composer 2 family successor at the same output price ($2.50/M); Cursor's release notes claim substantial intelligence + behavior improvements over Composer 2 trained on ~25x more synthetic tasks; specific benchmark numbers pending republish (CursorBench 61.3 + SWE-bench Multilingual 73.7 + Terminal-Bench 2.0 61.7 from Composer 2 carry forward as floors)"
             pricing-notes="-"
             best-for="Composer 2's successor at the same output price — Cursor's purpose-built multi-file agentic editor with frontier-level coding quality and speed-optimized inference; prefer over Composer 2 when both are available since 2.5 supersedes 2 within the same series per the equal-output-price replacement rule (Composer 2 is now Hidden by default on Cursor's pricing page)" />
      <model id="gemini-2.5-flash" name="Gemini 2.5 Flash"
             input-price-per-1m="$0.30" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="High-throughput Gemini Flash variant with native multimodal grounding; 1M-token context; designed for low-cost high-volume inference"
             pricing-notes="Hidden by default"
             best-for="Google's cheap, fast, multimodal Flash model at $0.30/M output — the cost-efficient pick for high-volume structured-output tasks (model recommendation, classification, light planning with strong system-prompt grounding) where multimodal capability matters and frontier-class reasoning does not; powers free-tier SaaS surfaces where per-call cost discipline is essential and the bundled templates do the structural heavy lifting" />
      <model id="gemini-3-flash" name="Gemini 3 Flash"
             input-price-per-1m="$0.50" output-price-per-1m="$3.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="S"
             headline-benchmarks="Gemini 3 generation Flash variant; native multimodal across text/image/video/audio; 1M-token context; throughput-optimized inference"
             pricing-notes="Hidden by default"
             best-for="Gemini 3 generation's cheap-tier model — meaningfully stronger planning, agentic, knowledge ratings than 2.5 Flash at slightly higher cost ($3.00/M output vs $2.50/M), with native multimodal-S; pick over 2.5 Flash when the task benefits from Gemini 3 family improvements and per-call cost discipline still matters" />
      <model id="gemini-3.5-flash" name="Gemini 3.5 Flash"
             input-price-per-1m="$1.50" output-price-per-1m="$9.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="A"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="A"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 55.3 (high reasoning); τ²-bench retail pass_1 45.6 (Gemini 3.5 Flash); Output Speed 217.6 tokens/s"
             pricing-notes="-"
             best-for="Auto-added cheap-tier Google model; pending editorial best-for refinement." />
      <model id="gpt-5-mini" name="GPT-5 Mini"
             input-price-per-1m="$0.25" output-price-per-1m="$2.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5 family variant at $2.00/M output; throughput-optimized inference"
             pricing-notes="Hidden by default"
             best-for="The cheapest GPT-5 family variant at $2.00/M output — well-suited for trivial text tasks, simple lookups, rapid classification, and high-throughput pipelines where the cost-per-call is the binding constraint; not appropriate for multi-step planning or autonomous agentic execution; competitive with Gemini 2.5 Flash on cost but lacks Gemini's native multimodal-A rating" />
      <model id="kimi-k2.5" name="Kimi K2.5"
             input-price-per-1m="$0.60" output-price-per-1m="$3.00"
             jurisdiction="cn"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="C" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="Moonshot AI's Kimi K2 series successor at $3.00/M output; competitive cost positioning across general text tasks; specific benchmark numbers pending refresh"
             pricing-notes="Hidden by default"
             best-for="Moonshot's affordable mid-volume model — a non-Google / non-OpenAI / non-Anthropic option at low-tier pricing for cost-conscious code and text generation when provider diversity is desired (vendor-risk hedging, regional preferences); routed via Cursor's pool only — no direct Moonshot access method is currently enumerated in the access-methods block" />
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
            provider-jurisdiction="us"
            requires="anthropic-api-key"
            supports-models="opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Programmatic / scripted Claude use outside Claude Code — raw API headers, batch endpoints, or features not surfaced by Claude Code. Falls back here when claude.ai Max budget is exhausted." />
    <method id="claude-code" name="Claude Code"
            provider="anthropic" billing="subscription-or-key"
            provider-jurisdiction="us"
            requires="claude-max-subscription OR anthropic-api-key"
            supports-models="opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="yes"
            best-for="Default for Claude coding or terminal tasks when a claude.ai Max subscription is active — $0 marginal cost until the Max budget is exhausted, full tool-use surface, runs as a CLI and as an IDE extension inside Cursor. Heavy Opus usage that would cost over $1,000/mo on per-token API is fully covered by a $100/mo Max plan." />
    <method id="claude-web" name="claude.ai web / desktop"
            provider="anthropic" billing="subscription-included"
            provider-jurisdiction="us"
            requires="claude-max-subscription"
            supports-models="opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Chat-driven Claude use (no terminal, no codebase tool use) under the same Max budget that funds Claude Code — pick when the task is conversational rather than code-editing." />
    <method id="openai-api" name="OpenAI API"
            provider="openai" billing="per-token"
            provider-jurisdiction="us"
            requires="openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.1-codex,gpt-5,gpt-5.4-mini,gpt-5.4-nano,gpt-5-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Programmatic / scripted GPT use when an OpenAI API key is configured. Pay-per-token at OpenAI's published rates." />
    <method id="codex-cli" name="Codex"
            provider="openai" billing="subscription-or-key"
            provider-jurisdiction="us"
            requires="chatgpt-subscription OR openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.1-codex,gpt-5,gpt-5.4-mini,gpt-5-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Default for GPT-driven autonomous coding sessions when a ChatGPT Plus/Pro subscription is active — pays from the ChatGPT budget instead of the per-token API rate. Best surface for gpt-5.3-codex / gpt-5.1-codex on long-running terminal / agentic work." />
    <method id="chatgpt-app" name="ChatGPT (web / desktop)"
            provider="openai" billing="subscription-included"
            provider-jurisdiction="us"
            requires="chatgpt-subscription"
            supports-models="gpt-5.5,gpt-5.4,gpt-5,gpt-5.4-mini,gpt-5-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Chat-driven GPT use without terminal or IDE integration; subscription-funded so marginal cost is $0 until ChatGPT's usage limits kick in." />
    <method id="google-api" name="Google AI Studio API"
            provider="google" billing="per-token"
            provider-jurisdiction="us"
            requires="google-api-key"
            supports-models="gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Programmatic / scripted Gemini use with a Google API key. Pay-per-token at Google's published rates. Powers the roadmodel SaaS free-tier surfaces (/recommend on Gemini 2.5 Flash; /roadmap on Gemini 2.5 Flash with 3.1 Pro escalation)." />
    <method id="gemini-cli" name="Gemini CLI"
            provider="google" billing="subscription-or-key"
            provider-jurisdiction="us"
            requires="gemini-advanced-subscription OR google-api-key"
            supports-models="gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Terminal-driven Gemini use; the CLI surface for multimodal and long-context Gemini work outside Cursor's pool." />
    <method id="gemini-app" name="Gemini (web / app)"
            provider="google" billing="subscription-included"
            provider-jurisdiction="us"
            requires="gemini-advanced-subscription"
            supports-models="gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Chat-driven Gemini use under the Gemini Advanced subscription budget." />
    <method id="xai-api" name="xAI API"
            provider="xai" billing="per-token"
            provider-jurisdiction="us"
            requires="xai-api-key"
            supports-models="grok-4.3"
            exposes-max-mode="no" exposes-thinking="no"
            exposes-orchestration="no"
            best-for="Direct Grok API access for 2M-context or hallucination-resistant tasks; pay-per-token at xAI's published rates." />
    <method id="cursor" name="Cursor"
            provider="cursor" billing="subscription-pool"
            provider-jurisdiction="us"
            requires="cursor-pro-or-ultra-subscription"
            supports-models="opus-4.8,opus-4.7,gpt-5.5,sonnet-4.6,gpt-5.4,gpt-5.3-codex,gpt-5.2,gemini-3.1-pro,gemini-3-pro,gpt-5,gpt-5.1-codex,grok-4.3,claude-4.5-haiku,gpt-5.4-mini,gpt-5.4-nano,composer-2,composer-2.5,gemini-2.5-flash,gemini-3-flash,gemini-3.5-flash,gpt-5-mini,kimi-k2.5"
            exposes-max-mode="yes" exposes-thinking="no"
            exposes-orchestration="no"
            best-for="Cursor IDE — single Platform covering both UI modes (Composer for multi-file autonomous editing; Chat for interactive model-picker). The operator picks the mode at task time based on the chosen Model: composer-2 / composer-2.5 imply Composer mode; frontier models (opus-4.7, gpt-5.5, sonnet-4.6, etc.) imply Chat mode. Cursor's own Auto and Premium routing modes are deliberately NOT enumerated as roadmodel-recommendable models because their routing is opaque (see `jurisdiction-context` for the rationale) — operators who want routing behavior pick a specific fixed model and let Cursor's pool handle the call. All routes through the $0-marginal Cursor pool. Defer to claude-code when the chosen model is Claude and claude.ai Max is active (Max budget is cheaper marginal cost than burning Cursor pool tokens on Claude calls that have a dedicated Anthropic subscription path)." />
  </access-methods>

  <selection-algorithm>
    Run this procedure for every prompt that needs a model recommendation.
    Quality wins at every step; cost only enters at step 5. The
    jurisdiction filter (Step 0) runs first because a forbidden-
    jurisdiction model can never be recommended regardless of quality.

    Step 0 — Filter candidate models by allowed jurisdictions.
      Read the user's allowed-jurisdictions list from
      `docs/user-context.md` (the SaaS surface reads it from the
      user's `profiles.allowed_jurisdictions` column). Default when
      absent is `[us, eu, uk, ca, au, jp, kr]`. Drop every `<model>`
      whose `jurisdiction` attribute is not in the allowed list. The
      result is the input candidate set for Step 1.

      When the filter eliminates the otherwise-best model, the
      RATIONALE in the output MUST disclose the substitution — e.g.,
      "Kimi K2.5 was the strongest cost fit at this tier but was
      excluded by the jurisdiction filter (jurisdiction=cn, allowed
      list=[us, eu, uk, ca, au, jp, kr]); next-best fit returned
      instead." A silent filter is a worse experience than a
      transparent one.

      If the filter would eliminate every candidate (no allowed
      provider serves the task's PRIMARY at the required tier),
      emit a hard error rather than picking a forbidden model:
      "No allowed-jurisdiction model meets the required tier for
      this task. Either widen the allowed-jurisdictions list or
      lower the quality requirement."

      Models whose `jurisdiction` is `unknown` are treated as
      forbidden under the default-allow-list — the maintainer must
      editorially set the jurisdiction before such a model becomes
      recommendable.

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
        of S or A (currently: gemini-3-flash, gemini-3-pro, gemini-3.1-pro at S; sonnet-4.6, gpt-5.4, opus-4.7, opus-4.8, gpt-5.5 at A).
      - For PRIMARY = `long-context`, prefer models with native large
        context (opus-4.7 1M, opus-4.8 1M, gemini-3.1-pro 1M, grok-4.3 2M) over forcing
        a smaller-context model into Max Mode truncation.
      - For PRIMARY = `coding` at S-tier requirement, the candidate set is
        gpt-5.1-codex, gpt-5.3-codex, opus-4.7, opus-4.8, gpt-5.5; cost tie-breaker favors
        gpt-5.1-codex when the ratings are equivalent for the prompt.
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

    Routing meta-models (Cursor's "Auto" / "Premium" modes; analogous
    routers from other providers) are NOT enumerated in `<model-options>`.
    The catalog tracks fixed-engine models only — a routing model's
    benchmarks, jurisdiction, and cost are by construction unknowable in
    advance, which conflicts with the selector's per-model tier ratings
    and the `<jurisdiction-context>` filter. Users who want routing
    behavior should pick a specific fixed engine directly.

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
    - Teams plans: requests against fixed-model surfaces include the
      Cursor Token Rate.
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

  <orchestration-context>
    Orchestration (Claude Code's Dynamic Workflows feature, shipped
    with Opus 4.8 in May 2026) lets the model fan a single prompt
    out across parallel subagents from a script Claude writes and
    the runtime executes. Up to 1,000 agents per run, 16 concurrent.
    Intermediate results live in script variables, not the model's
    context window. Workflows can adversarially cross-check
    findings before reporting.

    Providers expose orchestration differently:

    - Claude Code (CLI, IDE extension): per-prompt opt-in by
      including the word "workflow" in the prompt; session-wide
      opt-in via /effort ultracode. Ultracode pins reasoning at
      xhigh AND auto-authors a workflow for every substantive
      task in the session.
    - All other surfaces (Cursor, Codex, Gemini CLI, claude.ai
      web, ChatGPT app, direct APIs): no equivalent built-in
      orchestration primitive at time of writing.

    Output mapping (the ORCHESTRATION field of the output format):
    `None` / `PerPrompt` / `Ultracode` / `N/A`.

    - Claude Code default → `None` (single-agent turn-by-turn).
    - Claude Code with `workflow` keyword on this prompt only →
      `PerPrompt`.
    - Claude Code with `/effort ultracode` session-wide → `Ultracode`.
    - Any non-Claude-Code platform → `N/A`.

    Decision rule (applied during <access-selection>):
    - PRIMARY task category `planning` with cross-cutting scope AND
      overall complexity High AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - PRIMARY task category `long-context` with multi-source
      cross-checking required (e.g., codebase audit, migration
      sweep, cited research) AND chosen access method is Claude
      Code → recommend `ORCHESTRATION: Ultracode`.
    - Single well-scoped deliverable (one file, one bug fix, one
      refactor) → `None` even on Claude Code.
    - Chosen access method's `exposes-orchestration` attribute is
      `no` → `N/A` regardless of the above.

    Cost note: Ultracode lifts the per-prompt token-cost ceiling
    ("token cost is not a constraint" per Anthropic's built-in
    framing). On claude.ai Max ($200/mo), per-call $ cost is $0
    marginal, but session budget burns 10-100x faster than High.
    Recommend Ultracode as a deliberate per-step opt-in, not as
    a default — pair with a session-budget-awareness clause in
    the rationale.

    Orchestration, thinking, and Max Mode are three orthogonal
    axes. Cursor + Max Mode + THINKING N/A + ORCHESTRATION N/A
    is valid. Claude Code + THINKING XHigh + ORCHESTRATION
    Ultracode is valid. Claude Code + THINKING XHigh +
    ORCHESTRATION None is also valid (Extra high effort, no
    auto-workflow).
  </orchestration-context>

  <jurisdiction-context>
    Some users restrict which model providers are acceptable based on
    the provider's HQ jurisdiction — typically driven by data-
    sovereignty, vendor-trust, regulatory-compliance, or export-control
    concerns. The selector supports this via the `jurisdiction`
    attribute on every `<model>` element and the
    `provider-jurisdiction` attribute on every `<method>` element,
    combined with an allowed-jurisdictions list the user supplies in
    `docs/user-context.md` (or the SaaS-side `profiles` row).

    Valid jurisdiction codes (ISO-3166-1 alpha-2-style, lowercase):

    - `us` — United States. Today: Anthropic, OpenAI, Google, xAI,
      Cursor.
    - `eu` — European Union member state.
    - `uk` — United Kingdom.
    - `ca` — Canada.
    - `au` — Australia.
    - `jp` — Japan.
    - `kr` — South Korea.
    - `cn` — China. Today: Moonshot (Kimi). Future Chinese-HQ
      entrants inherit this code.
    - `ru` — Russia. (No models on Cursor's pricing page from this
      jurisdiction at time of writing.)
    - `unknown` — provider HQ has not been editorially verified yet.
      Newly-auto-added models receive this code until the maintainer
      fills it in; the auto-add rule in `update/prompt.md` emits a
      warning so these don't ship silently.

    Default allowed list (assumed when `docs/user-context.md` carries
    no `<allowed-jurisdictions>` section):
    `[us, eu, uk, ca, au, jp, kr]` — a "five eyes plus close-aligned
    democracies" baseline. Users add or remove entries to widen or
    narrow.

    The base weights of a model and the operator of a model may
    carry different jurisdictions. The `jurisdiction` attribute
    reflects the OPERATOR — the entity whose terms govern the data
    flow when a call is placed. Composer 2 / Composer 2.5 are
    `us`-jurisdiction because Cursor operates them, even though
    their base weights derive from Moonshot's Kimi K2 series; the
    data path is governed by Cursor's privacy policy and US law.
    When base-weights origin matters for a user's compliance
    posture, the `best-for` attribute discloses the lineage so the
    user can decide whether to widen the filter further.

    Routing meta-models (e.g., Cursor's "Auto" and "Premium" modes;
    OpenRouter-style routers; any "router-of-routers") are NOT
    enumerated in `<model-options>` precisely because their routing
    is opaque — the selector cannot guarantee a specific call's
    jurisdiction without knowing the routed engine, and the routing
    decision is the routing provider's, not the user's. As of
    2026-05-21 roadmodel exposes only fixed-engine models. Users
    who want routing behavior should pick a specific fixed engine
    directly and accept that the underlying provider may pool-route
    among models of the same family.
  </jurisdiction-context>

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
             jurisdiction="us"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 57.3 (#2); LMArena Text #6 (Elo 1480.8); LMArena WebDev #2 (Elo 1562.4); AA-Omniscience 26.2 (#2)"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Deepest abstract and scientific reasoning, highest coherence on long unsupervised multi-step agent chains, best long-context recall at 1M tokens, 128K output ceiling for large single-shot deliverables, and novel problem-solving where high ambiguity demands creative judgment over pattern-matching" />
      <model id="opus-4.8" name="Opus 4.8"
             input-price-per-1m="$5.00" output-price-per-1m="$25.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="S" tier-agentic="A"
             tier-multimodal="A" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 61.4 (#1); HLE 45.7%; Terminal-Bench Hard 58.3%; τ²-bench airline pass_1 ~ (benchmark coverage expanding)"
             pricing-notes="Requires Max Mode on request-based plans; Fast mode (`claude-opus-4-8-fast`) requires Max Mode; Fast mode is 3x lower per-token pricing than Opus 4.7 fast mode; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Anthropic's Opus 4.7 successor at the same very-high tier pricing — placeholder tier ratings inherited from opus-4.7 pending benchmark coverage; the 3x cheaper fast-mode per-token rate (vs opus-4.7 fast mode) is the headline cost-structure change to surface in the next editorial pass" />
      <model id="gpt-5.5" name="GPT-5.5"
             input-price-per-1m="$5.00" output-price-per-1m="$30.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="S" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="D"
             headline-benchmarks="AA Intelligence Index 60.2 (#1); LMArena Text Elo 1463.9 (#16); HLE 44.3%; AA-Omniscience 20.1 (#3)"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; More token-efficient than GPT-5.4 on comparable tasks; Improved persistence on long-running tasks; Fast mode is available at higher rates; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="OpenAI's most capable frontier model and highest-cost GPT offering, best suited for the most demanding reasoning, long-horizon planning, and tasks where maximum intelligence is required regardless of cost — strongest single model for hard coding, agentic execution, and reasoning, but verify factual claims due to elevated hallucination" />
    </tier>
    <tier cost="high">
      <model id="sonnet-4.6" name="Sonnet 4.6"
             input-price-per-1m="$3.00" output-price-per-1m="$15.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 51.7; LMArena WebDev Elo 1522.9 (#7); AA-Omniscience 12.4; top-ranked tool-calling on Anthropic lineage"
             pricing-notes="Requires Max Mode on request-based plans; Up to 1M tokens in Max Mode at the same per-token rates (no long-context surcharge)"
             best-for="Top-ranked tool-calling and agentic execution globally, near-Opus coding quality at 2-3x the speed, strong mathematical reasoning (89% MATH), and complex but well-structured tasks needing reliable high-throughput multi-step implementation" />
      <model id="gpt-5.4" name="GPT-5.4"
             input-price-per-1m="$2.50" output-price-per-1m="$15.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="S"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="S"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 56.8 (#4); LMArena Text Elo 1456.3 (#19); GPT-5.4 (xhigh) Output Speed 91.9 tokens/s; lowest factual error rate among GPT models"
             pricing-notes="Hidden by default; Requires Max Mode on request-based plans; Agentic and reasoning capabilities; 90% discount on cached input tokens; Fast mode is 15% faster with 2x pricing; Long context (Max Mode) supports up to 1M tokens with 2x input pricing"
             best-for="Broadest professional domain expertise (outperforms human specialists in 83% of occupations), native computer-use capability surpassing human baselines, lowest factual error rate among GPT models, and cross-domain knowledge work requiring deep real-world accuracy and grounding" />
    </tier>
    <tier cost="medium">
      <model id="gpt-5.3-codex" name="GPT-5.3 Codex"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="B" tier-agentic="S"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="GPT-5.3 Codex (xhigh) listed on AA leaderboards; Codex lineage retains strong Terminal-Bench and SWE-bench Verified performance for autonomous coding"
             pricing-notes="Requires Max Mode on request-based plans; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.3-codex-high"
             best-for="Highest terminal and tool-use proficiency at the medium tier, most token-efficient autonomous coding, excels at long-running agentic sessions spanning debugging through deployment, and hard algorithmic problems requiring sustained code reasoning across languages — the cost-efficient pick for pure coding and agentic execution when an S-tier coding rating is needed" />
      <model id="gpt-5.2" name="GPT-5.2"
             input-price-per-1m="$1.75" output-price-per-1m="$14.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="B"
             tier-multimodal="C" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="MMLU Pro 81.4; GPQA 71.2; LiveCodeBench 66.9; 400K-token context; output speed 68 tokens/s; released 2025-12-10"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5.2-high"
             best-for="Earlier-flagship GPT reasoning model (December 2025) with 400K context and broad knowledge coverage (GPQA 71.2, MMLU Pro 81.4); same medium-tier pricing as GPT-5.3 Codex but lacks Codex's autonomous-coding specialization — pick gpt-5.3-codex over gpt-5.2 for coding/agentic tasks; gpt-5.2 fits when broad reasoning at A-tier knowledge and a 400K context window are the primary need at the medium price tier" />
      <model id="gemini-3.1-pro" name="Gemini 3.1 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 57.2 (#3); AA-Omniscience 32.9 (#1); HLE 44.7% (#1); LMArena Text Elo 1481.4 (#5); 1M-token context"
             pricing-notes="-"
             best-for="True native multimodal understanding (text, image, video, audio, and code in a single pass), 1M-token context optimized for heterogeneous inputs, strong agentic multi-step tool use, and synthesizing insights across large mixed-media datasets or sprawling document corpora — the obvious choice whenever multimodal or long-context is the primary category" />
      <model id="gemini-3-pro" name="Gemini 3 Pro"
             input-price-per-1m="$2.00" output-price-per-1m="$12.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="Gemini 3 generation Pro variant predating the 3.1 refresh; 1M-token context; native multimodal across text/image/video/audio/code"
             pricing-notes="Hidden by default"
             best-for="Gemini 3 family Pro model at the same medium-tier pricing as gemini-3.1-pro — pick gemini-3.1-pro over gemini-3-pro when both are available since 3.1 carries the updated benchmarks and is the canonical visible Gemini Pro; gemini-3-pro fits when reproducing earlier Gemini-3-generation outputs or when the 3.1 refresh's behavioral changes are undesirable for a specific workload" />
      <model id="gpt-5" name="GPT-5"
             input-price-per-1m="$1.25" output-price-per-1m="$10.00"
             jurisdiction="us"
             tier-coding="A" tier-planning="A" tier-agentic="A"
             tier-multimodal="B" tier-long-context="A" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="Earlier flagship GPT-5 family entry with agentic and reasoning capabilities at medium-tier output pricing; specific AA / LMArena numbers pending benchmark refresh"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities; Available reasoning effort variant is gpt-5-high"
             best-for="OpenAI's baseline GPT-5 family flagship — broad reasoning capability at medium-tier pricing ($10/M output), useful when a balanced GPT-5-class model is needed without the premium of GPT-5.4 / 5.5 and without the codex coding specialization; superseded by GPT-5.2 / 5.3 / 5.4 for most production use cases but available on Cursor's pool" />
      <model id="gpt-5.1-codex" name="GPT-5.1 Codex"
             input-price-per-1m="$1.25" output-price-per-1m="$10.00"
             jurisdiction="us"
             tier-coding="S" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="Earlier-generation Codex specialization at medium-tier output pricing; strong terminal and tool-use proficiency carried forward from the Codex lineage"
             pricing-notes="Hidden by default; Agentic and reasoning capabilities"
             best-for="Earlier Codex generation at the same medium-tier pricing as gpt-5.3-codex but $10/M output (gpt-5.3-codex is $14/M) — the lowest-cost S-tier coding model on the medium tier; prefer gpt-5.3-codex when latest-generation Codex quality matters, prefer gpt-5.1-codex when reproducing earlier-Codex-generation outputs or when the slightly cheaper output price compounds against a high-volume coding workload" />
    </tier>
    <tier cost="low">
      <model id="composer-2" name="Composer 2 (Fast)"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="CursorBench 61.3 (+37% over Composer 1.5); SWE-bench Multilingual 73.7; Terminal-Bench 2.0 61.7"
             pricing-notes="Hidden by default"
             best-for="Cursor's enforced default Composer model — purpose-built for multi-file agentic editing, fine-tuned on real developer sessions, self-summarizing 200K context for sustained long tasks, and frontier-level coding quality with speed-optimized inference at the lowest output price ($2.50/M) — the default choice for standard implementation, multi-file changes, and roadmap execution where coding-A is sufficient" />
      <model id="grok-4.3" name="Grok 4.3"
             input-price-per-1m="$1.25" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="S"
             tier-multimodal="B" tier-long-context="S" tier-knowledge="A"
             tier-speed="B"
             headline-benchmarks="AA Intelligence Index 53.2 (#7); AA-Omniscience 18.3 (#4); HLE 35.0%; LMArena Search Elo 1189.2"
             pricing-notes="Requires Max Mode on request-based plans"
             best-for="Latest Grok release with built-in multi-agent self-verification, configurable reasoning depth, and signature 2M-token context with hallucination-resistant grounding — leads the low tier on agentic execution and long-context, ideal when massive context, factual accuracy, and aggressive cost efficiency must coexist" />
      <model id="claude-4.5-haiku" name="Claude 4.5 Haiku"
             input-price-per-1m="$1.00" output-price-per-1m="$5.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 37.1; Output Speed 132.7 tokens/s; AA-Omniscience -4.2; latency leader among Claude family"
             pricing-notes="Hidden by default; Bedrock/Vertex: regional endpoints +10% surcharge; Cache: writes 1.25x, reads 0.1x"
             best-for="Speed-optimized lowest-cost Claude model, ideal for simple completions, high-volume repetitive tasks, and latency-sensitive workflows where a lightweight capable response matters more than deep reasoning" />
      <model id="gpt-5.4-mini" name="GPT-5.4 Mini"
             input-price-per-1m="$0.75" output-price-per-1m="$4.50"
             jurisdiction="us"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="A"
             headline-benchmarks="AA Intelligence Index 48.9 (xhigh); Output Speed 172.8 tokens/s; HLE 26.6% (GPT-5.4-mini xhigh)"
             pricing-notes="Hidden by default; Smaller, faster variant of GPT-5.4; 90% discount on cached input tokens"
             best-for="Lightweight GPT-5.4 variant balancing quality and cost, well-suited for straightforward coding, short-form generation, and high-throughput workloads needing solid GPT reasoning at a fraction of the flagship price" />
      <model id="gpt-5.4-nano" name="GPT-5.4 Nano"
             input-price-per-1m="$0.20" output-price-per-1m="$1.25"
             jurisdiction="us"
             tier-coding="C" tier-planning="D" tier-agentic="D"
             tier-multimodal="C" tier-long-context="C" tier-knowledge="C"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5.4 family variant; throughput-optimized inference"
             pricing-notes="Hidden by default; Smallest GPT-5.4 variant, optimized for cost; 90% discount on cached input tokens"
             best-for="Ultra-low-cost GPT variant for trivial text tasks, simple lookups, rapid classification, and extreme-throughput pipelines where cost efficiency is the sole constraint and task complexity is minimal" />
      <model id="composer-2.5" name="Composer 2.5"
             input-price-per-1m="$0.50" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="A" tier-planning="B" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="Composer 2 family successor at the same output price ($2.50/M); Cursor's release notes claim substantial intelligence + behavior improvements over Composer 2 trained on ~25x more synthetic tasks; specific benchmark numbers pending republish (CursorBench 61.3 + SWE-bench Multilingual 73.7 + Terminal-Bench 2.0 61.7 from Composer 2 carry forward as floors)"
             pricing-notes="-"
             best-for="Composer 2's successor at the same output price — Cursor's purpose-built multi-file agentic editor with frontier-level coding quality and speed-optimized inference; prefer over Composer 2 when both are available since 2.5 supersedes 2 within the same series per the equal-output-price replacement rule (Composer 2 is now Hidden by default on Cursor's pricing page)" />
      <model id="gemini-2.5-flash" name="Gemini 2.5 Flash"
             input-price-per-1m="$0.30" output-price-per-1m="$2.50"
             jurisdiction="us"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="A" tier-long-context="A" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="High-throughput Gemini Flash variant with native multimodal grounding; 1M-token context; designed for low-cost high-volume inference"
             pricing-notes="Hidden by default"
             best-for="Google's cheap, fast, multimodal Flash model at $0.30/M output — the cost-efficient pick for high-volume structured-output tasks (model recommendation, classification, light planning with strong system-prompt grounding) where multimodal capability matters and frontier-class reasoning does not; powers free-tier SaaS surfaces where per-call cost discipline is essential and the bundled templates do the structural heavy lifting" />
      <model id="gemini-3-flash" name="Gemini 3 Flash"
             input-price-per-1m="$0.50" output-price-per-1m="$3.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="A"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="A"
             tier-speed="S"
             headline-benchmarks="Gemini 3 generation Flash variant; native multimodal across text/image/video/audio; 1M-token context; throughput-optimized inference"
             pricing-notes="Hidden by default"
             best-for="Gemini 3 generation's cheap-tier model — meaningfully stronger planning, agentic, knowledge ratings than 2.5 Flash at slightly higher cost ($3.00/M output vs $2.50/M), with native multimodal-S; pick over 2.5 Flash when the task benefits from Gemini 3 family improvements and per-call cost discipline still matters" />
      <model id="gemini-3.5-flash" name="Gemini 3.5 Flash"
             input-price-per-1m="$1.50" output-price-per-1m="$9.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="A" tier-agentic="A"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="A"
             tier-speed="S"
             headline-benchmarks="AA Intelligence Index 55.3 (high reasoning); τ²-bench retail pass_1 45.6 (Gemini 3.5 Flash); Output Speed 217.6 tokens/s"
             pricing-notes="-"
             best-for="Auto-added cheap-tier Google model; pending editorial best-for refinement." />
      <model id="gpt-5-mini" name="GPT-5 Mini"
             input-price-per-1m="$0.25" output-price-per-1m="$2.00"
             jurisdiction="us"
             tier-coding="B" tier-planning="C" tier-agentic="C"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             headline-benchmarks="Cheapest GPT-5 family variant at $2.00/M output; throughput-optimized inference"
             pricing-notes="Hidden by default"
             best-for="The cheapest GPT-5 family variant at $2.00/M output — well-suited for trivial text tasks, simple lookups, rapid classification, and high-throughput pipelines where the cost-per-call is the binding constraint; not appropriate for multi-step planning or autonomous agentic execution; competitive with Gemini 2.5 Flash on cost but lacks Gemini's native multimodal-A rating" />
      <model id="kimi-k2.5" name="Kimi K2.5"
             input-price-per-1m="$0.60" output-price-per-1m="$3.00"
             jurisdiction="cn"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="C" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             headline-benchmarks="Moonshot AI's Kimi K2 series successor at $3.00/M output; competitive cost positioning across general text tasks; specific benchmark numbers pending refresh"
             pricing-notes="Hidden by default"
             best-for="Moonshot's affordable mid-volume model — a non-Google / non-OpenAI / non-Anthropic option at low-tier pricing for cost-conscious code and text generation when provider diversity is desired (vendor-risk hedging, regional preferences); routed via Cursor's pool only — no direct Moonshot access method is currently enumerated in the access-methods block" />
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
            provider-jurisdiction="us"
            requires="anthropic-api-key"
            supports-models="opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Programmatic / scripted Claude use outside Claude Code — raw API headers, batch endpoints, or features not surfaced by Claude Code. Falls back here when claude.ai Max budget is exhausted." />
    <method id="claude-code" name="Claude Code"
            provider="anthropic" billing="subscription-or-key"
            provider-jurisdiction="us"
            requires="claude-max-subscription OR anthropic-api-key"
            supports-models="opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="yes"
            best-for="Default for Claude coding or terminal tasks when a claude.ai Max subscription is active — $0 marginal cost until the Max budget is exhausted, full tool-use surface, runs as a CLI and as an IDE extension inside Cursor. Heavy Opus usage that would cost over $1,000/mo on per-token API is fully covered by a $100/mo Max plan." />
    <method id="claude-web" name="claude.ai web / desktop"
            provider="anthropic" billing="subscription-included"
            provider-jurisdiction="us"
            requires="claude-max-subscription"
            supports-models="opus-4.8,opus-4.7,sonnet-4.6,claude-4.5-haiku"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Chat-driven Claude use (no terminal, no codebase tool use) under the same Max budget that funds Claude Code — pick when the task is conversational rather than code-editing." />
    <method id="openai-api" name="OpenAI API"
            provider="openai" billing="per-token"
            provider-jurisdiction="us"
            requires="openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.1-codex,gpt-5,gpt-5.4-mini,gpt-5.4-nano,gpt-5-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Programmatic / scripted GPT use when an OpenAI API key is configured. Pay-per-token at OpenAI's published rates." />
    <method id="codex-cli" name="Codex"
            provider="openai" billing="subscription-or-key"
            provider-jurisdiction="us"
            requires="chatgpt-subscription OR openai-api-key"
            supports-models="gpt-5.5,gpt-5.4,gpt-5.3-codex,gpt-5.2,gpt-5.1-codex,gpt-5,gpt-5.4-mini,gpt-5-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Default for GPT-driven autonomous coding sessions when a ChatGPT Plus/Pro subscription is active — pays from the ChatGPT budget instead of the per-token API rate. Best surface for gpt-5.3-codex / gpt-5.1-codex on long-running terminal / agentic work." />
    <method id="chatgpt-app" name="ChatGPT (web / desktop)"
            provider="openai" billing="subscription-included"
            provider-jurisdiction="us"
            requires="chatgpt-subscription"
            supports-models="gpt-5.5,gpt-5.4,gpt-5,gpt-5.4-mini,gpt-5-mini"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Chat-driven GPT use without terminal or IDE integration; subscription-funded so marginal cost is $0 until ChatGPT's usage limits kick in." />
    <method id="google-api" name="Google AI Studio API"
            provider="google" billing="per-token"
            provider-jurisdiction="us"
            requires="google-api-key"
            supports-models="gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Programmatic / scripted Gemini use with a Google API key. Pay-per-token at Google's published rates. Powers the roadmodel SaaS free-tier surfaces (/recommend on Gemini 2.5 Flash; /roadmap on Gemini 2.5 Flash with 3.1 Pro escalation)." />
    <method id="gemini-cli" name="Gemini CLI"
            provider="google" billing="subscription-or-key"
            provider-jurisdiction="us"
            requires="gemini-advanced-subscription OR google-api-key"
            supports-models="gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Terminal-driven Gemini use; the CLI surface for multimodal and long-context Gemini work outside Cursor's pool." />
    <method id="gemini-app" name="Gemini (web / app)"
            provider="google" billing="subscription-included"
            provider-jurisdiction="us"
            requires="gemini-advanced-subscription"
            supports-models="gemini-3.1-pro,gemini-3-pro,gemini-3-flash,gemini-2.5-flash"
            exposes-max-mode="no" exposes-thinking="yes"
            exposes-orchestration="no"
            best-for="Chat-driven Gemini use under the Gemini Advanced subscription budget." />
    <method id="xai-api" name="xAI API"
            provider="xai" billing="per-token"
            provider-jurisdiction="us"
            requires="xai-api-key"
            supports-models="grok-4.3"
            exposes-max-mode="no" exposes-thinking="no"
            exposes-orchestration="no"
            best-for="Direct Grok API access for 2M-context or hallucination-resistant tasks; pay-per-token at xAI's published rates." />
    <method id="cursor" name="Cursor"
            provider="cursor" billing="subscription-pool"
            provider-jurisdiction="us"
            requires="cursor-pro-or-ultra-subscription"
            supports-models="opus-4.8,opus-4.7,gpt-5.5,sonnet-4.6,gpt-5.4,gpt-5.3-codex,gpt-5.2,gemini-3.1-pro,gemini-3-pro,gpt-5,gpt-5.1-codex,grok-4.3,claude-4.5-haiku,gpt-5.4-mini,gpt-5.4-nano,composer-2,composer-2.5,gemini-2.5-flash,gemini-3-flash,gemini-3.5-flash,gpt-5-mini,kimi-k2.5"
            exposes-max-mode="yes" exposes-thinking="no"
            exposes-orchestration="no"
            best-for="Cursor IDE — single Platform covering both UI modes (Composer for multi-file autonomous editing; Chat for interactive model-picker). The operator picks the mode at task time based on the chosen Model: composer-2 / composer-2.5 imply Composer mode; frontier models (opus-4.7, gpt-5.5, sonnet-4.6, etc.) imply Chat mode. Cursor's own Auto and Premium routing modes are deliberately NOT enumerated as roadmodel-recommendable models because their routing is opaque (see `jurisdiction-context` for the rationale) — operators who want routing behavior pick a specific fixed model and let Cursor's pool handle the call. All routes through the $0-marginal Cursor pool. Defer to claude-code when the chosen model is Claude and claude.ai Max is active (Max budget is cheaper marginal cost than burning Cursor pool tokens on Claude calls that have a dedicated Anthropic subscription path)." />
  </access-methods>

  <selection-algorithm>
    Run this procedure for every prompt that needs a model recommendation.
    Quality wins at every step; cost only enters at step 5. The
    jurisdiction filter (Step 0) runs first because a forbidden-
    jurisdiction model can never be recommended regardless of quality.

    Step 0 — Filter candidate models by allowed jurisdictions.
      Read the user's allowed-jurisdictions list from
      `docs/user-context.md` (the SaaS surface reads it from the
      user's `profiles.allowed_jurisdictions` column). Default when
      absent is `[us, eu, uk, ca, au, jp, kr]`. Drop every `<model>`
      whose `jurisdiction` attribute is not in the allowed list. The
      result is the input candidate set for Step 1.

      When the filter eliminates the otherwise-best model, the
      RATIONALE in the output MUST disclose the substitution — e.g.,
      "Kimi K2.5 was the strongest cost fit at this tier but was
      excluded by the jurisdiction filter (jurisdiction=cn, allowed
      list=[us, eu, uk, ca, au, jp, kr]); next-best fit returned
      instead." A silent filter is a worse experience than a
      transparent one.

      If the filter would eliminate every candidate (no allowed
      provider serves the task's PRIMARY at the required tier),
      emit a hard error rather than picking a forbidden model:
      "No allowed-jurisdiction model meets the required tier for
      this task. Either widen the allowed-jurisdictions list or
      lower the quality requirement."

      Models whose `jurisdiction` is `unknown` are treated as
      forbidden under the default-allow-list — the maintainer must
      editorially set the jurisdiction before such a model becomes
      recommendable.

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
        of S or A (currently: gemini-3-flash, gemini-3-pro, gemini-3.1-pro at S; sonnet-4.6, gpt-5.4, opus-4.7, opus-4.8, gpt-5.5 at A).
      - For PRIMARY = `long-context`, prefer models with native large
        context (opus-4.7 1M, opus-4.8 1M, gemini-3.1-pro 1M, grok-4.3 2M) over forcing
        a smaller-context model into Max Mode truncation.
      - For PRIMARY = `coding` at S-tier requirement, the candidate set is
        gpt-5.1-codex, gpt-5.3-codex, opus-4.7, opus-4.8, gpt-5.5; cost tie-breaker favors
        gpt-5.1-codex when the ratings are equivalent for the prompt.
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

    Step A0 — Filter access methods by allowed jurisdictions.
      Reduce `<access-methods>` to those whose
      `provider-jurisdiction` attribute is in the user's allowed-
      jurisdictions list from `docs/user-context.md` (default
      `[us, eu, uk, ca, au, jp, kr]`). This is a defense-in-depth
      pass against the Step 0 filter in `<selection-algorithm>`:
      it prevents a chosen model from being routed through a
      provider in a forbidden jurisdiction even if the model
      itself passed Step 0 (e.g., a US-operator model that's
      only reachable via a reseller in a restricted jurisdiction).
      In practice the two filters usually agree, but the two-step
      structure handles the edge case cleanly. Methods with
      `provider-jurisdiction="unknown"` are treated as forbidden
      under the default allowed list.

    Step A — Filter access methods by model support.
      Reduce the candidate set from Step A0 to those whose
      `supports-models` attribute lists the chosen model id.
      The result is the candidate set of platforms.

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
      time based on the chosen Model (composer-2 / composer-2.5
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

    Step E2 — ORCHESTRATION: apply the decision rule from
      <orchestration-context>. If the chosen method has
      `exposes-orchestration="no"`, emit ORCHESTRATION: N/A.
      Otherwise consider PRIMARY task category, scope, and
      complexity per the rule list. Default ORCHESTRATION: None
      for well-scoped single deliverables on Claude Code.

    Step F — Resolve MAX MODE against the chosen PLATFORM.
      Max Mode is a Cursor-surface concept. If the chosen access
      method's `exposes-max-mode` attribute is `no`, set MAX MODE
      `Off` in the output even when `<selection-algorithm>` Step 6
      enabled it — Max Mode does not apply outside Cursor. The
      `<selection-algorithm>` rationale for enabling Max Mode (long
      context, cross-cutting reasoning) still holds; it just manifests
      as native context-window use on non-Cursor surfaces.

    Step G — Emit PLATFORM, THINKING, ORCHESTRATION, and MAX MODE
      in the output. The PLATFORM field is the `name` attribute of
      the chosen access method. The RATIONALE must name (a) the
      subscription or API key that pays for the call (or note the
      lack thereof), (b) why the THINKING level was chosen (or why
      it is `N/A`), and (c) why ORCHESTRATION was chosen — and when
      ORCHESTRATION is `Ultracode`, the rationale must call out the
      session-budget caveat (claude.ai Max budget burns 10-100x
      faster than at High effort).

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
    - When the chosen model is a Cursor-only model (composer-2,
      composer-2.5), the only valid access method is `cursor`
      (the operator uses Composer mode at task time). Cursor's
      Auto and Premium routing modes are intentionally NOT
      recommendable engines per `<jurisdiction-context>` — if
      Cursor routing behavior is desired, the operator picks
      a specific fixed model and lets the Cursor pool handle
      the call, which keeps the catalog's tier ratings and
      jurisdiction filter meaningful.
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
ORCHESTRATION: [None/PerPrompt/Ultracode/N/A]
CONVERSATION: [New/Continue]
RATIONALE: [2-3 sentences that MUST name (a) the prompt's PRIMARY task
            category, (b) the recommended model's tier rating in that
            category, (c) at least one headline benchmark or named
            leaderboard from <benchmark-sources> supporting the choice,
            (d) the cost tie-breaker outcome if step 5 of the
            selection-algorithm applied, (e) the subscription or API
            key that pays for the chosen PLATFORM (or note its
            absence), (f) why the THINKING level was set as stated
            (or why it is N/A), and (g) why ORCHESTRATION was set to
            its value, including the session-budget caveat when
            Ultracode is recommended. Also note the conversation
            handling decision.]

Roadmap annotation mode — output one block per prompt, preceded by the
prompt identifier or a brief label, in order:

MODEL: [Model Name]
PLATFORM: [Access Method Name]
MAX MODE: [On/Off]
THINKING: [Off/Low/Medium/High/XHigh/N/A]
ORCHESTRATION: [None/PerPrompt/Ultracode/N/A]
CONVERSATION: [New/Continue]
RATIONALE: [2-3 sentences that MUST name (a) the prompt's PRIMARY task
            category, (b) the recommended model's tier rating in that
            category, (c) at least one headline benchmark or named
            leaderboard from <benchmark-sources> supporting the choice,
            (d) the cost tie-breaker outcome if step 5 of the
            selection-algorithm applied, (e) the subscription or API
            key that pays for the chosen PLATFORM (or note its
            absence), (f) why the THINKING level was set as stated
            (or why it is N/A), and (g) why ORCHESTRATION was set to
            its value, including the session-budget caveat when
            Ultracode is recommended. Also note the conversation
            handling decision.]
PROMPT: [Prompt # or short label]
