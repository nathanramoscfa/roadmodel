# roadmodel

Two source-of-truth documents that drive an AI-assisted "which model should I
use?" recommendation workflow, plus a weekly automation that keeps prices and
benchmark numbers fresh against upstream sources.

## Legal and community

Licensed under [Apache-2.0](LICENSE) (Apache License, Version 2.0).
Third-party and bundled attributions are listed in [NOTICE](NOTICE). See
[CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, pull request scope,
and how to propose catalog edits; the [Code of Conduct](CODE_OF_CONDUCT.md)
applies in community spaces. Report security issues privately per
[SECURITY.md](SECURITY.md).

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

A third file, **[docs/model-selector.md](docs/model-selector.md)**, is a
human-readable Markdown rendering of `model-selector.txt`. It is auto-generated
from the `.txt` by [update/render_md.py](update/render_md.py); never hand-edit
it. The Monday refresh regenerates it after Opus updates the `.txt`, and a
schema test (`test_selector_md_is_in_sync_with_selector_txt`) fails CI if the
two drift.

A fourth file, **`docs/user-context.md`**, is a per-user config that tells
the selector which subscriptions and API keys you have so it can pick a
**platform** alongside a model. It is gitignored. The committed template
[`docs/user-context.example.md`](docs/user-context.example.md) shows the
schema; see [Local setup](#local-setup) below to wire up your own copy. The
selector falls back to a generic default if the file is absent.

`~/Documents/model-selector.txt` and `~/Documents/model-tier-cost-scale.md`
symlink here so existing references in other projects keep working.

## Schedule

A GitHub Actions cron runs at **Mondays 16:00 UTC** — see
[.github/workflows/update-models.yml](.github/workflows/update-models.yml).
The workflow can also be triggered manually:

```sh
gh workflow run update-models.yml --repo nathanramoscfa/roadmodel
```

## How the automation works

```
fetch upstream sources (sources.json)
  → strip HTML to text + capture inline data scripts
  → validate per-source min_bytes + must_contain_all
  → cap each source at 150KB
  → send everything + both current docs + prompt.md to Opus 4.7 (streaming)
  → Opus returns updated docs + summary + warnings as JSON
  → render_md.py regenerates docs/model-selector.md from the updated .txt
  → workflow commits all three docs to main if anything changed
```

Sources used (see [update/sources.json](update/sources.json)):

| Source | Form | Purpose |
| --- | --- | --- |
| `cursor.com/docs/models-and-pricing.md` | Markdown (Mintlify exposes raw `.md`) | Pricing + the Notes column |
| Artificial Analysis | JSON API (`AA_API_KEY` required) | AA Intelligence Index, AA-Omniscience, HLE, GPQA, AIME, MATH-500, output speed |
| LMArena | Parquet on HuggingFace Datasets | Elo across text / webdev / search subsets |
| SWE-bench | Raw JSON on GitHub | Coding agent leaderboard (Verified + Multilingual splits) |
| LiveCodeBench | Raw JSON on `livecodebench.github.io` | Contamination-free coding (per-model pass@1, aggregated by transform) |
| Aider polyglot | Raw YAML on GitHub | Per-model coding pass-rate |
| MMMU | Raw JSON on GitHub | Multimodal university-level scores |
| τ²-bench | Per-submission JSON on GitHub | Agentic / tool-use across airline, retail, banking |

The Artificial Analysis source replaced two previous scrapes — the AA SPA
and lastexam.ai — because AA's per-model evaluations payload includes the
HLE column. LiveBench, Terminal-Bench 2.0, and MathArena remain not in the
source list because none has a machine-readable aggregate feed (MathArena
exposes only HTML competition tables); existing claims that cite them stay
frozen at hand-set values per the prompt's preserve-verbatim rule.

### Why both Artificial Analysis AND dedicated sources for some benchmarks

AA's `evaluations` field covers 15+ benchmarks per model — including
`livecodebench` and `tau2` — so there is overlap with the dedicated
LiveCodeBench and τ²-bench sources. The dedicated sources are kept on
purpose. Two reasons:

1. **Detail.** AA exposes one number per benchmark per model. The
   dedicated sources expose breakdowns AA does not — LiveCodeBench by
   problem difficulty (easy / medium / hard), τ²-bench by domain
   (airline / retail / banking) and pass^k. Future claims like
   "τ²-bench airline pass^1 84.0" need the dedicated feed.
2. **Vendor risk hedging.** AA is a commercial service. If they change
   the free-tier terms, alter the schema, or shut down, the dedicated
   raw-data sources keep working — they live in public GitHub repos
   and HuggingFace Datasets. This is consistent with the project's
   broader "raw data over scrape, multiple paths over one" stance.

In practice: AA is the **breadth** source (one fetch, many headline
numbers). Dedicated sources (LCB, τ²-bench, SWE-bench, Aider, MMMU,
LMArena) are **depth** sources for the capabilities they specialize
in. The prompt cites them by name; the cron just keeps them all
flowing.

### AA payload is filtered to Cursor's catalog

The AA API returns 500+ models, most of which are open-weight or
legacy entries that aren't in Cursor's pricing table and therefore
can't appear in `<model-options>`. The `aa_api` transform reads
Cursor's pricing markdown and intersects the AA list with it via a
token-set match (handles Cursor "Claude 4.7 Opus" ↔ AA "Claude Opus
4.7" / `claude-opus-4-7` and reasoning-effort variants in one shot).
Net payload: ~60 KB instead of ~300 KB. If the Cursor fetch fails or
the filter would drop everything, the transform falls through to the
unfiltered list rather than starve Opus of HLE / Intelligence Index
data.

## What auto-maintains vs what's editorial

**Auto-maintained on each run** (driven by [update/prompt.md](update/prompt.md)):

- Per-model pricing (Input / Cache Write / Cache Read / Output) in both docs
- Tier classification by output price
- The Notes column in `model-tier-cost-scale.md`
- The `pricing-notes="…"` attribute on each `<model>` in `model-selector.txt`
- The full Cursor catalog in `model-tier-cost-scale.md` (additions and removals follow Cursor's `.md`)
- The set of `<model …/>` entries in `<model-options>` of `model-selector.txt`. **Add is two-phased**: Cursor's pricing-table row lands in `model-tier-cost-scale.md` immediately; the `<model …/>` element in `<model-options>` is added on the first refresh where fetched benchmark sources contain ≥2 verifiable numeric facts about the model (otherwise deferred with a warning — Cursor typically lists models before third-party leaderboards index them). **Remove** only when Cursor discontinues the model OR a same-series successor exists at ≤ output price. Costlier successors do NOT displace predecessors. See [update/prompt.md](update/prompt.md) "Model lifecycle in `<model-options>`" for the rules and `same-series` definition.
- The `(currently: …)` enumeration in the multimodal guardrail and the coding S-tier candidate-set enumeration inside `<selection-algorithm>` — kept in sync with `<model-options>` membership when models are added/removed
- Headline benchmark **numbers** — in-place numeric replacement within existing claims only; no claim swapping, no claim deletion, no new claims (see prompt section "Headline benchmarks")
- The "Existing model-selector.txt Classification Audit" and "Recently Added" tables

**Editorial — never auto-changed**:

- The S/A/B/C/D `tier-*` ratings on **existing** `<model …/>` elements (newly added models receive auto-assigned ratings, but ratings on already-present models are preserved verbatim — override at any time and subsequent refreshes will respect your edit)
- The `best-for` description on **existing** `<model …/>` elements (same protection — auto-generated only on first add)
- The long-context guardrail and the `Default to composer-2 …` guardrail inside `<selection-algorithm>` (context-window sizes and editorial defaults — not auto-derivable from `<model-options>`)
- `<benchmark-sources>`, `<task-categories>`, `<conversation-principles>`, `<output-format>`, and the rest of the `model-selector.txt` framing
- The "Tier Boundaries" table

When Cursor ships a new model, the Monday refresh adds the row to
`model-tier-cost-scale.md` immediately and emits a warning. The
`<model …/>` element in `<model-options>` is added on the first refresh
where fetched benchmark sources have ≥2 verifiable numeric facts about
the model — typically days to weeks after Cursor lists it, since
leaderboards index new models on a lag. Both phases emit warnings for
visibility. After the entry lands, you can override the auto-assigned
tier ratings or `best-for` in a follow-up commit; subsequent refreshes
preserve your edits verbatim. To preview what the next refresh would
change without committing, run `python update/update_models.py --dry-run`
(prints diff + warnings to stdout). To exercise the lifecycle rules
against a synthetic Cursor pricing payload, pass
`--fixture path/to/sources.json` — see the script's `--help` for the
fixture shape.

## Local setup

The recommender needs to know which subscriptions and API keys you have
to recommend a **platform** alongside a model. On first checkout, copy
the committed template to a local-only file and fill in your real values:

```sh
cp docs/user-context.example.md docs/user-context.md
$EDITOR docs/user-context.md
```

`docs/user-context.md` is **gitignored** — it never appears in `git
status`, never gets committed, and never goes to GitHub. The template
ships with `$XXX` placeholders for dollar amounts and `Yes/No`
placeholders for API-key state; replace them with your real values. If
you skip this step entirely, the selector falls back to a generic
default platform preference order.

Phase 1.2 of [the public roadmap](#repo-layout) will swap this
markdown-file pattern for a `roadmodel.toml` config; the example /
real split remains.

## Local run

```sh
conda create -n roadmodel python=3.12 -y
conda activate roadmodel
pip install -r update/requirements.txt
set -a; [ -f .env ] && . .env; set +a   # exports ANTHROPIC_API_KEY, AA_API_KEY
python update/update_models.py
```

The script writes back into `docs/`. Inspect the diff with `git diff docs/`.
A successful run also writes `update/.last-summary.txt` and (if any)
`update/.last-warnings.txt` — both gitignored.

### Preview a refresh without committing (`--dry-run`)

Run with `--dry-run` to print the diff + warnings stdout-only, no
file writes:

```sh
python update/update_models.py --dry-run
```

### Smoke-test the lifecycle rules (`--fixture`)

The Model lifecycle rules in [update/prompt.md](update/prompt.md)
(don't drop a model when a costlier same-series successor appears;
auto-add new models with B-default tier ratings; keep
`<selection-algorithm>` guardrail enumerations in sync) only fire
when Cursor ships a new model. To exercise them on demand against
synthetic pricing:

```sh
# Build a fixture: live upstream sources + an injected synthetic row
python update/build_fixture.py costlier-successor \
    --output tests/fixtures/costlier_successor.json

# Preview what the LLM would do (one Opus call, ~$0.50-1.00)
python update/update_models.py --dry-run \
    --fixture tests/fixtures/costlier_successor.json
```

Two scenarios ship in [update/build_fixture.py](update/build_fixture.py):

- `costlier-successor` — injects GPT-5.6 at $40/M output. Expected:
  add `gpt-5.6`, **keep** `gpt-5.5` and `gpt-5.4` (no supersession).
- `cheaper-successor` — injects GPT-5.6 at $25/M output. Expected:
  add `gpt-5.6`, **remove** `gpt-5.5` (superseded, $25 ≤ $30),
  **keep** `gpt-5.4` ($25 > $15).

Generated fixtures land in `tests/fixtures/` and are gitignored —
the generator is the durable artifact, since committed fixtures
freeze the benchmark and pricing snapshots the LLM sees, which
ages quickly. Re-run the generator whenever you want a fresh
smoke test against current upstream data.

## Tests

A separate workflow ([.github/workflows/tests.yml](.github/workflows/tests.yml))
runs daily at 12:00 UTC, on every push to `main`, on every PR, and on
`workflow_dispatch`. The suite has three tiers (see [tests/](tests/)):

- **Live source health** ([tests/test_sources_live.py](tests/test_sources_live.py))
  — actually fetches every URL in `sources.json`, runs the same fetch /
  normalize / validate pipeline the Monday refresh runs, and asserts
  source-specific facts (Cursor `.md` has the Opus 4.7 row at $5, the
  Notes column is populated, ≥30 model rows present, Aider YAML parses
  with ≥50 entries). Catches upstream regressions *before* the Monday
  refresh hits them.
- **Schema and cross-doc consistency** ([tests/test_doc_schema.py](tests/test_doc_schema.py))
  — every `<model>` element has all 14 required attributes; every
  cost-scale table has the 7-column header; prices and pricing-notes
  match byte-for-byte across the two docs; tier-cost groupings match
  output prices. Catches bot drift.
- **Freshness** ([tests/test_freshness.py](tests/test_freshness.py)) —
  fails if the most recent `model-selector-bot` commit is older than
  14 days, signalling a stuck cron.

Run locally:

```sh
pip install -r tests/requirements.txt
pytest tests/ -v
```

## Auto-remediation

When the **scheduled** daily Tests run on `main` fails, a separate
workflow ([.github/workflows/auto-remediate.yml](.github/workflows/auto-remediate.yml))
fires. It uses [`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action)
to invoke Claude Sonnet 4.6 with the failure logs and a tightly-scoped
remediation prompt.

### Modes

The workflow has two modes, controlled by the `AUTO_REMEDIATE_MODE`
env var at the top of the workflow file. Edit the single line to flip:

- **`auto-merge` (default)**: Claude iterates up to 3 attempts. The
  first attempt that produces a clean `pytest tests/ -v` opens a PR
  and squash-merges it immediately. If all 3 attempts fail, Claude
  opens a **GitHub Issue** instead — labeled `needs-attention` —
  detailing what was tried, why each attempt failed, and concrete
  next-step suggestions for you (e.g. "consider replacing this
  source with X", "this benchmark may need to be dropped").
- **`pr-only`**: Claude makes one attempt and opens a PR for human
  review. Never merges. Use this if you want eyes on every fix.

### Scope

- **In scope to edit**: `update/sources.json` (URLs, validate rules,
  max_bytes), and the fetch/strip/validate helpers in
  `update/update_models.py` (`fetch`, `normalize_content`,
  `strip_html`, `looks_like_html`, `validate_content`).
- **Out of scope, in BOTH modes**: `update/prompt.md`, anything in
  `docs/`, test files, workflow files, README, requirements files.
  Loosening a test as a "fix" is forbidden. Removing a source
  entirely is forbidden — that's an editorial decision and goes via
  the issue path.

### Loop prevention

Trigger is filtered to scheduled workflow_run failures on `main` only.
Push and PR runs of remediation branches running their own tests
cannot re-trigger remediation. A concurrency group also prevents
pile-up.

## Repo layout

```
.
├── docs/
│   ├── model-selector.txt              # the recommender doc (source of truth)
│   ├── model-selector.md               # human-readable mirror, auto-generated
│   ├── model-tier-cost-scale.md        # the price/tier reference
│   ├── user-context.example.md         # public template for per-user selector config
│   ├── user-context.md                 # local, gitignored: real subscription/API-key state
│   ├── templates/
│   │   ├── project-roadmap-template.md # roadmap builder: project-level template
│   │   └── phase-roadmap-template.md   # roadmap builder: phase-level template
│   └── archive/
│       └── roadmap-v1.md               # historical roadmap (frozen)
├── update/
│   ├── update_models.py                # fetch + strip + validate + call Opus
│   ├── render_md.py                    # render model-selector.txt → .md
│   ├── build_fixture.py                # synthesize sources.json fixtures for lifecycle tests
│   ├── prompt.md                       # system prompt (the rules Opus follows)
│   ├── sources.json                    # upstream URLs + per-source validation
│   └── requirements.txt                # anthropic, beautifulsoup4, requests
├── tests/
│   ├── test_sources_live.py            # live upstream-health checks
│   ├── test_doc_schema.py              # schema + cross-doc consistency
│   ├── test_subscription_freshness.py  # user-context.md staleness check
│   ├── test_freshness.py               # cron-heartbeat check
│   └── requirements.txt                # pytest, pyyaml
├── .github/workflows/
│   ├── update-models.yml               # weekly refresh (Mondays 16:00 UTC)
│   ├── tests.yml                       # daily tests + on push/PR
│   ├── auto-remediate.yml              # opens PR when daily tests fail
│   └── claude.yml                      # on-demand Claude Code action
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
- **`AA_API_KEY is not set`** during fetch — the Artificial Analysis
  source needs a free API key. Sign up at
  https://artificialanalysis.ai/login (1000 req/day free tier),
  generate a key, and add it to the environment locally and to GitHub
  Actions secrets via `gh secret set AA_API_KEY --repo …`. Without it,
  the AA + HLE column data is missing from the run; per the prompt's
  "kept stale-by-default" rule, claims citing those sources stay
  verbatim, but they won't be re-verified until the key is set.
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
