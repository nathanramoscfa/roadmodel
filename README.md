# model-selector

Reference docs and automation that drive a Claude-Code-friendly model
recommendation workflow. The two source-of-truth documents live under
[docs/](docs/):

- [docs/model-selector.txt](docs/model-selector.txt) — selection criteria,
  per-model pricing, tier ratings, and headline benchmark numbers. Referenced
  from other projects via `@model-selector.txt`.
- [docs/model-tier-cost-scale.md](docs/model-tier-cost-scale.md) — the
  output-price-tier classification reference.

`~/Documents/model-selector.txt` and `~/Documents/model-tier-cost-scale.md`
symlink here so existing references keep working.

## Automation

A weekly GitHub Actions cron triggers an Opus 4.7 agent that:

1. Fetches the current Cursor pricing page
   ([cursor.com/docs/models-and-pricing](https://cursor.com/docs/models-and-pricing)).
2. Fetches headline benchmark leaderboards (see
   [update/sources.json](update/sources.json)).
3. Reconciles changes against both docs.
4. Commits any updates directly to `main`.

The schedule is `0 16 * * 1` (Mondays 16:00 UTC). See
[.github/workflows/update-models.yml](.github/workflows/update-models.yml).

## Environment (conda)

This repo uses a dedicated conda env named `model-selector`. Workspace settings
under [.vscode/settings.json](.vscode/settings.json) point Cursor at that
interpreter and turn on **Python › Terminal: Activate Environment**, so new
integrated terminals opened from the project root should auto-activate the env
after the Python extension loads.

Create or refresh the env once:

```sh
conda create -n model-selector python=3.12 -y
conda activate model-selector
pip install -r update/requirements.txt
```

## Running locally

After the env exists and dependencies are installed (see above), load API keys
from the environment. A root-level `.env` is gitignored and may define
`ANTHROPIC_API_KEY`; export it before running if you do not use a loader:

```sh
cd update
conda activate model-selector
set -a
[ -f ../.env ] && . ../.env
set +a
python update_models.py
```

The script writes back into `docs/`. Inspect the diff with `git diff docs/`.

## CLI tooling

- **GitHub CLI (`gh`)**: install with `brew install gh`, then `gh auth login`.
  Used for repo secrets and manually triggering workflows.

- **Claude Code**: install per [Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/setup)
  (this machine may already have the `claude` CLI). API access uses
  `ANTHROPIC_API_KEY` (see local `.env`, gitignored).

## Setup checklist

- [x] Set the `ANTHROPIC_API_KEY` repo secret:
      `gh secret set ANTHROPIC_API_KEY --repo nathanramoscfa/model-selector`
      (pipe or `--body` the value; do not commit it).
- [x] Trigger the workflow manually once to verify:
      `gh workflow run update-models.yml --repo nathanramoscfa/model-selector`
