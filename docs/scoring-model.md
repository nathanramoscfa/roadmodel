# The scoring model

`roadmodel.scoring` ranks *(model, platform, effort)* candidates in code. It
is the first slice of moving the selector's decision out of prose rules and
into a scoring function: the LLM classifies the task (category, complexity,
novel-or-not) and writes the rationale; the arithmetic over published data
and the operator's declared funding happens here, where it is testable,
explainable term by term, and cannot contradict itself.

Run it offline, no engine call:

```text
roadmodel score --category coding --complexity high --novel
roadmodel score --category planning --complexity medium --budget cheap --output json
```

or from an agent via the MCP tool `score_candidates(category, complexity,
novel, budget, top)` — neither needs a provider key.

## The formula

For every catalog model, reached through its best funded access method:

```text
score = quality − requirement_penalty − λ · K · decades(effective_cost)
```

| Term | What it is | Source |
| --- | --- | --- |
| `quality` (0–100) | The model's standing in the task's category. The Artificial Analysis evidence figure for that category, min-max scaled across the measured catalog (coding and agentic by rank instead: 0 for the lowest, 100 for the highest, ties sharing their mean rank; coding's figure is the mean of the model's percentile ranks on SciCode and Terminal-Bench 4.0, the evaluations AA's own Coding Index averaged), blended 70/30 with the S→D letter. Unmeasured models use the letter alone, discounted by 5 points (a letter without evidence is an estimate, not a measurement) — except in a category with no evidence at all (multimodal), where every model is on its letter. A throughput of exactly 0 tokens/s is "not measured" (AA reports it for endpoints it has not throughput-tested); an evaluation's 0 is a result. | `docs/benchmarks.json` (AA) + `docs/catalog.json` letters |
| `requirement_penalty` | 1.5 points per point the model falls short of the quality the task requires: Low → 30 (C band), Medium → 50 (B), High → 70 (A), High + novel / multi-step proof → 85 (S). Soft, not a filter, so a thin candidate set still ranks. | complexity |
| `effective_cost` | Blended list price (3 input : 1 output tokens per 1M) × *scarcity* of the platform's funding × the effort level's expected token multiplier. | catalog prices, user-context funding |
| `decades` | log₁₀(effective_cost / $0.02), floored at 0 — a 10× price step costs the same points anywhere on the range, and $0 is "free", not infinitely good. | — |
| `K` | The market exchange rate between price and quality, **in the score's own quality units**: the OLS slope of this category's blended quality on log₁₀(blended price) over every measured model (≈ 33–37 points per decade for coding / planning at the time of writing). Fitting on raw AA-index units and applying it to the stretched quality would understate the market line 2× and more. A category with no positive slope (speed — faster models are cheaper) anchors on the general-intelligence (planning) fit. Recomputed from the bundled data on every call. | fitted |
| `λ` | The share of `K` this operator applies to a decade of spend. λ = 1 ranks purely by value (the market-line residual — the same quantity the `/models` Score shows); λ → 0 ranks purely by quality. It is a budget factor (`cheap` 0.9 / `balanced` 0.5 / `best` 0.1) times a stakes factor (Low 1.6 / Medium 1.0 / High 0.55 / High + novel 0.27 — a failed attempt at a hard task costs far more than the price gap between two models). Under `balanced` that is roughly **30 / 18 / 10 / 5 quality points per decade of spend** for Low / Medium / High / novel: a routine task is a value decision, a novel hard one is a quality decision. | budget + complexity |

Coding-agent surfaces (Claude Code, Codex, Cursor) receive a +0.5 nudge on
coding / agentic / planning work, purely to break otherwise-tied costs toward
the surface a roadmap step actually runs on.

### Category → evidence

| Category | AA figure | Fallback |
| --- | --- | --- |
| coding | SciCode + Terminal-Bench 4.0 (mean rank), by rank | letter |
| planning | Artificial Analysis Intelligence Index | letter |
| agentic | Terminal-Bench 4.0, by rank | letter |
| long-context | AA-LCR | letter |
| knowledge | Humanity's Last Exam | letter |
| speed | median output tokens/s | letter |
| multimodal | — (letter only) | letter |

### Funding → scarcity

Funding is read from `user-context.md` the way `roadmodel.cost` reads it
(Active subscriptions, Active API keys, Local models), plus the
`Consumption headroom` line and the `Usage-pool status` table.

| Path | Scarcity (share of list price a token effectively costs) |
| --- | --- |
| local (Ollama, declared) | 0.0 |
| subscription, `uncapped` headroom | 0.0 — and effort goes to `max` |
| subscription, `capped` (default) with pool `headroom` | 0.35 |
| subscription, pool `tight` | 0.7 |
| subscription, pool `exhausted` (overflow on) | 1.0 — usage credits bill at list price |
| subscription, pool `exhausted`, `overflow off` | unfunded — unless the provider's API key is declared, in which case the surface runs on the key at list price |
| API key / per-token | 1.0 |
| no subscription and no key | unfunded — never chosen while a funded path exists |

A pool row matches a subscription when the row's name contains the tier's
name minus its price tag (`claude.ai Max — weekly` ↔ `claude.ai Max ($200)`),
or names the provider together with a plan word (`Anthropic Max weekly`); a
bare provider mention (an "Anthropic API budget" row) does not attach. A row
that names a model family (`… Fable 50% sub-cap`) applies only to that
family. The worst state among matching rows wins.

### Effort

The selector's `<thinking-context>` ladder, in code: Low → `low`,
Medium → `medium`, High → `high`, High + novel → `xhigh`; cross-cutting
planning / knowledge +1 rung; `best` +1; `cheap` on a path that costs
something −1; `uncapped` headroom on a free path → `max`. Under `capped`
the ladder tops out at `xhigh`. The effort's token multiplier (low 0.6,
medium 0.8, high 1.0, xhigh 1.6, max 2.5) feeds the cost term, so a higher
effort on a metered pool is priced, not free.

