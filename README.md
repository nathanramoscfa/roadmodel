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

## Running locally

```sh
cd update
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-... python update_models.py
```

The script writes back into `docs/`. Inspect the diff with `git diff docs/`.

## Setup checklist

- [ ] Set the `ANTHROPIC_API_KEY` repo secret:
      `gh secret set ANTHROPIC_API_KEY --repo <owner>/model-selector`
- [ ] Trigger the workflow manually once to verify:
      `gh workflow run update-models.yml --repo <owner>/model-selector`
