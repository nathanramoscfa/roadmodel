# Benchmarks & ratings

roadmodel recommends a model by scoring each catalogued model's **per-category
capability** and grounding the choice in public benchmarks. This page explains the
rating scale the recommender uses and the benchmarks it cites in its rationale.

> The app surfaces the same content on its in-product docs page and inline in every
> recommendation's rationale (each benchmark term links to its source). The glossary
> that powers those links is the source of truth; a test keeps this doc in sync.

## Rating scale

Every model carries a rating in each of seven categories — **coding, planning,
agentic, multimodal, long-context, knowledge, speed** — on an **S → D** scale.
**S** is the top "tier-list" rank, a step above A (the gaming convention for the
genuine best), then A, B, C, D:

| Rating | Meaning |
|:------:|---------|
| **S** | Top-1 or top-2 globally in this category. |
| **A** | Strong, reliable, near-frontier. |
| **B** | Competent. |
| **C** | Limited — usable only for trivial work. |
| **D** | Not suited for this category. |

The selection algorithm reads the prompt's complexity to set a **minimum required
rating** (High → S, Medium → A, Low → B) in the prompt's primary category, then picks
the highest-rated *available* model that clears the bar, breaking ties by the
secondary category and finally by cost. Ratings are an editorial synthesis of the
public benchmarks below (plus model cards and first-party reports), refreshed as new
results land.

## Benchmarks

The recommender grounds its rationale in these leaderboards. Links verified
2026-06-15.

| Benchmark | What it measures | Source |
|-----------|------------------|--------|
| LMArena | Human-preference Elo across general chat | <https://lmarena.ai/> |
| Artificial Analysis Intelligence Index | Composite of 10 evaluations (GPQA Diamond, Humanity's Last Exam, SciCode, Terminal-Bench Hard, …) | <https://artificialanalysis.ai/> |
| Aider polyglot | Coding across C++, Go, Java, JavaScript, Python, Rust | <https://aider.chat/docs/leaderboards/> |
| SWE-bench Verified | Real GitHub issues (500-instance human-filtered subset) — the gold standard for software-engineering capability | <https://www.swebench.com/> |
| LiveCodeBench | Contamination-free coding with rolling problems from LeetCode / AtCoder / Codeforces | <https://livecodebench.github.io/> |
| τ²-bench | Agentic / tool-use benchmark with a real tool–agent–user loop (airline, retail, banking) | <https://github.com/sierra-research/tau2-bench> |
| LiveBench | Contamination-resistant multi-domain benchmark | <https://livebench.ai/> |
| Terminal-Bench | Terminal and agent task-execution benchmark | <https://www.tbench.ai/> |
| GPQA Diamond | Graduate-level science-reasoning benchmark | <https://github.com/idavidrein/gpqa> |
| AIME | Advanced math-olympiad problems (LLM leaderboard via MathArena) | <https://matharena.ai/> |
| MMMU | Multimodal university-level understanding benchmark | <https://mmmu-benchmark.github.io/> |
| Humanity's Last Exam | Frontier-difficulty general-intelligence exam (HLE) | <https://agi.safe.ai/> |
| CursorBench | Cursor's benchmark from real coding sessions (terse prompts, multi-file solutions) | <https://cursor.com/blog/cursorbench> |
