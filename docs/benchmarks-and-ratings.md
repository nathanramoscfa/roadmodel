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
| **S** | Frontier-class: at or within reach of the best in this category on the cited benchmarks — a class several models can share, so compare within it by the benchmark figures. |
| **A** | Strong, reliable, near-frontier. |
| **B** | Competent. |
| **C** | Limited — usable only for trivial work. |
| **D** | Not suited for this category. |

The selection algorithm reads the prompt's complexity to set a **minimum required
rating** (High → S, Medium → A, Low → B) in the prompt's primary category, then picks
the highest-rated *available* model that clears the bar, breaking ties by the
secondary category and finally by cost. Five ratings (coding, planning, agentic,
long-context, knowledge) are measured wherever Artificial Analysis publishes their
benchmark: planning, long-context and knowledge as the model's gap to the category
leader, agentic as its rank on Terminal-Bench 4.0, and coding as its rank on SciCode and
Terminal-Bench 4.0 averaged. Planning reads the AA Intelligence Index, AA's composite of
its whole evaluation suite, since no benchmark tests planning alone. Multimodal and speed
are estimates the daily catalog automation sets from the public benchmarks below (plus
model cards and first-party reports), refreshed as new results land, as is a measured
category's letter for a model Artificial Analysis has not measured; a new model starts
from its predecessor's letters. In the five measured categories an estimate stops at A:
S takes a measurement.

## Benchmarks

The recommender grounds its rationale in these leaderboards. Links verified
2026-06-15.

| Benchmark | What it measures | Source |
|-----------|------------------|--------|
| LMArena | Human-preference Elo across general chat | <https://lmarena.ai/> |
| Artificial Analysis Intelligence Index | Composite of 10 evaluations (v4.3: Humanity's Last Exam, SciCode, Terminal-Bench 4.0, AA-Omniscience, AutomationBench-AA, …); scores are not comparable across index versions | <https://artificialanalysis.ai/> |
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
