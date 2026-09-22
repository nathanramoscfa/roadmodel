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
| `quality` (0–100) | The model's standing in the task's category. The Artificial Analysis evidence figure for that category, min-max scaled across the measured catalog, blended 70/30 with the editorial S→D letter. Unmeasured models use the letter alone, discounted by 5 points (a letter without evidence is a prior, not a measurement) — except in a category with no evidence at all (multimodal), where every model is on its letter. An AA figure of exactly 0 is "not measured" (AA reports 0 tokens/s for endpoints it has not throughput-tested). | `docs/benchmarks.json` (AA) + `docs/catalog.json` letters |
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
| coding | Artificial Analysis Coding Index | letter |
| planning | Artificial Analysis Intelligence Index | letter |
| agentic | Terminal-Bench 2.1 | letter |
| long-context | AA-LCR | letter |
| knowledge | Humanity's Last Exam | letter |
| speed | median output tokens/s | letter |
| multimodal | — (editorial letter only) | letter |

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

## Integration path

1. **Now** — `roadmodel score` and the `score_candidates` MCP tool are
   advisory: run them after classifying a task to audit or override a
   prompt-driven pick.
2. **Next** — two-pass recommend: the engine classifies (category,
   complexity, novel), the scorer ranks, the engine writes the rationale for
   the scorer's primary/backup. Agreement between the prompt-driven pick and
   the scorer's top-1 is logged; disagreement rate becomes the first outcome
   metric.
3. **Then** — the ledger; priors → measured values; the selector prose
   shrinks to classification guidance and rationale style.
