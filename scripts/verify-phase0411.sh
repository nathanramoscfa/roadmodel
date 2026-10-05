#!/usr/bin/env bash
# scripts/verify-phase0411.sh
#
# Phase 4.11 (visitor-funded recommendations) deliverable verification. Mirrors
# scripts/verify-phase046.sh (record_pass / record_fail, summary table, --fast
# for CI) so CI logs across phases stay diff-friendly. Covers Steps 1-6: the
# fail-closed funding lanes + invite list + funded_by ledger, visitor keys,
# OpenRouter connect, the keyless scoring endpoint + agreement eval, the keyless
# lane on /recommend, and this step's verify script + alarm + docs.
#
# Usage:
#   ./scripts/verify-phase0411.sh             # static + service pytest
#   ./scripts/verify-phase0411.sh --fast      # static checks only (CI; Ubuntu-safe, <30s)
#   ./scripts/verify-phase0411.sh --web       # static + typecheck + Playwright specs
#   ./scripts/verify-phase0411.sh --service   # static + service/package pytest
#   ./scripts/verify-phase0411.sh --security  # secret scan + SAST + dep audit + literal grep
#   ./scripts/verify-phase0411.sh --all       # static + web + service + security
#   ./scripts/verify-phase0411.sh --post      # static + V-checks + live lane probe (Mac)
#
# --post needs the maintainer's keychain secrets (scripts/with-prod-secrets.sh);
# CI runs --fast and --security. The funding-invariant alarm (V6.6) runs daily in
# cron-health.yml, not here.
#
# Discipline: this script always names the selector by its qualified path
# (docs/model-selector.txt) so verify-phase01.sh's rename-sweep stays green.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-phase0411.sh: not inside a git checkout" >&2
  exit 1
fi
cd "${ROOT}"

resolve_python_bin() {
  if [[ -n "${ROADMODEL_VERIFY_PYTHON:-}" ]]; then
    printf '%s\n' "${ROADMODEL_VERIFY_PYTHON}"
    return 0
  fi
  if [[ -x "${ROOT}/.venv/bin/python" ]]; then
    printf '%s\n' "${ROOT}/.venv/bin/python"
    return 0
  fi
  if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; return 0; fi
  if command -v python3.11 >/dev/null 2>&1; then command -v python3.11; return 0; fi
  command -v python3
}

PYTHON_BIN="$(resolve_python_bin)"

MODE_DEFAULT=0
MODE_FAST=0
MODE_WEB=0
MODE_SERVICE=0
MODE_SECURITY=0
MODE_ALL=0
MODE_POST=0

if [[ $# -eq 0 ]]; then
  MODE_DEFAULT=1
else
  case "$1" in
    --fast) MODE_FAST=1 ;;
    --web) MODE_WEB=1 ;;
    --service) MODE_SERVICE=1 ;;
    --security) MODE_SECURITY=1 ;;
    --all) MODE_ALL=1 ;;
    --post) MODE_POST=1 ;;
    -h | --help)
      sed -n '2,23p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
fi

if [[ "${MODE_ALL}" -eq 1 ]]; then
  MODE_WEB=1
  MODE_SERVICE=1
  MODE_SECURITY=1
fi
if [[ "${MODE_DEFAULT}" -eq 1 ]]; then
  MODE_SERVICE=1
fi

declare -i STATIC_PASS=0 STATIC_FAIL=0
declare -i WEB_PASS=0 WEB_FAIL=0
declare -i SERVICE_PASS=0 SERVICE_FAIL=0
declare -i SECURITY_PASS=0 SECURITY_FAIL=0
declare -i V_PASS=0 V_FAIL=0
declare -i POST_PASS=0 POST_FAIL=0
FAILED_CHECKS=()
# CHECK_OK[n]=1 once static check n passed (or was skipped on purpose).
CHECK_OK=()

record_pass() {
  STATIC_PASS+=1
  CHECK_OK[$1]=1
  printf '[PASS] Check %s: %s\n' "$1" "$2"
}

record_fail() {
  STATIC_FAIL+=1
  CHECK_OK[$1]=0
  FAILED_CHECKS+=("$1")
  printf '[FAIL] Check %s: %s — %s\n' "$1" "$2" "$3" >&2
}

record_skip() {
  CHECK_OK[$1]=1
  printf '[SKIP] Check %s: %s — %s\n' "$1" "$2" "$3"
}