### Hard filters (before scoring)

Availability (`unavailable_models`), allowed jurisdictions (user-context, or
the `us, eu, uk, ca, au, jp, kr` baseline; a `local` access method passes
every list), the operator's `platforms.allowed` / `platforms.excluded` lists
(both the template's fenced form and the bold form; tokens that are not
access-method ids, such as `(none declared)`, are dropped, and an unknown id
is reported and ignored rather than read as "allow nothing"), and the access
method's own provider jurisdiction. Excluded models are reported with the
reason.

### Backup

The best-scoring candidate from a **different provider that the operator can
reach** (funded). When the user-context funds only one provider the result
carries `backup_warning` instead of an unreachable model name — an outage
or an exhausted pool needs somewhere to go, and naming a model the operator
cannot run is worse than saying so.

## Why these shapes

- **Log price, not a ratio.** Quality ÷ price is dominated by the two orders
  of magnitude in price and crowns the cheapest weak model. Points per
  decade treats a 10× step the same everywhere.
- **Market-fitted `K`, operator-scaled `λ`.** The one number that is
  genuinely arguable — how many quality points a decade of spend is worth —
  is anchored to what the market charges, and the operator's posture scales
  it rather than invents it.
- **Soft requirement.** A hard "adequate" filter returns nothing when the
  set is thin and hides *how* short a model falls. A steep penalty ranks
  everything and shows the shortfall.
- **Funding classes, not dollars alone.** On a flat subscription the thing
  being spent is a pool that is metered by model *and* effort; `scarcity`
  turns pool state into a comparable cost so the same formula ranks a
  subscription path against a pay-per-token one.

## What is a prior (and how it gets calibrated)

Every constant in `scoring.py` under "Priors" — the letter points, the
70/30 blend, the unmeasured discount, the requirement bands and slope, the
λ table, the complexity weights, the scarcity factors, the effort token
multipliers, the cost floor — is a named guess. The calibration path is a
**usage ledger**: per step, record model, effort, tokens in/out, pool draw,
pass/fail, retries, and review findings; then fit the multipliers and the
requirement bands to outcomes and replace the priors with measured values.
Until then the formula is transparent about which term drove a pick, which
is the property the prose rules could not offer.

## The Cost / Balanced / Quality ladder

/recommend's three picks are read off the operator's own cost/quality
frontier, in code (`scoring.ladder`):

1. **Pool.** `rank`'s candidates, every hard filter applied, one per model on
   its best platform: the funded ones, or every candidate when the
   user-context funds nothing (an anonymous caller).
2. **Frontier.** Among the pool, every model that scores higher on the AA
   Intelligence Index than every pool model at its blended list price or
   less: the rule /models draws, over the models this operator can run.
   List price, not the price they pay: on a subscription every covered model
   costs them $0, which would collapse the frontier to its top model, while
   list price is what a pick draws from a capped pool. A model the frontier
   leaves out (the same price as a stronger one, or dearer and weaker) is
   never a pick.
3. **Adequate.** Frontier points whose quality in the task's category meets
   the complexity's requirement (no requirement penalty). When none does, the
   frontier's best for the category stands alone.
4. **Rungs.** QUALITY is the adequate point that scores highest in the
   category; COST is the cheapest adequate point; BALANCED is the point
   between them with the best score at the balanced posture, or, with none
   between, the COST or QUALITY model run at the balanced posture's effort,
   whichever differs from both other rungs. Each rung's effort is
   `effort_for` its posture (cheap / balanced / best).
