# Catalog Refresh — Manual Fallback Procedure

The catalog-refresh cron in
[`.github/workflows/update-models.yml`](../.github/workflows/update-models.yml)
opens a PR that refreshes [`docs/model-selector.txt`](model-selector.txt),
[`docs/model-tier-cost-scale.md`](model-tier-cost-scale.md), the rendered
[`docs/model-selector.md`](model-selector.md), and the machine-readable
[`docs/catalog.json`](catalog.json) in a single commit. This document covers
the manual fallback when the cron fails or when a correction is needed
between runs.

## What starts a refresh

The cron checks every hour. Each run reads every provider's own pricing page
(`update/extract_*_catalog.py`) and the Codex model list, then
`update/check_sources.py` compares them, Cursor's pricing page and the model
names the docs trackers have seen with the last run's signature:

- **A provider's own source changed** (a new model or price on Google's,
  Anthropic's or OpenAI's page, or a tracker naming a new model): the
  deterministic refresh runs within the hour and adds, prices or retires
  models by rule. No model call.
- **Cursor's page changed:** on the daily 16:00 UTC run, the curation pass
  (Opus) runs too, for Cursor's own models and the models Cursor offers.
- **Nothing changed:** the run stops after the gate.

A price reader that fails keeps its committed snapshot and opens one
`catalog-reader-failure` issue, closed on the first run it reads again.

## How a model joins or retires

A refresh PR merges itself when the gate admits it
(`update/automation_integrity.py`), and since 2026-11 that includes models:

- **A new model** a provider's own page prices joins when a second source
  (a docs tracker or a vendor's default-effort table) names it too. It is
  written from the template in `update/lifecycle_rules.py` — id, name,
  prices, its predecessor's letters (or the B placeholder for a new series),
  jurisdiction, a fixed pricing note — and its prose is written from data.
  The gate rebuilds that template and refuses anything else in the element.
- **Another name for a carried model** (Anthropic's "Claude Mythos N" for
  Fable N) is declined, not added.
- **A retirement** (`update/supersede.py`) merges with its tags, the letters
  it moves and the effort ratings.

The price readers map every carried model by name, so a model added this way
is priced from its provider's page on every later run. What the gate still
refuses — the curation pass's own prose or decline reasons — waits in the
draft PR from `chore/catalog-review`. A later refresh that passes the gate
whole closes that draft, since nothing in it still waits.

## When to run manually

Run this procedure whenever any of the following hold:

- **Cron failure.** The weekly run on
  [Actions → Update roadmodel catalog docs](https://github.com/nathanramoscfa/roadmodel/actions/workflows/update-models.yml)
  reported a red status (fetch failure, Opus JSON parse failure, determinism
  guard tripped, etc.) and the catalog has not refreshed.
- **Urgent catalog correction between Mondays.** A provider published a
  price or model change that materially affects selection output and you
  do not want to wait for the next scheduled run.
- **`tests/test_freshness.py` is failing locally or on `main`** because
  the bot's last commit to `docs/` is older than the 14-day threshold.

Do not run this procedure for editorial-only changes (typo fixes, prose
tweaks) — those should be plain PRs that do not touch
`docs/catalog.json`.

## How to run manually

1. **Clone and branch.** From a clean working tree:

   ```bash
   git clone https://github.com/nathanramoscfa/roadmodel.git
   cd roadmodel
   git checkout -b chore/catalog-refresh-$(date -u +%Y-%m-%d)
   ```

2. **Install the update tooling.**

   ```bash
   pip install -r update/requirements.txt
   ```

3. **Refresh the prose docs.** Provide the same secrets the cron uses
   (`ANTHROPIC_API_KEY` and `AA_API_KEY`) in your environment:

   ```bash
   python update/update_models.py
   ```

   This rewrites `docs/model-selector.txt`,
   `docs/model-tier-cost-scale.md`, and `docs/model-selector.md`.

4. **Rebuild the catalog JSON.** This step is deterministic — running it
   twice against unchanged prose docs MUST produce byte-identical output:

   ```bash
   python update/build_catalog.py
   ```

5. **Open the PR.** Stage all four artifacts together so the catalog
   commit-set stays self-consistent:

   ```bash
   git add docs/model-selector.txt docs/model-selector.md \
           docs/model-tier-cost-scale.md docs/catalog.json
   git commit -m "Manual catalog refresh: $(date -u +%Y-%m-%d)"
   git push -u origin HEAD
   gh pr create --base main --fill
   ```

## Verification

Before merging, confirm the schema and cross-reference tests pass:

```bash
pytest tests/test_doc_schema.py tests/test_freshness.py tests/test_catalog_json.py
```

All three suites MUST be green. `test_catalog_json.py` in particular
catches divergence between `catalog.json` and the prose docs (price
mismatches, missing models, missing access methods, non-deterministic
output).

## Cross-reference with the cron

When this manual PR is opened because the Monday cron failed, link the
two so future maintainers can trace the recovery path:

- In the manual PR description, add a `Resolves <cron-failure-link>` or
  `Replaces #<cron-PR>` line pointing at the failed cron run on the
  [Actions tab](https://github.com/nathanramoscfa/roadmodel/actions/workflows/update-models.yml)
  or at the abandoned cron PR.
- If the failure exposed a parser / prompt regression, file a follow-up
  issue with the failure log attached so the next cron run can succeed
  without manual intervention. The cron is the primary refresh path;
  manual runs should remain exceptional.

## How new models reach every access list

A model retires its predecessor only when it is offered on every access
method that offers the predecessor (`update/supersede.py`), so each method's
`supports-models` list has to keep up with launches. The daily catalog cron
keeps them current in three ways:

- **Synced from the surface's own list, in code.** After the curation pass,
  `update/merge_catalog.py --sync-method` adds every catalogued model a
  surface publishes: Codex's models page (`update/extract_codex_models.py`)
  for `codex-cli` and `codex-api`; OpenRouter's public model list
  (`update/extract_openrouter_models.py`, matched by normalized name, with
  the exceptions in `update/openrouter-model-map.json`) for `openrouter`;
  each provider's own price list for its `<provider>-api` method. Additive
  and fail-open. `ollama` is the one hand-maintained list (a local model
  needs a licence check).
- **Searched by the curation pass.** Every other method's list is refreshed
  from its official source, under the sanity guards in `update/prompt.md`.
- **Near-misses, checked one by one.** `update/supersede.py` prints
  `NEAR-MISS <old> -> <new>: missing on <methods>` for a same-maker model
  that passes every supersession test but coverage. The curation pass gets
  those (method, model) pairs as `<near_miss_checks>` and searches each
  method's source for exactly that model. A pair that is a near-miss on main
  today and three days ago opens one issue,
  `chore(catalog): near-miss supersession "<old>" -> "<new>"`, which
  `update/close_resolved_issues.py` (daily, in `cron-health.yml`) closes once
  the pair resolves.

A dispatch of the cron on a day it already ran refreshes that day's open
catalog PR in place; the PR still awaits human review.
