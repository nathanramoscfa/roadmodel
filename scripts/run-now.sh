#!/bin/bash
# scripts/run-now.sh — run a scheduled job on demand, wait for it, report back.
#
#   scripts/run-now.sh <target> [--dry-run] [--merge]
#
# Targets (each is a GitHub Actions workflow, dispatched on main):
#   catalog       update-models.yml       prices, models, tiers (Opus + web search)
#   claude-code   update-claude-code.yml  Claude Code effort/thinking surface
#   codex         update-codex.yml        Codex reasoning levels
#   gemini        update-gemini.yml       Gemini thinking levels
#   deepseek      update-deepseek.yml     DeepSeek thinking modes
#   benchmarks    update-benchmarks.yml   Artificial Analysis numbers + derived ratings
#   availability  probe-availability.yml  which models answer (1-token probes)
#   soak          recommend-soak.yml      production recommender smoke
#   health        cron-health.yml         the cron alarm itself
#   crons         catalog → claude-code → codex → gemini → deepseek → benchmarks → availability,
#                 one after another in the daily schedule's order
#   release [X.Y.Z]   → scripts/release.sh (PyPI release + service rollout)
#
#   --dry-run   workflows that support it preview only (no PR, no promotion)
#   --merge     squash-merge each PR a run opens once its checks pass (rebasing
#               when main moved). With `crons`, each PR merges before the next
#               job starts, so every job builds on the previous one's output.
#
# Needs `gh` authenticated with repo + workflow scope. The catalog, Claude Code,
# Codex, Gemini and DeepSeek jobs call the Anthropic API (~$0.30-2 per run —
# see the `API cost` line); the rest are free.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/ops-lib.sh
. "$HERE/ops-lib.sh"

usage() { sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

target="${1:-}"
[ -z "$target" ] && usage 1
case "$target" in -h | --help) usage 0 ;; esac
shift
if [ "$target" = "release" ]; then
  exec "$HERE/release.sh" "$@"
fi

dry_run=0
merge=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --merge) merge=1 ;;
    -h | --help) usage 0 ;;
    *) die "unknown option: $arg" ;;
  esac
done

workflow_for() {
  case "$1" in
    catalog) echo update-models.yml ;;
    claude-code) echo update-claude-code.yml ;;
    codex) echo update-codex.yml ;;
    gemini) echo update-gemini.yml ;;
    deepseek) echo update-deepseek.yml ;;
    benchmarks) echo update-benchmarks.yml ;;
    availability) echo probe-availability.yml ;;
    soak) echo recommend-soak.yml ;;
    health) echo cron-health.yml ;;
    *) return 1 ;;
  esac
}

failures=""
run_one() {
  local name="$1" wf run_id rc pr
  wf="$(workflow_for "$name")" || die "unknown target: $name (see --help)"
  set --
  if [ "$dry_run" = 1 ]; then
    if grep -q 'dry_run:' "$HERE/../.github/workflows/$wf" 2>/dev/null ||
      gh workflow view "$wf" -R "$REPO" --yaml 2>/dev/null | grep -q 'dry_run:'; then
      set -- -f dry_run=true
    else
      log "$name has no dry-run mode — skipping it in --dry-run"
      return 0
    fi
  fi
  log "== $name ($wf)$([ "$dry_run" = 1 ] && echo ' [dry run]')"
  run_id="$(dispatch_and_wait "$wf" "$@")"
  rc=$?
  run_summary "$run_id"
  if [ "$rc" -ne 0 ]; then
    failures="$failures $name"
    return 0
  fi
  if [ "$merge" = 1 ] && [ "$dry_run" = 0 ]; then
    for pr in $(prs_from_run "$run_id"); do
      log "merging PR #$pr when green"
      ( merge_when_green "$pr" ) || failures="$failures $name(PR#$pr)"
    done
  fi
}

if [ "$target" = "crons" ]; then
  for name in catalog claude-code codex gemini deepseek benchmarks availability; do
    run_one "$name"
  done
else
  run_one "$target"
fi

if [ -n "$failures" ]; then
  log "FAILED:$failures"
  exit 1
fi
log "done"