5. **Distinct picks.** When two adjacent rungs name the same model on the
   same platform, the lower one runs at least one effort level below the one
   above: BALANCED at most one level under QUALITY, then COST at most one
   level under BALANCED. Three columns that read the same offer no choice,
   and on a capped pool a lower effort is a real, cheaper option. Two rungs
   converge in two cases: at the dial's lowest level, and on an `uncapped`
   free path, where a lower effort saves the operator nothing (their declared
   flat-funding posture). A novel high-complexity planning task on Claude
   Max, ChatGPT Pro and Google AI Pro reads Sonnet 5.5 · High, Sonnet 5.5 ·
   XHigh, Opus 5.5 · XHigh; a row with one adequate model (knowledge, high,
   novel) runs it at three efforts.
6. **Native levels.** Each rung's level is set on its platform's own dial.
   `docs/catalog.json` records each access method's `effort_levels` (native
   names, lowest first) and, where the surface's docs distinguish models,
   `effort_levels_by_model`; `update/build_catalog.py` reads them only from
   the snapshots the daily trackers take of each surface's docs (Claude
   Code's effort table, Codex's `model_reasoning_effort`, the Gemini API's
   thinking levels for the Google AI Studio API, DeepSeek's
   `reasoning_effort`). `native_level` maps a scorer level to the native
   level of the same name, else the highest native level below it, else the
   dial's lowest: on Gemini 3.8 Flash (low / medium / high) the scorer's
   xhigh and max both read high. Step 5 compares levels on the native dial,
   so two scorer levels that land on one native level still give distinct
   picks. A method no tracker documents (Antigravity, the chat apps, Cursor)
   carries no levels, and its rows keep the scorer's word for the engine to
   map.
7. **Backups.** Each rung carries a backup from another maker
   (`Candidate.provider` differs from the rung model's): over the pool's
   models from other makers, draw the frontier and keep its adequate points;
   the backup is the adequate point with the highest list price at or below
   the rung's, else the cheapest adequate point above it, else (with no
   adequate point) the strongest for the category. It runs at the rung's
   posture's effort on its own platform's dial. With no other maker in the
   pool a rung has no backup and `backup_warning` says why. On Claude Max,
   ChatGPT Pro and Google AI Pro, Sonnet 5.5 and Opus 5.5 rungs back up to
   GPT-6.1 Sol on Codex (GPT-6 Astra on novel rows, where only it clears the
   bar); GPT-6 Luna rungs back up to Gemini 3.8 Flash on Antigravity from
   medium complexity up, and on low-complexity rows to the cheapest Gemini
   that clears the bar (Gemini 2.5 Flash or Gemini 3 Flash on the Gemini
   app), since no other maker's model costs Luna's $0.20 or less.

`ladder_table` computes the ladder for every classification (seven
categories × three complexities, plus novel high-complexity work: 28 rows,
about 0.4 s). In ladder mode the recommender appends the table to the prompt;
the engine classifies the task on a `CLASSIFICATION:` line and copies its
row's model, platform and effort into the three blocks, then writes the
settings and rationale. `novel` covers research-grade work only (an open
problem, a new algorithm, a multi-step proof); planning, architecture,
security hardening, design and refactors are `routine` at any difficulty. `recommend_structured_ladder` checks every rung
against the row and rewrites any that names another model or platform, so
the picks are the table's whatever the engine writes, and text injected
into a task can at most change its classification. On every platform with
documented levels it also sets each rung's EFFORT to the row's native level
(on Claude Code, Ultracode stands where the row says max), and it sets each
rung's BACKUP to the row's; such a pick carries a `backup_plan` (the
backup's platform and effort), which the service uses to show the backup on
the scorer's surface. The guard reports `mode: "frontier"`, the row, how it
was found (`declared`, or `matched` from the picks), the tiers rewritten,
the tiers whose effort was set (`effort_set`) and the tiers whose backup was
set (`backup_set`). The Step 7 backup guard, `suggest_cross_provider_backup`
and the service's AccessGuard stay in place as safety nets. A response the table cannot place keeps
the engine's own picks under the old tier-distinctness guard.

The table needs a user-context the scorer can read (the `user-context.md`
tables). The service writes its per-user context as prose for the engine, so
it renders a table-format twin from the same request
(`scoring_context_from_request`) and passes it as `scoring_context_text`.

## Integration path

1. **Done** — `roadmodel score` and the `score_candidates` MCP tool rank
   candidates for a classified task.
2. **Done** — /recommend's ladder: the engine classifies, the scorer's
   frontier ladder picks, the engine writes the rationale for the picks it
   is given, and code holds it to them.
3. **Then** — the ledger; priors → measured values; the selector prose
   shrinks to classification guidance and rationale style.
