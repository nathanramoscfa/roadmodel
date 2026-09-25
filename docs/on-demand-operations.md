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
| `claude-code` | `update-claude-code.yml` | Claude Code effort/thinking surface | ~$0.30–0.60 |
| `codex` | `update-codex.yml` | Codex reasoning levels | ~$0.30 |
| `gemini` | `update-gemini.yml` | Gemini thinking levels | ~$0.30 |
| `deepseek` | `update-deepseek.yml` | DeepSeek thinking modes | ~$0.30 |
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
4. a PR bumping `service/pyproject.toml` to `roadmodel[recommend]>=X.Y.Z`, merged
5. a wait until `https://roadmodel-api.vercel.app/healthz` reports `X.Y.Z`

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