# file_has <n> <desc> <path> <fixed-string>  — pass iff the file exists and
# contains the fixed string (grep -F, no regex surprises).
file_has() {
  local n="$1" desc="$2" path="$3" needle="$4"
  if [[ -f "${path}" ]] && grep -Fq -- "${needle}" "${path}"; then
    record_pass "${n}" "${desc}"
  else
    record_fail "${n}" "${desc}" "missing file or string in ${path}: ${needle}"
  fi
}

# file_lacks <n> <desc> <path> <extended-regex>  — pass iff the file exists and
# no line OUTSIDE a comment matches. Comment lines are `//`, `#` and `*`-led.
file_lacks() {
  local n="$1" desc="$2" path="$3" pattern="$4"
  if [[ ! -f "${path}" ]]; then
    record_fail "${n}" "${desc}" "missing ${path}"
    return
  fi
  if grep -Ev '^[[:space:]]*(//|#|\*|/\*)' "${path}" | grep -Eq -- "${pattern}"; then
    record_fail "${n}" "${desc}" "found /${pattern}/ in ${path}"
  else
    record_pass "${n}" "${desc}"
  fi
}

# files_exist <n> <desc> <path>...
files_exist() {
  local n="$1" desc="$2"
  shift 2
  local missing=() f
  for f in "$@"; do
    [[ -f "${f}" ]] || missing+=("${f}")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    record_pass "${n}" "${desc}"
  else
    record_fail "${n}" "${desc}" "missing: ${missing[*]}"
  fi
}

# json_check <n> <desc> <python-expression over `d`> <path>
json_check() {
  local n="$1" desc="$2" expr="$3" path="$4"
  if [[ -f "${path}" ]] && "${PYTHON_BIN}" - "${path}" "${expr}" <<'PY' 2>/dev/null; then
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if eval(sys.argv[2], {"d": d}) else 1)
PY
    record_pass "${n}" "${desc}"
  else
    record_fail "${n}" "${desc}" "${path}: ${expr}"
  fi
}

# The phase's own paths: what the secret scan and the literal grep cover.
phase_paths() {
  cat <<'EOF'
web/lib/funding-lane.ts
web/lib/withFundingLane.ts
web/lib/visitor-key.ts
web/lib/use-visitor-key.ts
web/lib/openrouter-connect.ts
web/lib/keyless.ts
web/lib/keyless-eval.ts
web/lib/service-url.ts
web/lib/spend-guard.ts
web/lib/audit.ts
web/lib/api.ts
web/app/api/recommend
web/app/api/openrouter
web/app/api/roadmap
web/app/api/test/mock-recommend
web/app/privacy
web/app/recommend
web/components/LaneChooser.tsx
web/components/OpenRouterCallback.tsx
web/components/OwnAgentPanel.tsx
web/components/QuickPick.tsx
web/components/VisitorKeyPanel.tsx
web/tests/funding-lane.spec.ts
web/tests/visitor-key.spec.ts
web/tests/visitor-key-ui.spec.ts
web/tests/openrouter-connect.spec.ts
web/tests/keyless-lane.spec.ts
web/tests/keyless-lane-ui.spec.ts
web/tests/fixtures
service/app/visitor.py
service/app/score.py
service/app/engines.json
service/tests/test_visitor_endpoint.py
service/tests/test_score_endpoint.py
service/tests/test_engines.py
tests/test_audit_log_migration.py
tests/test_keyless_eval_shape.py
tests/test_funding_invariant.py
scripts/verify-phase0411.sh
scripts/probe-funding-lanes.ts
scripts/check_funding_invariant.py
scripts/drill-funding-invariant.sh
scripts/eval_keyless_agreement.py
scripts/keyless_probe_labels.json
infra/supabase/migrations/20261002000000_audit_log_funded_by.sql
docs/cost-ceilings.md
docs/byo-key-setup.md
docs/phase0411-qa-findings.md
docs/keyless-eval.json
docs/engine-eval.json
.githooks/pre-commit
.github/workflows/cron-health.yml
.github/workflows/phase-verify.yml
EOF
}

# The secret-shaped literals that must not sit under the phase's paths. The
# SHAPE is matched, not the bare prefix: web/lib/visitor-key.ts and
# service/app/visitor.py name the prefixes themselves, and the tests assemble
# their fake keys from parts at runtime.
SECRET_SHAPES='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_-]{16,}|sk-proj-[A-Za-z0-9_-]{16,}|(^|[^A-Za-z0-9])sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{16,}'

