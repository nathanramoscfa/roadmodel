#!/usr/bin/env bash
# scripts/drill-funding-invariant.sh  (Phase 4.11 Step 6 fire drill)
#
# Proves the funding-invariant alarm fires, and clears:
#   1. insert ONE synthetic violating operator row (route /__invariant-drill,
#      reason "drill", no user) into production audit_log;
#   2. dispatch cron-health.yml on the step branch, expect the run to FAIL and
#      the tracking issue to open or update;
#   3. delete the row, dispatch again, expect the run to go GREEN and the
#      issue to close.
# The row is deleted in a trap even if a step fails. Prints run URLs and
# conclusions only; the service-role key is read from the keychain by
# scripts/with-prod-secrets.sh and never echoed.
#
#   scripts/with-prod-secrets.sh scripts/drill-funding-invariant.sh [branch]
set -euo pipefail

BRANCH="${1:-feature/phase04.11-step6-verify}"
WF=cron-health.yml
TITLE="chore(cron): automated refresh pipeline is unhealthy"
: "${SUPABASE_URL:?run under scripts/with-prod-secrets.sh}"
: "${SUPABASE_SERVICE_ROLE_KEY:?run under scripts/with-prod-secrets.sh}"

ROW_ID=""
rest() { # rest <method> <path> [json-body]
  curl -fsS -X "$1" "${SUPABASE_URL}/rest/v1/$2" \
    -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Content-Type: application/json" -H "Prefer: return=representation" \
    ${3:+-d "$3"}
}
cleanup() {
  if [[ -n "${ROW_ID}" ]]; then
    rest DELETE "audit_log?id=eq.${ROW_ID}" >/dev/null && echo "drill row ${ROW_ID} deleted" || echo "!! could not delete drill row ${ROW_ID}" >&2
    ROW_ID=""
  fi
}
trap cleanup EXIT

run_workflow() { # prints "<id> <conclusion> <url>" for a fresh dispatch
  local before id
  before="$(gh run list --workflow "${WF}" --limit 1 --json databaseId -q '.[0].databaseId // 0')"
  gh workflow run "${WF}" --ref "${BRANCH}" >/dev/null
  for _ in $(seq 1 30); do
    sleep 5
    id="$(gh run list --workflow "${WF}" --branch "${BRANCH}" --event workflow_dispatch --limit 1 --json databaseId -q '.[0].databaseId // 0')"
    [[ "${id}" -gt "${before}" ]] && break
  done
  gh run watch "${id}" >/dev/null 2>&1 || true
  gh run view "${id}" --json conclusion,url -q '"\(.conclusion) \(.url)"' | sed "s/^/${id} /"
}

issue_number() {
  gh issue list --state open --limit 200 --json number,title \
    -q "map(select(.title == \"${TITLE}\")) | .[0].number // empty"
}

echo "== 1. insert the synthetic violating row"
ROW_ID="$(rest POST audit_log '{"ip_hash":"invariant-drill","ua_hash":"invariant-drill","route":"/__invariant-drill","outcome":"ok","funded_by":"operator","cost_usd":0,"cache_stats":{"funding_reason":"drill"}}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
echo "inserted drill row id=${ROW_ID}"

echo "== 2. dispatch with the row present (expect failure + issue)"
read -r id1 conclusion1 url1 < <(run_workflow)
echo "run ${id1}: ${conclusion1}  ${url1}"
echo "tracking issue open: #$(issue_number)"

echo "== 3. delete the row, dispatch again (expect success + issue closed)"
cleanup
read -r id2 conclusion2 url2 < <(run_workflow)
echo "run ${id2}: ${conclusion2}  ${url2}"
echo "tracking issue open after recovery: #$(issue_number)"

[[ "${conclusion1}" == "failure" && "${conclusion2}" == "success" ]] && echo "DRILL PASSED" || { echo "DRILL FAILED"; exit 1; }
