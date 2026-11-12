#!/usr/bin/env bash
# Open or refresh the draft PR that holds what a refresh may not merge itself.
#
#   scripts/open-review-pr.sh <branch> <title> <hold-dir> <path>...
#
# update/split_identity.py copies the full candidate into <hold-dir> and writes
# update/.last-held.md when the typed refresh boundary refuses part of it (a new
# model, an access-list entry, a decline line, a provider snapshot, a new AA row).
# This commits that candidate on top of the current HEAD (today's typed refresh,
# or main when there was none), so the PR diff is only what waits for a person,
# and force-pushes it to one rolling branch: each run's candidate replaces the
# last. The PR stays a draft. The refresh merger never takes it, and the
# refresh-integrity status fails on it by design: a maintainer admits it from a
# branch of their own (the PR body says how).
#
# An empty update/.last-held.md means this run's candidate passed the gate
# whole, so whatever an earlier run held has been superseded: the open draft is
# closed rather than left asking for a review of stale data. No report at all
# means the split did not run, and the draft stays.
set -euo pipefail

branch="$1" title="$2" hold="$3"
shift 3
if [ ! -s update/.last-held.md ]; then
  echo "Nothing held for review."
  if [ -e update/.last-held.md ]; then
    stale="$(gh pr list --head "$branch" --state open --json url -q '.[0].url' || true)"
    if [ -n "$stale" ]; then
      gh pr close "$stale" --delete-branch --comment "Superseded: the latest refresh passed the typed boundary whole, so nothing held here still waits for review. A later run that holds something opens a new draft."
      echo "Closed: $stale"
    fi
  fi
  exit 0
fi
git config user.name "roadmodel-bot"
git config user.email "roadmodel-bot@users.noreply.github.com"
git checkout -B "$branch" HEAD
for path in "$@"; do
  cp "$hold/$path" "$path"
done
git add -- "$@"
if git diff --cached --quiet; then
  echo "The held candidate adds nothing to the typed refresh."
  exit 0
fi
DATE="$(date -u +%Y-%m-%d)"
held="$(cat update/.last-held.md)"
git commit -m "${title}: ${DATE}" -m "$held"
git push --force -u origin "$branch"
# Literal Markdown; shell expansion is not intended.
# shellcheck disable=SC2016
body="$(printf '%s\n\n---\n\nOpened by the daily refresh (`scripts/open-review-pr.sh`). The automated lane merges only typed edits to the catalog data (`update/automation_integrity.py`); `update/split_identity.py` shipped those in the refresh PR and held the rest here. This branch is rebuilt from each run that changes, so it always carries the latest candidate.\n\nTo admit it: review the diff; branch from it (`git checkout -b <name> origin/%s`); tag the data commit so it stays reachable and point `context_policy.baseline_revision` in `.github/security-allowances.json` at it; re-bind the allowances; open that branch as your own PR and close this one.' "$held" "$branch")"
PR_URL="$(gh pr list --head "$branch" --state open --json url -q '.[0].url' || true)"
if [ -n "$PR_URL" ]; then
  gh pr edit "$PR_URL" --title "$title" --body "$body"
  echo "Refreshed: $PR_URL"
else
  PR_URL="$(gh pr create --draft --base main --head "$branch" --title "$title" --body "$body")"
  echo "Opened: $PR_URL"
fi