# secret_literal_hits — print `path:line` for every shape match under the phase paths.
secret_literal_hits() {
  local p
  while IFS= read -r p; do
    [[ -e "${p}" ]] || continue
    grep -rEIn --binary-files=without-match -e "${SECRET_SHAPES}" "${p}" 2>/dev/null |
      cut -d: -f1,2 || true
  done < <(phase_paths)
}

run_static_checks() {
  STATIC_PASS=0
  STATIC_FAIL=0
  FAILED_CHECKS=()
  CHECK_OK=()

  # --- Step 1: funding lanes — checks 1-9 ---
  file_has 1 "web/lib/funding-lane.ts exports decideLane" \
    web/lib/funding-lane.ts "export function decideLane"

  if [[ -f web/lib/withFundingLane.ts ]] &&
    grep -Fq withFundingLane web/app/api/recommend/route.ts &&
    grep -Fq withFundingLane web/app/api/roadmap/route.ts; then
    record_pass 2 "withFundingLane.ts exists; /api/recommend and /api/roadmap use it"
  else
    record_fail 2 "withFundingLane.ts exists; both paid routes use it" "missing file or import"
  fi

  file_has 3 "RECOMMEND_INVITED_USER_IDS is in web/lib/env.ts" \
    web/lib/env.ts "RECOMMEND_INVITED_USER_IDS"

  if grep -rqI "recommendOnServer" web --include='*.ts' --include='*.tsx' --exclude-dir=node_modules --exclude-dir=.next 2>/dev/null; then
    record_fail 4 "recommendOnServer is gone from web/" "still referenced"
  else
    record_pass 4 "recommendOnServer is gone from web/"
  fi

  # supabase/migrations/ is a gitignored local symlink, absent on a CI runner.
  if compgen -G "infra/supabase/migrations/*_audit_log_funded_by.sql" >/dev/null; then
    record_pass 5 "the funded_by migration exists in infra/supabase/migrations/"
  else
    record_fail 5 "the funded_by migration exists in infra/supabase/migrations/" "missing"
  fi

  if [[ -f service/app/engines.json ]] && ! grep -Eq '"(signed_in|public)"' service/app/engines.json; then
    record_pass 6 "engines.json carries no signed_in / public menu value"
  else
    record_fail 6 "engines.json carries no signed_in / public menu value" "found or missing"
  fi

  file_has 7 "spend-guard.ts filters on funded_by" \
    web/lib/spend-guard.ts 'funded_by.eq.operator'

  file_has 8 "/api/roadmap checks ROADMAP_ENABLED (answers 404 when off)" \
    web/app/api/roadmap/route.ts "enabled: () => env.ROADMAP_ENABLED"

  files_exist 9 "web/tests/funding-lane.spec.ts exists" web/tests/funding-lane.spec.ts

  # --- Step 2: visitor keys — checks 10-16 ---
  file_has 10 "visitor.py defines /v1/visitor/recommend/ladder" \
    service/app/visitor.py '"/v1/visitor/recommend/ladder"'

  file_lacks 11 "visitor.py never calls load_config or _provider_chain" \
    service/app/visitor.py 'load_config\(|_provider_chain\(|import .*(load_config|_provider_chain)'

  json_check 12 "engines.json has visitor_defaults for openai, google, anthropic" \
    'all(k in d["visitor_defaults"] for k in ("openai", "google", "anthropic"))' \
    service/app/engines.json

  file_has 13 "/healthz capabilities list visitor-key" \
    service/app/main.py '"visitor-key"'

  file_lacks 14 "the key-holder module never writes localStorage / sessionStorage / document.cookie" \
    web/lib/use-visitor-key.ts '(localStorage|sessionStorage)\.(setItem|getItem)|document\.cookie[[:space:]]*='

  files_exist 15 "visitor endpoint pytest and visitor-key Playwright spec exist" \
    service/tests/test_visitor_endpoint.py web/tests/visitor-key.spec.ts

  if [[ -f web/app/privacy/page.tsx ]] && grep -Eiq "own (API )?key|visitor key" web/app/privacy/page.tsx; then
    record_pass 16 "the privacy page mentions the visitor key"
  else
    record_fail 16 "the privacy page mentions the visitor key" "no mention in web/app/privacy/page.tsx"
  fi

  # --- Step 3: OpenRouter — checks 17-19 ---
  files_exist 17 "the OpenRouter exchange route and callback page exist" \
    web/app/api/openrouter/exchange/route.ts web/app/recommend/openrouter/page.tsx

  json_check 18 "engine-eval.json has a passing openrouter record" \
    'any(k.startswith("openrouter") and v["passed"] == v["probes"] and v["probes"] > 0 for k, v in d["engines"].items())' \
    docs/engine-eval.json

  json_check 19 "engines.json visitor_defaults.openrouter is set" \
    'bool(d["visitor_defaults"].get("openrouter"))' \
    service/app/engines.json

  # --- Step 4: keyless scoring — checks 20-23 ---
  file_has 20 "service/app/score.py defines /v1/score" \
    service/app/score.py '"/v1/score"'

  json_check 21 "keyless-eval.json: agree >= 27, total 36, under_tier 0" \
    'd["agree"] >= 27 and d["total"] == 36 and d["under_tier"] == 0' \
    docs/keyless-eval.json

  files_exist 22 "the agreement eval script and its probe labels exist" \
    scripts/eval_keyless_agreement.py scripts/keyless_probe_labels.json

  files_exist 23 "service/tests/test_score_endpoint.py exists" \
    service/tests/test_score_endpoint.py

  # --- Step 5: keyless lane — checks 24-26 ---
  # The route reaches the service only through scoreUrl() (the "/v1/score"
  # literal lives in web/lib/service-url.ts) and names no other /v1/ path.
  local route=web/app/api/recommend/keyless/route.ts other
  if [[ -f "${route}" ]] && grep -Fq "scoreUrl()" "${route}" && grep -Fq '"/v1/score"' web/lib/service-url.ts; then
    other="$(grep -Eo '/v1/[A-Za-z0-9_/-]+' "${route}" | sort -u | grep -Fvx '/v1/score' || true)"
    if [[ -z "${other}" ]]; then
      record_pass 24 "the keyless route reaches the service only through scoreUrl() (/v1/score)"
    else
      record_fail 24 "the keyless route names only /v1/score" "also names: ${other}"
    fi
  else
    record_fail 24 "the keyless route reaches the service only through scoreUrl()" "route or service-url.ts missing the call"
  fi

  file_has 25 "sync-catalog.mjs copies keyless-eval.json" \
    web/scripts/sync-catalog.mjs "keyless-eval.json"

  files_exist 26 "web/tests/keyless-lane.spec.ts exists" web/tests/keyless-lane.spec.ts

  # --- Step 6 self-checks — checks 27-32 ---
  if [[ -x scripts/verify-phase0411.sh ]]; then record_pass 27 "scripts/verify-phase0411.sh exists + executable"
  else record_fail 27 "scripts/verify-phase0411.sh exists + executable" "missing or not executable"; fi

  files_exist 28 "docs/phase0411-qa-findings.md exists" docs/phase0411-qa-findings.md

  if [[ -d private ]]; then
    files_exist 29 "private/phase04.11-visitor-funded-roadmap.md exists" \
      private/phase04.11-visitor-funded-roadmap.md
  else
    record_skip 29 "private/phase04.11-visitor-funded-roadmap.md exists" "private/ is not in this checkout (CI)"
  fi

  if [[ -f .github/workflows/phase-verify.yml ]] &&
    [[ "$(grep -c '"0411"' .github/workflows/phase-verify.yml)" -ge 2 ]]; then
    record_pass 30 "phase-verify.yml matrix includes 0411 (verify and post)"
  else
    record_fail 30 "phase-verify.yml matrix includes 0411 (verify and post)" "needs both matrices"
  fi

  file_has 31 "cron-health.yml runs scripts/check_funding_invariant.py" \
    .github/workflows/cron-health.yml "scripts/check_funding_invariant.py"

  # Security wiring: the pre-commit hook runs the secret scan, the post job
  # installs gitleaks, and no PEM / key-shaped literal sits under the phase.
  local hits
  hits="$(secret_literal_hits)"
  if [[ -x .githooks/pre-commit ]] && grep -Fq gitleaks .githooks/pre-commit &&
    grep -Fq "Install gitleaks" .github/workflows/phase-verify.yml && [[ -z "${hits}" ]]; then
    record_pass 32 "secret scan wired (pre-commit + CI) and no key-shaped literal under the phase's paths"
  else
    record_fail 32 "secret scan wired and no key-shaped literal under the phase's paths" \
      "hook/CI wiring missing, or literal at: $(printf '%s' "${hits}" | tr '\n' ' ')"
  fi
}

