---
description: Run a roadmodel job on demand — curation crons, benchmarks, availability, soak, or a full release (usage: /run-now <target> [--dry-run] [--merge] | /run-now release [X.Y.Z])
---

Run a scheduled roadmodel job now, from the repo root, and report the result.

Arguments: `$ARGUMENTS`

- For a job target (`crons`, `catalog`, `benchmarks`, `claude-code`, `codex`,
  `gemini`, `deepseek`, `availability`, `soak`, `health`): run
  `scripts/run-now.sh $ARGUMENTS` in the background and wait for it. Add
  `--merge` unless the user said preview/dry run — a green curation PR is merged
  without asking. If a PR it opened fails checks, open it, find the cause (the
  failing test names the model or file), fix it on that PR's branch, push, and
  merge once green; a data bug in a generated file is fixed at its source
  (`docs/model-selector.txt` / the cost scale) and the derived files
  regenerated (`update/render_md.py`, `update/build_catalog.py`).
- For `release [X.Y.Z]`: first make sure CHANGELOG.md's `[Unreleased]` section
  describes every user-visible change merged since the last `v*` tag (`git log
  <last-tag>..origin/main`), in the file's existing voice; add missing entries as
  an uncommitted edit (the script carries it onto the release branch). Then run
  `scripts/release.sh X.Y.Z` (omit the version for the next patch). It is
  resumable — on a failure, fix the cause and run it again.
- Report: what ran, its result, the API cost line, the PR(s) and whether they
  merged; for a release, the PyPI version and what production `/healthz` reports.
- An Anthropic "usage limits" error means the org spend limit is hit — say so;
  it is raised in the Console (Settings → Limits), not in this repo.
