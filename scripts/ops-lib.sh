# scripts/ops-lib.sh — shared helpers for run-now.sh and release.sh.
#
# Sourced, never executed. Plain bash 3.2 (macOS /bin/bash) — no mapfile, no
# associative arrays — so the same helpers run on the Mac and in Actions.

REPO="${ROADMODEL_REPO:-nathanramoscfa/roadmodel}"
HEALTHZ_URL="${ROADMODEL_HEALTHZ_URL:-https://roadmodel-api.vercel.app/healthz}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# dispatch_and_wait <workflow.yml> [-f key=value ...]
# Dispatches the workflow on main, finds THAT run (not an older one), watches it
# to completion and prints its run id on stdout. Returns the run's exit status.
dispatch_and_wait() {
  local wf="$1"
  shift
  local before run_id tries=0
  before="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  gh workflow run "$wf" -R "$REPO" --ref main "$@" >/dev/null ||
    die "could not dispatch $wf"
  while :; do
    run_id="$(gh run list -R "$REPO" -w "$wf" -e workflow_dispatch -L 5 \
      --json databaseId,createdAt \
      -q "[.[] | select(.createdAt >= \"$before\")] | last | .databaseId // empty")"
    [ -n "$run_id" ] && break
    tries=$((tries + 1))
    [ "$tries" -gt 40 ] && die "$wf was dispatched but no run appeared after 2 minutes"
    sleep 3
  done
  log "$wf -> https://github.com/$REPO/actions/runs/$run_id"
  gh run watch "$run_id" -R "$REPO" --exit-status --interval 15 >/dev/null 2>&1
  local rc=$?
  echo "$run_id"
  return $rc
}

# run_summary <run_id> — conclusion, per-turn API cost lines and any PR it opened.
run_summary() {
  local run_id="$1" logf
  logf="$(mktemp)"
  gh run view "$run_id" -R "$REPO" --log >"$logf" 2>/dev/null || true
  gh run view "$run_id" -R "$REPO" --json workflowName,conclusion \
    -q '"  result: \(.workflowName) — \(.conclusion)"'
  grep -oE 'est_usd=[0-9.]+' "$logf" | awk -F= '{s+=$2; n++} END {if (n) printf "  API cost: $%.2f over %d Opus turn(s)\n", s, n}'
  grep -oE "https://github.com/$REPO/pull/[0-9]+" "$logf" | sort -u | sed 's/^/  PR: /'
  if grep -q 'usage limits' "$logf"; then
    echo "  !! Anthropic API spend limit reached — raise it in the Console (Settings → Limits)"
  fi
  rm -f "$logf"
}

# prs_from_run <run_id> — PR numbers a run opened, one per line.
prs_from_run() {
  gh run view "$1" -R "$REPO" --log 2>/dev/null |
    grep -oE "https://github.com/$REPO/pull/[0-9]+" | sort -u | grep -oE '[0-9]+$'
}

# merge_when_green <pr> — wait for checks, rebase when BEHIND, squash-merge.
# MERGE_GH_TOKEN (optional) is used for the merge itself: in Actions it is the
# cron App's token, so the merge commit still triggers push workflows.
merge_when_green() {
  local pr="$1" state merge_state failing i
  for i in $(seq 1 120); do
    state="$(gh pr view "$pr" -R "$REPO" --json state -q .state)"
    [ "$state" = "MERGED" ] && { log "PR #$pr merged"; return 0; }
    [ "$state" = "CLOSED" ] && { log "PR #$pr was closed (superseded?) — skipping"; return 0; }
    failing="$(gh pr view "$pr" -R "$REPO" --json statusCheckRollup \
      -q '[.statusCheckRollup[] | select((.conclusion // .state) as $c | $c == "FAILURE" or $c == "ERROR" or $c == "CANCELLED" or $c == "TIMED_OUT")] | map(.name // .context) | join(", ")')"
    [ -n "$failing" ] && die "PR #$pr has failing checks: $failing — https://github.com/$REPO/pull/$pr"
    merge_state="$(gh pr view "$pr" -R "$REPO" --json mergeStateStatus -q .mergeStateStatus)"
    case "$merge_state" in
      BEHIND)
        log "PR #$pr is behind main — rebasing"
        _gh_as_merger pr update-branch "$pr" -R "$REPO" --rebase || true ;;
      CLEAN | HAS_HOOKS | UNSTABLE)
        _gh_merge "$pr" --squash --delete-branch || _gh_merge "$pr" --squash || true ;;
    esac
    sleep 20
  done
  die "PR #$pr did not merge within 40 minutes — https://github.com/$REPO/pull/$pr"
}

# gh as the merger: MERGE_GH_TOKEN when set (the cron App in Actions, so the
# resulting commits still trigger workflows), else the caller's own auth.
_gh_as_merger() {
  if [ -n "${MERGE_GH_TOKEN:-}" ]; then
    GH_TOKEN="$MERGE_GH_TOKEN" gh "$@" >/dev/null 2>&1
  else
    gh "$@" >/dev/null 2>&1
  fi
}

_gh_merge() {
  local pr="$1"
  shift
  _gh_as_merger pr merge "$pr" -R "$REPO" "$@"
}

# quiet_push <git push args...> — the pre-push hook prints the whole macOS
# verify suite; show it only when the push fails.
quiet_push() {
  local out
  out="$(git push "$@" 2>&1)" || { printf '%s\n' "$out" | tail -25 >&2; return 1; }
}

# pypi_index_has <version> — true once PyPI's SIMPLE index (what pip and uv
# resolve against) lists the version. The JSON API sees a release minutes
# before the CDN-cached index does; a build that resolves in that window fails
# with "only roadmodel<=OLD is available" (0.2.43's first service build). The
# CDN caches one copy per Accept header, so this asks with uv's own.
pypi_index_has() {
  curl -s --max-time 15 \
    -H "Accept: application/vnd.pypi.simple.v1+json, application/vnd.pypi.simple.v1+html;q=0.2, text/html;q=0.01" \
    https://pypi.org/simple/roadmodel/ |
    python3 -c 'import json,sys; sys.exit(0 if sys.argv[1] in json.load(sys.stdin).get("versions",[]) else 1)' "$1" \
    2>/dev/null
}

# pypi_upload_epoch <version> — Unix time of the version's first upload.
pypi_upload_epoch() {
  curl -s --max-time 15 "https://pypi.org/pypi/roadmodel/$1/json" |
    python3 -c 'import json,sys
from datetime import datetime
u = json.load(sys.stdin)["urls"]
print(int(min(datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")).timestamp() for f in u)))' \
    2>/dev/null
}

healthz_version() {
  curl -s --max-time 15 "$HEALTHZ_URL" |
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("roadmodel_version",""))' 2>/dev/null
}