# v_group <id> <desc> <first> <last>  — a V-check passes when static checks
# first..last all passed.
v_group() {
  local id="$1" desc="$2" first="$3" last="$4" i bad=""
  for ((i = first; i <= last; i++)); do
    [[ "${CHECK_OK[$i]:-0}" -eq 1 ]] || bad="${bad} ${i}"
  done
  if [[ -z "${bad}" ]]; then
    V_PASS+=1
    printf '[PASS] %s: %s\n' "${id}" "${desc}"
  else
    V_FAIL+=1
    printf '[FAIL] %s: %s — failing static checks:%s\n' "${id}" "${desc}" "${bad}" >&2
  fi
}

run_v_rollup() {
  V_PASS=0
  V_FAIL=0
  printf '\n-- V-checks --\n'
  v_group V1.1 "static checks 1-9 (lane module, wrapper, invite env, migration twins)" 1 9
  v_group V2.1 "static checks 10-16 (visitor endpoint, no load_config, defaults, key holder)" 10 16
  v_group V3.1 "static checks 17-19 (OpenRouter routes, passing eval record, default)" 17 19
  v_group V4.1 "static checks 20-23 (score endpoint, keyless eval at the bar)" 20 23
  v_group V5.1 "static checks 24-26 (keyless route, eval synced, spec)" 24 26
  v_group V6.1 "verify-phase0411.sh exists and is executable (check 27)" 27 27
  v_group V6.2 "phase-verify.yml matrix includes 0411 (check 30)" 30 30
  v_group V6.3 "all static checks in verify-phase0411.sh pass (1-32)" 1 32
}

