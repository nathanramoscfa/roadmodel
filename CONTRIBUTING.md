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
