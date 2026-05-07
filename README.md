# model-selector

Two source-of-truth documents that drive an AI-assisted "which model should I
use?" recommendation workflow, plus a weekly automation that keeps prices and
benchmark numbers fresh against upstream sources.

## The two documents

- **[docs/model-selector.txt](docs/model-selector.txt)** — the recommender.
  Selection criteria, per-model pricing, tier ratings, headline benchmark
  numbers, pricing notes (Cursor IDE hovertext), and the selection algorithm.
  Reference it from a chat with `@model-selector.txt` (or paste its contents)
  alongside any prompt and the AI returns a `MODEL / MAX MODE / CONVERSATION
  / RATIONALE` block grounded in the file's criteria.
- **[docs/model-tier-cost-scale.md](docs/model-tier-cost-scale.md)** — the
  output-price-tier classification reference. Full Cursor catalog with
  per-model Input / Cache Write / Cache Read / Output prices, tier
  (Low / Medium / High / Very High by output price), and Notes (the
  hovertext column from Cursor's pricing page).

`~/Documents/model-selector.txt` and `~/Documents/model-tier-cost-scale.md`
symlink here so existing references in other projects keep working.

## Schedule

A GitHub Actions cron runs at **Mondays 16:00 UTC** — see
[.github/workflows/update-models.yml](.github/workflows/update-models.yml).
The workflow can also be triggered manually:

```sh
gh workflow run update-models.yml --repo nathanramoscfa/model-selector
```

## How the automation works

```
fetch upstream sources (sources.json)
  → strip HTML to text + capture inline data scripts
  → validate per-source min_bytes + must_contain_all
  → cap each source at 150KB
  → send everything + both current docs + prompt.md to Opus 4.7 (streaming)
  → Opus returns updated docs + summary + warnings as JSON
  → workflow commits to main if anything changed
```

Sources used (see [update/sources.json](update/sources.json)):

| Source | Form | Purpose |
| --- | --- | --- |
| `cursor.com/docs/models-and-pricing.md` | Markdown (Mintlify exposes raw `.md`) | Pricing + the Notes column |
| Artificial Analysis | HTML strip | AA Intelligence Index, AA-Omniscience |
| LMArena | HTML strip | Elo across categories |
| SWE-bench | HTML strip | Coding benchmark presence |
| Aider polyglot | Raw YAML on GitHub | Per-model coding pass-rate |
| MMMU | Static HTML | Multimodal university-level scores |
| Humanity's Last Exam | HTML strip | Frontier-difficulty scores |

LiveBench and Terminal-Bench 2.0 are intentionally not in the source list —
both are JS-rendered SPAs with no machine-readable feed. Existing claims that
cite them stay frozen at hand-set values per the prompt's preserve-verbatim rule.

## What auto-maintains vs what's editorial

**Auto-maintained on each run** (driven by [update/prompt.md](update/prompt.md)):

- Per-model pricing (Input / Cache Write / Cache Read / Output) in both docs
- Tier classification by output price
- The Notes column in `model-tier-cost-scale.md`
- The `pricing-notes="…"` attribute on each `<model>` in `model-selector.txt`
- The full Cursor catalog in `model-tier-cost-scale.md` (additions and removals follow Cursor's `.md`)
- Headline benchmark **numbers** — in-place numeric replacement within existing claims only; no claim swapping, no claim deletion, no new claims (see prompt section "Headline benchmarks")
- The "Existing model-selector.txt Classification Audit" and "Recently Added" tables

**Editorial — never auto-changed**:

- Which models appear in `<model-options>` of `model-selector.txt`
- The S/A/B/C/D `tier-*` ratings on each model
- The `best-for` description on each model
- `<benchmark-sources>`, `<task-categories>`, `<selection-algorithm>`, `<conversation-principles>`, `<output-format>`, and the rest of the `model-selector.txt` framing
- The "Tier Boundaries" table

When Cursor ships a new model and you want it recommendable, hand-add a
`<model …/>` element to `<model-options>` with your editorial tier ratings,
headline benchmarks, pricing-notes (copy from cost-scale doc), and best-for
description. The bot will keep its prices fresh from then on but will never
add it for you.

## Local run

```sh
conda create -n model-selector python=3.12 -y
conda activate model-selector
pip install -r update/requirements.txt
set -a; [ -f .env ] && . .env; set +a   # exports ANTHROPIC_API_KEY
python update/update_models.py
```

The script writes back into `docs/`. Inspect the diff with `git diff docs/`.
A successful run also writes `update/.last-summary.txt` and (if any)
`update/.last-warnings.txt` — both gitignored.

## Repo layout

```
.
├── docs/
│   ├── model-selector.txt          # the recommender doc
│   └── model-tier-cost-scale.md    # the price/tier reference
├── update/
│   ├── update_models.py            # fetch + strip + validate + call Opus
│   ├── prompt.md                   # system prompt (the rules Opus follows)
│   ├── sources.json                # upstream URLs + per-source validation
│   └── requirements.txt            # anthropic, beautifulsoup4, requests
├── .github/workflows/
│   └── update-models.yml           # weekly cron + workflow_dispatch
├── .gitignore
└── README.md
```

## Troubleshooting

- **429 rate-limit error during run** — input payload exceeded 500K
  tokens/min. Means a fetched source ballooned (likely a new SPA shipping
  bundled JS). Tighten `max_bytes` for that source in `sources.json` or
  drop it if it has no machine-readable form.
- **`anthropic.APIError: 401`** — `ANTHROPIC_API_KEY` is missing or wrong.
  Repo secret is set via `gh secret set ANTHROPIC_API_KEY --repo …`.
- **Validation failure on a source** — log line shows
  `<url>: validation failed: <reason>`. Either upstream changed shape
  (update `must_contain_all` / `min_bytes`) or the page is genuinely
  empty (drop it). Validation failures are warnings, not run failures —
  Opus continues with the remaining sources.
- **Run committed nothing** — if the docs already match upstream, the
  workflow exits cleanly without a commit. Check the run log's `summary`.

## CLI tooling

- **GitHub CLI (`gh`)**: `brew install gh && gh auth login`. Used for repo
  secrets, manual workflow triggers, run logs.