# run_lane <counter-prefix> <desc> <command...>
lane_result() {
  local prefix="$1" desc="$2"
  shift 2
  if "$@"; then
    printf '[PASS] Lane: %s\n' "${desc}"
    eval "${prefix}_PASS+=1"
  else
    printf '[FAIL] Lane: %s\n' "${desc}" >&2
    eval "${prefix}_FAIL+=1"
  fi
}

web_typecheck() { npm --prefix web run --silent typecheck; }

web_specs() {
  (cd web && npm run --silent test:ci -- \
    tests/funding-lane.spec.ts \
    tests/visitor-key.spec.ts \
    tests/visitor-key-ui.spec.ts \
    tests/openrouter-connect.spec.ts \
    tests/keyless-lane.spec.ts \
    tests/keyless-lane-ui.spec.ts)
}

run_web() {
  WEB_PASS=0
  WEB_FAIL=0
  printf '\n-- web --\n'
  lane_result WEB "web typecheck" web_typecheck
  lane_result WEB "Phase 4.11 Playwright specs (V1.2, V2.2, V2.3, V3.2, V5.2)" web_specs
}

service_pytest() {
  "${PYTHON_BIN}" -m pytest -q \
    service/tests/test_visitor_endpoint.py \
    service/tests/test_score_endpoint.py \
    service/tests/test_engines.py \
    tests/test_audit_log_migration.py \
    tests/test_keyless_eval_shape.py \
    tests/test_funding_invariant.py
}

run_service() {
  SERVICE_PASS=0
  SERVICE_FAIL=0
  printf '\n-- service --\n'
  lane_result SERVICE "service + package pytest (V1.3, V2.4, V3.3, V4.2, V4.3, V6.6 logic)" service_pytest
}

sec_gitleaks() {
  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "gitleaks is not installed" >&2
    return 1
  fi
  local p rc=0
  while IFS= read -r p; do
    [[ -e "${p}" ]] || continue
    gitleaks dir --no-banner --redact "${p}" >/dev/null 2>&1 || {
      echo "gitleaks flagged: ${p}" >&2
      rc=1
    }
  done < <(phase_paths)
  return "${rc}"
}

sec_bandit() { "${PYTHON_BIN}" -m bandit -q -r src/ service/app; }
# pip-audit resolves the DECLARED dependencies of each package (pyproject.toml),
# so the answer does not depend on how stale the local venv is. tests.yml's
# security-scan job audits the freshly installed CI environment the same way.
sec_pip_audit() {
  "${PYTHON_BIN}" -m pip_audit . && "${PYTHON_BIN}" -m pip_audit ./service
}
sec_npm_audit() { npm --prefix web audit --omit=dev --audit-level=high; }

