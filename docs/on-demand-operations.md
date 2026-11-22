# On-demand operations

Every scheduled job can also run on demand. The runner dispatches the job's own
workflow, waits for it, prints its Anthropic API cost and the PR it opened, and
can merge that PR once its checks pass.

## Three ways to run a job

| Where | How |
|---|---|
| **Mac terminal** | `scripts/run-now.sh <target> [--dry-run] [--merge]` |
| **GitHub app or web** | Actions → **Run now (on demand)** → Run workflow → pick the target |
| **Claude Code** | `/run-now <target>` or ask in plain words ("run the crons now") |

## Targets

| Target | Workflow | What it refreshes | API cost |
|---|---|---|---|
| `catalog` | `update-models.yml` | prices, models, tiers (Opus + web search) | ~$1–2 |
| `benchmarks` | `update-benchmarks.yml` | Artificial Analysis numbers + derived ratings | free |
| `launch-tables` | `update-launch-tables.yml` | a new model's launch-day table, its AA Index estimate and the letters derived from it | per try, capped at $4 a model and $10 a week (the ledger in `update/launch-tables.json`) |
| `claude-code` | `update-claude-code.yml` | Claude Code effort/thinking surface | ~$0.30–0.60 |
| `codex` | `update-codex.yml` | Codex reasoning levels | ~$0.30 |
| `gemini` | `update-gemini.yml` | Gemini thinking levels | ~$0.30 |
| `deepseek` | `update-deepseek.yml` | DeepSeek thinking modes | ~$0.30 |
| `defaults` | `update-default-efforts.yml` | each vendor's default effort (Anthropic and OpenAI APIs, Codex, xAI, Groq, z.ai) | free |
| `availability` | `probe-availability.yml` | which models answer | ~$0 |
| `soak` | `recommend-soak.yml` | production recommender smoke | recommender engine |
| `health` | `cron-health.yml` | the cron alarm | free |
| `crons` | all curation jobs, in schedule order | everything above except soak/health | ~$3–5 |

With `crons --merge`, each job's PR merges before the next job starts, so
every job builds on the one before it.

## Releases

`scripts/release.sh [X.Y.Z]` (or `/run-now release`) runs on the Mac, because
the tag is signed with the local key. A merge updates roadmodel.ai/models right
away. The recommender at /recommend changes only after a PyPI release **and** a
bump of the minimum roadmodel version in `service/pyproject.toml`. The script
does all of it and skips any step that is already done, so after a failure you
fix the cause and run it again:

1. a release PR (version bump; CHANGELOG `[Unreleased]` → `[X.Y.Z]`), merged
2. a signed `vX.Y.Z` tag, which builds, uploads to TestPyPI and verifies the install
3. the PyPI publish (`release.yml` dispatch) and the GitHub Release
4. a PR bumping `service/pyproject.toml` to `roadmodel[recommend]>=X.Y.Z`, merged.
   It opens 11 minutes after the PyPI upload, once every cached copy of the
   old package index has expired
5. a wait until `https://roadmodel-api.vercel.app/healthz` reports `X.Y.Z`

## Effort-token measurement automation

A ladder's Price and `/models` effort-adjusted price rest on how many output
tokens each model writes at each level (`docs/effort-tokens.json`). Only the
operator's Mac can measure that: the Claude Code and Codex lanes need its
sign-ins, and the rest run on OpenRouter with the key in its keychain
(`roadmodel/OPENROUTER_API_KEY`).

- `scripts/measure-weekly.sh --auto` runs every 2 hours (fast <1s `$0` no-op
  when nothing is missing): it measures any new/unmeasured model right away
  (`--models <missing> --rounds 1 --max-samples 12`), and on Sundays after
  10:00 runs a full top-up pass (`--max-samples 24`) to tighten noisy efforts
  to within ±10%. Running `scripts/measure-weekly.sh` without `--auto` runs a
  full top-up immediately. Both work in `~/.cache/roadmodel/measure-clone`
  (fetching tags with `--tags --force` so security baseline tags are present),
  close stale `chore/effort-tokens-*` PRs, open a PR, and land it with
  `private/security-tools/finish-security.sh`.
- `scripts/measure-weekly.sh --install` installs the 2-hour launchd job
  (`ai.roadmodel.measure-weekly`; log
  `~/Library/Logs/roadmodel-measure-weekly.log`). `--uninstall` removes it.
- OpenRouter spend is bounded by both `ROADMODEL_MEASURE_MAX_USD` per run
  (default $3) and `ROADMODEL_MEASURE_MAX_WEEKLY_USD` over any rolling 7 days
  (default $6). Subscription lanes (`claude-code`, `codex`) cost no cash.
- Any local run failure opens or updates one GitHub issue
  (`chore(effort-tokens): local measurement run failed`) and backs off for 12
  hours on the same unmeasured state until fixed or `main` advances; the next
  successful run closes it automatically.
- Until a new model is measured, it derives its verbosity from its same-series
  predecessor (`scoring.token_use` and `web/lib/pick-effort.ts`), or falls back
  to the uniform table only for an unmeasured brand-new series.

## When a run fails

- **"You have reached your specified API usage limits"**: the Anthropic org
  spend limit is hit. Raise it in the Console under Settings → Limits. Buying
  credits doesn't lift it.
- **A red curation PR**: the failing test names the model or file. Fix the
  source (`docs/model-selector.txt` or `docs/model-tier-cost-scale.md`),
  regenerate with `update/render_md.py` and `update/build_catalog.py`, and push
  to the PR's branch.
- **TestPyPI "No matching distribution"** during a release: the CDN hasn't
  caught up yet. Run `gh run rerun <id> --failed`, then run `scripts/release.sh`
  again.
- **The floor-bump PR's `roadmodel-api` build says "only
  roadmodel[recommend]<=OLD is available"**: that build read a cached copy of
  PyPI's index from before the upload. PyPI serves the index with
  `max-age=600`, and `uv` keeps it in the Vercel build cache. Push an empty
  commit to the PR's branch to rebuild, then run `scripts/release.sh` again.
