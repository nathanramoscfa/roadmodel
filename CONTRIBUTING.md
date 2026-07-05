# Contributing to roadmodel

Thank you for helping improve roadmodel. This document describes how we
review changes and how to propose edits to the bundled recommender catalog.

## Branch naming

Use short-lived branches (about one week or less) that merge to `main` via
pull request. Prefix branches by intent:

| Prefix     | Purpose                     | Example                          |
| ---------- | --------------------------- | -------------------------------- |
| `feature/` | Phase work or new feature   | `feature/phase-3-recommender`    |
| `fix/`     | Non-urgent bug fix          | `fix/cost-comparison-rounding`   |
| `hotfix/`  | Urgent production fix       | `hotfix/stripe-webhook-500`      |
| `chore/`   | Tooling, deps, housekeeping | `chore/upgrade-next-15`          |
| `docs/`    | Documentation-only changes  | `docs/byo-key-setup`             |
| `perf/`    | Performance work            | `perf/catalog-load-time`         |
| `release/` | Pre-release stabilisation   | `release/v1.0.0`                 |

`main` must stay green on CI and deployable. Do not force-push to `main`.

## Local hooks (one-time setup)

After cloning, point Git at the in-repo hooks directory so the
`pre-commit` branch guard runs:

```sh
git config core.hooksPath .githooks
```

The hook refuses commits directly on `main` (or `master`) and points
you at the recovery steps. This complements GitHub's server-side
branch protection (`enforce_admins: true`) by catching the mistake at
commit time, before work strands on the wrong branch. The setting is
per-clone, so re-run it after a fresh `git clone`. AI coding agents
operating in this repo MUST set `core.hooksPath` before their first
commit.

Emergency bypass (reserved for incident recovery):
`ROADMODEL_ALLOW_MAIN_COMMIT=1 git commit ...`.

The same `core.hooksPath` setting also enables a **`pre-push`** hook that
runs native macOS verification (`scripts/verify-macos.sh --fast`) before a
push. CI runs the phase-verify matrix on Linux only — Linux Actions minutes
are free on this public repo, whereas macOS runners are not — so this hook
is where macOS-specific breakage gets caught, on Apple hardware, for free.

Bypass once: `git push --no-verify` (or `ROADMODEL_SKIP_PREPUSH_VERIFY=1
git push`). Disable for a clone: `git config roadmodel.prepushverify
false`. Narrow scope: `git config roadmodel.prepushphases "01 03"`. Point
`ROADMODEL_VERIFY_PYTHON` at a 3.11+ interpreter if your default `python3`
is older.

## Pull request scope

Keep each pull request scoped to **one phase sub-section** (one numbered
step or subsection from the active phase roadmap). If work spans multiple
steps, split it into separate PRs so each review stays focused.

When you open a PR, use the repository templates so reviewers get a
consistent checklist:

- **Issues:** choose **Bug report** or **Feature request** from
  [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/) when filing linked
  issues.
- **Pull requests:** follow
  [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).

## Commits and merge strategy

We **squash-merge** to `main`. Write the **squash commit message** in
[Conventional Commits](https://www.conventionalcommits.org/) form (for
example `feat:`, `fix:`, `docs:`, `chore:`) so history stays readable.

## Proposing a catalog edit

The live recommender rules and model rows live in
[`docs/model-selector.txt`](docs/model-selector.txt). To change benchmarks,
tiers, pricing notes, or selection copy:

1. Open a pull request that updates `docs/model-selector.txt` (not the
   generated `docs/model-selector.md`; CI enforces sync).
2. In the PR description, include a short **rationale** for the change.
3. Include the **upstream source URL** (pricing page, leaderboard, provider
   doc, or other primary reference) for every material number or claim you
   touch.

Maintainers may ask for additional sources or to split editorial changes from
data-only updates.

## Security

Do not open a public issue for undisclosed security problems. Follow
[`SECURITY.md`](SECURITY.md) and email **nathan.ramos.github@gmail.com**
instead.

## License

By contributing, you agree your contributions are licensed under the same
terms as the project — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
