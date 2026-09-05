# Plan: Cut GitHub Actions cost by moving macOS verification to the Mac Studio

## Diagnosis (confirmed)
- Real out-of-pocket = **billable**, not gross. YTD billable **$254.80**; June **$34.68**. Gross ($307/mo) is ~90% erased by the public-repo Linux discount.
- roadmodel is **public** → Linux minutes free; **macOS minutes are the paid residual**.
- Paid macOS comes from exactly two files: `phase-verify.yml` (10 macOS jobs × every push+PR) and `verify-pypi.yml` (3 macOS jobs × every release).
- Private repos (reversi et al.) burn the 3,000 included Linux min/mo; overage is billable — separate, smaller bucket.
- All roadmodel crons + `tests.yml` are Linux = already $0. **Do not move these** (free already; local = fragile).

## Target
Drop roadmodel billable Actions to ~$0 by removing macOS from CI, while preserving macOS coverage by running it on the Mac Studio for free.

---

## Tier 1 — Kill the macOS matrix legs (this is ~all the savings)
Highest leverage, lowest risk. Linux legs stay in CI (free) as the PR gate.

- **`phase-verify.yml`**: change matrix `os: [ubuntu-latest, macos-latest]` → `os: [ubuntu-latest]`. Removes 10 macOS jobs/run.
- **`verify-pypi.yml`**: change matrix `os: [ubuntu-latest, macos-latest]` → `os: [ubuntu-latest]`. Removes 3 macOS jobs/release.
- Net CI change: Linux still gates every PR exactly as before; only the paid OS leg goes away.

## Tier 2 — Recover macOS coverage locally  [DECIDED: Option A]
The macOS legs did have *some* value (catch mac-only path/install breakage). Replace, don't just delete.

**Option A — Local verify hook/target (CHOSEN)**
- Add a `make verify-macos` (or reuse `scripts/verify-phase*.sh` + `verify-pypi` install smoke) that runs the same scripts natively on the Mac Studio.
- Wire an **optional** `pre-push` step (extend existing `.githooks/pre-commit` pattern → add `pre-push`) that runs the fast macOS verify before pushing to a PR branch. Bypassable with an env flag (mirror `ROADMODEL_ALLOW_MAIN_COMMIT` convention) for quick iterations.
- Cost: $0. Trade-off: coverage runs on your machine on demand, not automatically on every PR (fine for a solo/dogfood repo).

_(Option B self-hosted runner rejected — public-repo security footgun.)_

## Tier 3 — Reduce redundant runs (secondary; trims private-repo overage + churn)
- `phase-verify` fires on **both** `push: [main]` and `pull_request: [main]`. For a PR that merges, that's PR-per-commit runs + a push run on merge = double. Consider dropping the `push:` trigger (PR gate already covers it) or adding `paths-ignore` for docs-only changes.
- `tests.yml` + `phase-verify.yml` overlap heavily — evaluate whether both need to run on every event.
- These are Linux/free on roadmodel, so this is about churn + private-repo allowance, not roadmodel dollars.

## Tier 4 — Private repos (optional, separate ticket)
- reversi/pyfinlab overage draws the 3,000/mo Linux allowance. If those matter, apply the same trims (path filters, concurrency, drop redundant triggers). Out of scope for "roadmodel cost."

---

## Verification / acceptance
1. After Tier 1: next push shows **0 macOS jobs** in Phase verify (check `gh run view`).
2. Confirm `roadmodel` gross in the billing UI trends to near-fully-discounted (billable → ~$0).
3. Local `make verify-macos` passes on the Mac Studio (proves coverage didn't just vanish).
4. Note: I could not pull the exact OS-split billing via API (`user` scope missing). Optional step 0: export the CSV from the billing UI to confirm the macOS share precisely before/after.

## Rollout order
Tier 1 (one small PR, both files) → verify billing drops → Tier 2 coverage → Tier 3 if churn still bothers you.