sec_literals() {
  local hits
  hits="$(secret_literal_hits)"
  if [[ -n "${hits}" ]]; then
    printf 'secret-shaped literal at:\n%s\n' "${hits}" >&2
    return 1
  fi
}

run_security() {
  SECURITY_PASS=0
  SECURITY_FAIL=0
  printf '\n-- security (V6.4) --\n'
  lane_result SECURITY "gitleaks over the phase's paths" sec_gitleaks
  lane_result SECURITY "bandit -r src/ service/app" sec_bandit
  lane_result SECURITY "pip-audit" sec_pip_audit
  lane_result SECURITY "npm audit --omit=dev --audit-level=high" sec_npm_audit
  lane_result SECURITY "no secret-shaped literal under the phase's paths" sec_literals
}

probe_lanes() {
  NODE_PATH="${ROOT}/web/node_modules" scripts/with-prod-secrets.sh \
    node web/node_modules/.bin/tsx scripts/probe-funding-lanes.ts
}

branch_checks() {
  gh pr checks
}

run_post() {
  POST_PASS=0
  POST_FAIL=0
  printf '\n-- post (V6.5, live) --\n'
  if [[ "$(uname -s)" != "Darwin" ]]; then
    printf '[SKIP] live lane probe: needs the macOS keychain (scripts/with-prod-secrets.sh)\n'
  else
    lane_result POST "live lane probe: one operator row (the founder's), counter delta = its cost" probe_lanes
  fi
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    # `gh pr checks` exits non-zero on a branch with no PR; that is not a failure here.
    if gh pr view >/dev/null 2>&1; then
      lane_result POST "gh pr checks on the current branch" branch_checks
    else
      printf '[SKIP] gh pr checks: no pull request for this branch\n'
    fi
  else
    printf '[SKIP] gh pr checks: gh is not logged in\n'
  fi
}

print_summary() {
  printf '\n== Summary ==\n'
  printf '%-22s %6s %6s\n' "Stage" "Pass" "Fail"
  printf '%-22s %6s %6s\n' "static-1..32" "${STATIC_PASS}" "${STATIC_FAIL}"
  if [[ "${MODE_POST}" -eq 1 || "${MODE_FAST}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "v-checks" "${V_PASS}" "${V_FAIL}"
  fi
  if [[ "${MODE_WEB}" -eq 1 ]]; then printf '%-22s %6s %6s\n' "web" "${WEB_PASS}" "${WEB_FAIL}"; fi
  if [[ "${MODE_SERVICE}" -eq 1 ]]; then printf '%-22s %6s %6s\n' "service" "${SERVICE_PASS}" "${SERVICE_FAIL}"; fi
  if [[ "${MODE_SECURITY}" -eq 1 ]]; then printf '%-22s %6s %6s\n' "security" "${SECURITY_PASS}" "${SECURITY_FAIL}"; fi
  if [[ "${MODE_POST}" -eq 1 ]]; then printf '%-22s %6s %6s\n' "post" "${POST_PASS}" "${POST_FAIL}"; fi
  if [[ ${#FAILED_CHECKS[@]} -gt 0 ]]; then
    printf 'Failed static checks: %s\n' "${FAILED_CHECKS[*]}" >&2
  fi
}

total_fail() {
  echo $((STATIC_FAIL + V_FAIL + WEB_FAIL + SERVICE_FAIL + SECURITY_FAIL + POST_FAIL))
}

# --- main flow ---
# --security is a standalone gate (the CI post job); it needs no static pass.
if [[ "${MODE_SECURITY}" -eq 1 && "${MODE_ALL}" -eq 0 ]]; then
  run_security
  print_summary
  [[ "${SECURITY_FAIL}" -gt 0 ]] && exit 1
  exit 0
fi

run_static_checks

if [[ "${MODE_FAST}" -eq 1 || "${MODE_POST}" -eq 1 ]]; then
  run_v_rollup
fi

if [[ "${STATIC_FAIL}" -gt 0 ]]; then
  print_summary
  exit 1
fi

if [[ "${MODE_WEB}" -eq 1 ]]; then run_web; fi
if [[ "${MODE_SERVICE}" -eq 1 ]]; then run_service; fi
if [[ "${MODE_SECURITY}" -eq 1 ]]; then run_security; fi
if [[ "${MODE_POST}" -eq 1 ]]; then run_post; fi

print_summary
[[ "$(total_fail)" -gt 0 ]] && exit 1
exit 0
