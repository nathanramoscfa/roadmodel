# Catalog Refresh — Manual Fallback Procedure

The Monday catalog-refresh cron in
[`.github/workflows/update-models.yml`](../.github/workflows/update-models.yml)
opens a PR that refreshes [`docs/model-selector.txt`](model-selector.txt),
[`docs/model-tier-cost-scale.md`](model-tier-cost-scale.md), the rendered
[`docs/model-selector.md`](model-selector.md), and the machine-readable
[`docs/catalog.json`](catalog.json) in a single commit. This document covers
the manual fallback when the cron fails or when a correction is needed
between Mondays.

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
