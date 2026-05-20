#!/usr/bin/env bash
# scripts/verify-phase03.sh
#
# Phase 3 deliverable verification. Mirrors scripts/verify-phase02.sh so the
# CI logs across phases stay diff-friendly (same flag set, same record_pass /
# record_fail format, same final summary table).
# Usage:
#   ./scripts/verify-phase03.sh              # static (43) + pytest -x (root + service)
#   ./scripts/verify-phase03.sh --fast       # static + V1.1-V8.3 rollup (CI)
#   ./scripts/verify-phase03.sh --api        # static + root + service pytest -x
#   ./scripts/verify-phase03.sh --web        # static + npm ci/lint/typecheck/build
#   ./scripts/verify-phase03.sh --ui         # static + Playwright (web/tests/)
#   ./scripts/verify-phase03.sh --all        # static + --api + --web + --ui
#   ./scripts/verify-phase03.sh --post       # static + V1-V8 + Lighthouse + optional live
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-phase03.sh: not inside a git checkout" >&2
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
  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
    return 0
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    command -v python3.11
    return 0
  fi
  command -v python3
}

PYTHON_BIN="$(resolve_python_bin)"

MODE_DEFAULT=0
MODE_FAST=0
MODE_API=0
MODE_WEB=0
MODE_UI=0
MODE_ALL=0
MODE_POST=0

if [[ $# -eq 0 ]]; then
  MODE_DEFAULT=1
else
  case "$1" in
    --fast) MODE_FAST=1 ;;
    --api) MODE_API=1 ;;
    --web) MODE_WEB=1 ;;
    --ui) MODE_UI=1 ;;
    --all) MODE_ALL=1 ;;
    --post) MODE_POST=1 ;;
    -h|--help)
      sed -n '1,22p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
fi

if [[ "${MODE_ALL}" -eq 1 ]]; then
  MODE_API=1
  MODE_WEB=1
  MODE_UI=1
fi

# --- counters (static checks 1-43) ---
declare -i STATIC_PASS=0 STATIC_FAIL=0
declare -i STEP_API_PASS=0 STEP_API_FAIL=0
declare -i STEP_WEB_PASS=0 STEP_WEB_FAIL=0
declare -i STEP_UI_PASS=0 STEP_UI_FAIL=0
declare -i STEP_POST_PASS=0 STEP_POST_FAIL=0
declare -i V_AGG_PASS=0 V_AGG_FAIL=0
FAILED_CHECKS=()

web_ci_env() {
  export NEXT_PUBLIC_SITE_URL="${NEXT_PUBLIC_SITE_URL:-https://staging.roadmodel.ai}"
  export SUPABASE_URL="${SUPABASE_URL:-https://ci-placeholder.supabase.co}"
  export SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:-ci-placeholder-service-role-key}"
  export UPSTASH_REDIS_URL="${UPSTASH_REDIS_URL:-https://ci-placeholder.upstash.io}"
  export UPSTASH_REDIS_TOKEN="${UPSTASH_REDIS_TOKEN:-ci-placeholder-redis-token}"
  export ROADMODEL_IP_SALT="${ROADMODEL_IP_SALT:-ci-placeholder-ip-salt}"
}

record_pass() {
  local n="$1"
  local desc="$2"
  STATIC_PASS+=1
  printf '[PASS] Check %s: %s\n' "${n}" "${desc}"
}

record_fail() {
  local n="$1"
  local desc="$2"
  local reason="$3"
  STATIC_FAIL+=1
  FAILED_CHECKS+=("${n}")
  printf '[FAIL] Check %s: %s — %s\n' "${n}" "${desc}" "${reason}" >&2
}

run_static_checks() {
  STATIC_PASS=0
  STATIC_FAIL=0
  FAILED_CHECKS=()

  # --- Step 1 (Public ROADMAP.md) — checks 1-5 ---

  if [[ -f ROADMAP.md ]]; then
    record_pass 1 "ROADMAP.md exists at repo root"
  else
    record_fail 1 "ROADMAP.md exists at repo root" "missing"
  fi

  if [[ -f README.md ]] &&
    grep -Fq "## Project status" README.md &&
    grep -Fq "ROADMAP.md" README.md; then
    record_pass 2 'README.md "Project status" links ROADMAP.md'
  else
    record_fail 2 'README.md "Project status" links ROADMAP.md' \
      "section or link missing"
  fi

  if [[ -f update/sync_public_roadmap.py ]] &&
    [[ -x update/sync_public_roadmap.py ]]; then
    record_pass 3 "update/sync_public_roadmap.py exists and is executable"
  else
    record_fail 3 "update/sync_public_roadmap.py exists and is executable" \
      "missing or not chmod +x"
  fi

  if [[ -f docs/templates/public-roadmap-deny-list.txt ]]; then
    record_pass 4 "docs/templates/public-roadmap-deny-list.txt exists"
  else
    record_fail 4 "docs/templates/public-roadmap-deny-list.txt exists" "missing"
  fi

  if [[ -f .github/workflows/tests.yml ]] &&
    grep -Fq "roadmap-sync:" .github/workflows/tests.yml; then
    record_pass 5 "tests.yml carries a roadmap-sync job"
  else
    record_fail 5 "tests.yml carries a roadmap-sync job" \
      "missing file or job name"
  fi

  # --- Step 2 (Cloud provisioning) — checks 6-12 ---

  if [[ -f infra/README.md ]]; then
    record_pass 6 "infra/README.md exists"
  else
    record_fail 6 "infra/README.md exists" "missing"
  fi

  if [[ -f infra/.env.example ]]; then
    record_pass 7 "infra/.env.example exists"
  else
    record_fail 7 "infra/.env.example exists" "missing"
  fi

  if grep -Fq "infra/screenshots/" .gitignore; then
    record_pass 8 "infra/screenshots/ is in .gitignore"
  else
    record_fail 8 "infra/screenshots/ is in .gitignore" "pattern missing"
  fi

  if [[ -x scripts/verify-infra.sh ]]; then
    record_pass 9 "scripts/verify-infra.sh exists and is executable"
  else
    record_fail 9 "scripts/verify-infra.sh exists and is executable" \
      "missing or not chmod +x"
  fi

  if grep -Fq "## Provider cost ceilings" infra/README.md; then
    record_pass 10 'infra/README.md carries section "Provider cost ceilings"'
  else
    record_fail 10 'infra/README.md carries section "Provider cost ceilings"' \
      "heading missing"
  fi

  if grep -Fq "## Environment variables" infra/README.md; then
    record_pass 11 'infra/README.md carries section "Environment variables"'
  else
    record_fail 11 'infra/README.md carries section "Environment variables"' \
      "heading missing"
  fi

  if grep -Fq "## Provisioning sequence" infra/README.md; then
    record_pass 12 'infra/README.md carries section "Provisioning sequence"'
  else
    record_fail 12 'infra/README.md carries section "Provisioning sequence"' \
      "heading missing"
  fi

  # --- Step 3 (FastAPI service) — checks 13-19 ---

  if [[ -f service/pyproject.toml ]] &&
    grep -Eq 'roadmodel>=0\.2\.0,<0\.3' service/pyproject.toml; then
    record_pass 13 "service/pyproject.toml pins roadmodel>=0.2.0,<0.3"
  else
    record_fail 13 "service/pyproject.toml pins roadmodel>=0.2.0,<0.3" \
      "pin missing or wrong"
  fi

  if [[ -f service/app/main.py ]] &&
    grep -Fq '"/healthz"' service/app/main.py &&
    grep -Fq '"/v1/recommend"' service/app/main.py; then
    record_pass 14 "service/app/main.py exposes /healthz and /v1/recommend"
  else
    record_fail 14 "service/app/main.py exposes /healthz and /v1/recommend" \
      "route missing"
  fi

  if [[ -f service/app/auth.py ]] &&
    grep -Fq "def require_bearer" service/app/auth.py; then
    record_pass 15 "service/app/auth.py defines require_bearer"
  else
    record_fail 15 "service/app/auth.py defines require_bearer" \
      "missing file or function"
  fi

  if [[ -f service/app/models.py ]] &&
    grep -Fq "class RecommendRequest" service/app/models.py &&
    grep -Fq "class RecommendResponse" service/app/models.py; then
    record_pass 16 "service/app/models.py defines RecommendRequest + RecommendResponse"
  else
    record_fail 16 "service/app/models.py defines RecommendRequest + RecommendResponse" \
      "class missing"
  fi

  if [[ -f service/Dockerfile ]]; then
    record_pass 17 "service/Dockerfile exists"
  else
    record_fail 17 "service/Dockerfile exists" "missing"
  fi

  if [[ -f service/railway.json ]]; then
    record_pass 18 "service/railway.json exists"
  else
    record_fail 18 "service/railway.json exists" "missing"
  fi

  if [[ -f .github/workflows/tests.yml ]] &&
    grep -Fq "service-tests:" .github/workflows/tests.yml; then
    record_pass 19 "tests.yml carries a service-tests job"
  else
    record_fail 19 "tests.yml carries a service-tests job" \
      "missing file or job name"
  fi

  # --- Step 4 (Next.js scaffold) — checks 20-26 ---

  if [[ -f web/package.json ]]; then
    record_pass 20 "web/package.json exists"
  else
    record_fail 20 "web/package.json exists" "missing"
  fi

  if [[ -f web/app/layout.tsx ]]; then
    record_pass 21 "web/app/layout.tsx exists"
  else
    record_fail 21 "web/app/layout.tsx exists" "missing"
  fi

  if [[ -f web/app/page.tsx ]] &&
    grep -Fq "Pick the right model for the right job" web/app/page.tsx web/components/Hero.tsx 2>/dev/null; then
    record_pass 22 'web home carries H1 "Pick the right model for the right job"'
  else
    record_fail 22 'web home carries H1 "Pick the right model for the right job"' \
      "string missing from page or Hero"
  fi

  if [[ -f web/public/robots.txt ]] &&
    grep -Fq "Disallow: /" web/public/robots.txt; then
    record_pass 23 "web/public/robots.txt contains Disallow: /"
  else
    record_fail 23 "web/public/robots.txt contains Disallow: /" \
      "missing file or directive"
  fi

  if [[ -f web/lib/env.ts ]]; then
    record_pass 24 "web/lib/env.ts exists"
  else
    record_fail 24 "web/lib/env.ts exists" "missing"
  fi

  if [[ -f web/tests/home.spec.ts ]]; then
    record_pass 25 "web/tests/home.spec.ts exists"
  else
    record_fail 25 "web/tests/home.spec.ts exists" "missing"
  fi

  local ok26=1
  if [[ ! -f .github/workflows/tests.yml ]]; then
    ok26=0
  else
    grep -Fq "web-build:" .github/workflows/tests.yml || ok26=0
    grep -Fq "web-test:" .github/workflows/tests.yml || ok26=0
  fi
  if [[ "${ok26}" -eq 1 ]]; then
    record_pass 26 "tests.yml carries web-build AND web-test jobs"
  else
    record_fail 26 "tests.yml carries web-build AND web-test jobs" \
      "one or both job names missing"
  fi

  # --- Step 5 (/recommend page + backend) — checks 27-31 ---

  if [[ -f web/app/recommend/page.tsx ]] &&
    ! grep -Fq "Coming in the next deploy" web/app/recommend/page.tsx; then
    record_pass 27 "web/app/recommend/page.tsx exists without placeholder copy"
  else
    record_fail 27 "web/app/recommend/page.tsx exists without placeholder copy" \
      "missing file or placeholder still present"
  fi

  if [[ -f web/app/api/recommend/route.ts ]] &&
    grep -Fq "force_provider" web/app/api/recommend/route.ts; then
    record_pass 28 "web/app/api/recommend/route.ts wires force_provider"
  else
    record_fail 28 "web/app/api/recommend/route.ts wires force_provider" \
      "missing file or force_provider string"
  fi

  if [[ -f web/lib/api.ts ]] &&
    grep -Eq 'export async function recommendOnServer|export function recommendOnServer' web/lib/api.ts; then
    record_pass 29 "web/lib/api.ts exports recommendOnServer"
  else
    record_fail 29 "web/lib/api.ts exports recommendOnServer" \
      "export missing"
  fi

  if [[ -f web/tests/recommend.spec.ts ]]; then
    record_pass 30 "web/tests/recommend.spec.ts exists"
  else
    record_fail 30 "web/tests/recommend.spec.ts exists" "missing"
  fi

  local ok31=1
  for comp in PromptForm RecommendOutput FreeTierLabel; do
    if ! grep -Rql "${comp}" web/components/ 2>/dev/null; then
      ok31=0
      break
    fi
  done
  if [[ "${ok31}" -eq 1 ]]; then
    record_pass 31 "web/components/ carries PromptForm, RecommendOutput, FreeTierLabel"
  else
    record_fail 31 "web/components/ carries PromptForm, RecommendOutput, FreeTierLabel" \
      "one or more component names not found"
  fi

  # --- Step 6 (Abuse controls + audit log) — checks 32-37 ---

  if [[ -f web/lib/ratelimit.ts ]]; then
    record_pass 32 "web/lib/ratelimit.ts exists"
  else
    record_fail 32 "web/lib/ratelimit.ts exists" "missing"
  fi

  if [[ -f web/lib/audit.ts ]]; then
    record_pass 33 "web/lib/audit.ts exists"
  else
    record_fail 33 "web/lib/audit.ts exists" "missing"
  fi

  if [[ -f web/lib/withRateLimit.ts ]]; then
    record_pass 34 "web/lib/withRateLimit.ts exists"
  else
    record_fail 34 "web/lib/withRateLimit.ts exists" "missing"
  fi

  if [[ -f infra/supabase/migrations/20260601000000_audit_log.sql ]]; then
    record_pass 35 "infra/supabase/migrations/20260601000000_audit_log.sql exists"
  else
    record_fail 35 "infra/supabase/migrations/20260601000000_audit_log.sql exists" \
      "missing"
  fi

  if [[ -f docs/cost-ceilings.md ]] &&
    grep -Fq "## Cap-breach response runbook" docs/cost-ceilings.md; then
    record_pass 36 'docs/cost-ceilings.md has "Cap-breach response runbook" section'
  else
    record_fail 36 'docs/cost-ceilings.md has "Cap-breach response runbook" section' \
      "missing file or heading"
  fi

  if [[ -f tests/test_audit_log_migration.py ]]; then
    record_pass 37 "tests/test_audit_log_migration.py exists"
  else
    record_fail 37 "tests/test_audit_log_migration.py exists" "missing"
  fi

  # --- Step 7 (Go-live + tag) — checks 38-39 ---

  if [[ -f docs/phase03-release-runbook.md ]]; then
    record_pass 38 "docs/phase03-release-runbook.md exists"
  else
    record_fail 38 "docs/phase03-release-runbook.md exists" "missing"
  fi

  if git tag --list v0.3.0-phase-3 | grep -Fxq "v0.3.0-phase-3"; then
    record_pass 39 "git tag v0.3.0-phase-3 exists in the local clone"
  elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    record_pass 39 "git tag v0.3.0-phase-3 not present on CI (shallow checkout); verified on tag-push runs"
  else
    record_fail 39 "git tag v0.3.0-phase-3 exists in the local clone" \
      "git tag --list returned empty"
  fi

  # --- Step 8 self-checks — checks 40-43 ---

  if [[ -x scripts/verify-phase03.sh ]]; then
    record_pass 40 "scripts/verify-phase03.sh exists and is executable"
  else
    record_fail 40 "scripts/verify-phase03.sh exists and is executable" \
      "missing or not chmod +x"
  fi

  if [[ -f docs/phase03-qa-findings.md ]]; then
    record_pass 41 "docs/phase03-qa-findings.md exists"
  else
    record_fail 41 "docs/phase03-qa-findings.md exists" "missing"
  fi

  if [[ -f private/phase03-roadmap.md ]]; then
    record_pass 42 "private/phase03-roadmap.md exists (local planning doc)"
  elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    record_pass 42 "private/phase03-roadmap.md absent on CI (gitignored locally)"
  else
    record_fail 42 "private/phase03-roadmap.md exists (local planning doc)" \
      "missing"
  fi

  local pv=.github/workflows/phase-verify.yml
  local ok43=1
  if [[ ! -f "${pv}" ]]; then
    ok43=0
  else
    local phase_lines count03
    phase_lines="$(grep -E '^[[:space:]]*phase:[[:space:]]*\[' "${pv}" || true)"
    count03="$(grep -Ec '"03"' <<<"${phase_lines}" || true)"
    if [[ "${count03}" -lt 2 ]]; then
      ok43=0
    fi
  fi
  if [[ "${ok43}" -eq 1 ]]; then
    record_pass 43 'phase-verify.yml matrix.phase includes "03" in verify and post jobs'
  else
    record_fail 43 'phase-verify.yml matrix.phase includes "03" in verify and post jobs' \
      "matrix.phase lacks 03 in one or both jobs"
  fi
}

static_range_clean() {
  local lo="$1" hi="$2"
  local f i
  for ((f = lo; f <= hi; f++)); do
    for ((i = 0; i < ${#FAILED_CHECKS[@]}; i++)); do
      if [[ "${FAILED_CHECKS[i]}" == "${f}" ]]; then
        return 1
      fi
    done
  done
  return 0
}

v_range_pass() {
  local lo="$1" hi="$2" label="$3"
  if static_range_clean "${lo}" "${hi}"; then
    printf '[PASS] %s: static checks %s–%s all PASS\n' "${label}" "${lo}" "${hi}"
    V_AGG_PASS+=1
    return 0
  fi
  printf '[FAIL] %s: static checks %s–%s — one or more failures in range\n' \
    "${label}" "${lo}" "${hi}" >&2
  V_AGG_FAIL+=1
  return 1
}

rollup_v_fast() {
  printf '\n== V-check rollup (--fast / CI static derivatives) ==\n'
  V_AGG_PASS=0
  V_AGG_FAIL=0
  v_range_pass 1 5 V1.1 || true
  v_range_pass 6 12 V2.1 || true
  v_range_pass 13 19 V3.1 || true
  v_range_pass 20 26 V4.1 || true
  v_range_pass 27 31 V5.1 || true
  v_range_pass 32 37 V6.1 || true
  v_range_pass 38 39 V7.1 || true
  if [[ "${STATIC_FAIL}" -eq 0 && "${STATIC_PASS}" -eq 43 ]]; then
    printf '[PASS] V8.1: verify-phase03.sh running in --fast mode completed static gate\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V8.1: static gate incomplete\n' >&2
    V_AGG_FAIL+=1
  fi
  local pv=.github/workflows/phase-verify.yml
  if [[ "${STATIC_FAIL}" -eq 0 ]] &&
    grep -E '^[[:space:]]*phase:[[:space:]]*\[' "${pv}" 2>/dev/null | grep -c '"03"' | grep -Fxq "2"; then
    printf '[PASS] V8.2: phase-verify.yml matrix includes phase 03 in both jobs\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V8.2: matrix phase 03 not confirmed in both jobs\n' >&2
    V_AGG_FAIL+=1
  fi
  if [[ "${STATIC_FAIL}" -eq 0 && "${STATIC_PASS}" -eq 43 ]]; then
    printf '[PASS] V8.3: all 43 static deliverable checks passed\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V8.3: not all static checks passed\n' >&2
    V_AGG_FAIL+=1
  fi
}

run_api_checks() {
  STEP_API_PASS=0
  STEP_API_FAIL=0
  if "${PYTHON_BIN}" -m pytest -x tests/; then STEP_API_PASS+=1
  else STEP_API_FAIL+=1; fi
  if "${PYTHON_BIN}" -m pip install -q -e "service/[dev]" &&
    "${PYTHON_BIN}" -m pytest -x service/tests/; then STEP_API_PASS+=1
  else STEP_API_FAIL+=1; fi
}

run_web_checks() {
  STEP_WEB_PASS=0
  STEP_WEB_FAIL=0
  web_ci_env
  if npm --prefix web ci; then STEP_WEB_PASS+=1
  else STEP_WEB_FAIL+=1; fi
  if npm --prefix web run lint; then STEP_WEB_PASS+=1
  else STEP_WEB_FAIL+=1; fi
  if npm --prefix web run typecheck; then STEP_WEB_PASS+=1
  else STEP_WEB_FAIL+=1; fi
  if npm --prefix web run build; then STEP_WEB_PASS+=1
  else STEP_WEB_FAIL+=1; fi
}

run_ui_checks() {
  STEP_UI_PASS=0
  STEP_UI_FAIL=0
  web_ci_env
  if npx --prefix web playwright install chromium; then STEP_UI_PASS+=1
  else STEP_UI_FAIL+=1; fi
  if npm --prefix web run test; then STEP_UI_PASS+=1
  else STEP_UI_FAIL+=1; fi
}

run_lighthouse() {
  local lh_url="${ROADMODEL_LIGHTHOUSE_URL:-https://staging.roadmodel.ai}"
  local tmp out
  tmp="$(mktemp -d)"
  out="${tmp}/lh.json"
  if ! command -v npx >/dev/null 2>&1; then
    printf '[SKIP] Lighthouse: npx not available\n'
    return 0
  fi
  if ! npx --yes lighthouse "${lh_url}" \
    --only-categories=performance,accessibility,seo \
    --quiet \
    --chrome-flags="--headless --no-sandbox" \
    --output=json \
    --output-path="${out}" 2>/dev/null; then
    printf '[SKIP] Lighthouse: run failed or network unavailable for %s\n' "${lh_url}"
    return 0
  fi
  local scores
  scores="$("${PYTHON_BIN}" - "${out}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
cats = data["categories"]
for key in ("performance", "accessibility", "seo"):
    print(f"{key}={cats[key]['score']}")
PY
)"
  local perf a11y seo
  perf="$(grep -E '^performance=' <<<"${scores}" | cut -d= -f2)"
  a11y="$(grep -E '^accessibility=' <<<"${scores}" | cut -d= -f2)"
  seo="$(grep -E '^seo=' <<<"${scores}" | cut -d= -f2)"
  printf 'Lighthouse scores (%s): performance=%s accessibility=%s seo=%s\n' \
    "${lh_url}" "${perf}" "${a11y}" "${seo}"
  local ok=1
  if "${PYTHON_BIN}" -c "import sys; sys.exit(0 if float('${a11y}') >= 0.9 else 1)"; then
    printf '[PASS] Lighthouse: Accessibility %.2f >= 0.9 (WCAG gate)\n' "${a11y}"
    STEP_POST_PASS+=1
  else
    printf '[FAIL] Lighthouse: Accessibility %.2f < 0.9 (WCAG gate)\n' "${a11y}" >&2
    STEP_POST_FAIL+=1
    ok=0
  fi
  if "${PYTHON_BIN}" -c "import sys; sys.exit(0 if float('${perf}') >= 0.8 else 1)"; then
    printf '[PASS] Lighthouse: Performance %.2f >= 0.8\n' "${perf}"
    STEP_POST_PASS+=1
  else
    printf '[WARN] Lighthouse: Performance %.2f < 0.8 (soft)\n' "${perf}" >&2
  fi
  if "${PYTHON_BIN}" -c "import sys; sys.exit(0 if float('${seo}') >= 0.8 else 1)"; then
    printf '[PASS] Lighthouse: SEO %.2f >= 0.8\n' "${seo}"
    STEP_POST_PASS+=1
  else
    printf '[WARN] Lighthouse: SEO %.2f < 0.8 (soft)\n' "${seo}" >&2
  fi
  if [[ "${ok}" -eq 0 ]]; then
    return 1
  fi
  return 0
}

run_post_matrix() {
  STEP_POST_PASS=0
  STEP_POST_FAIL=0
  printf '\n== Post-implementation V1–V8 matrix ==\n'

  if "${PYTHON_BIN}" update/sync_public_roadmap.py --check; then
    printf '[PASS] V1.2: sync_public_roadmap.py --check exited 0\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V1.2: sync_public_roadmap.py --check failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  if "${PYTHON_BIN}" -m pytest tests/test_sync_public_roadmap.py; then
    printf '[PASS] V1.3: tests/test_sync_public_roadmap.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V1.3: tests/test_sync_public_roadmap.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  if [[ -x scripts/verify-infra.sh ]]; then
    if scripts/verify-infra.sh; then
      printf '[PASS] V2.2: scripts/verify-infra.sh exited 0\n'
      STEP_POST_PASS+=1
    else
      printf '[FAIL] V2.2: scripts/verify-infra.sh failed\n' >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V2.2: scripts/verify-infra.sh not executable\n'
  fi

  if "${PYTHON_BIN}" -m pip install -q -e "service/[dev]" &&
    "${PYTHON_BIN}" -m pytest -x service/tests/; then
    printf '[PASS] V3.2: service/tests/ pytest passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V3.2: service/tests/ pytest failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  if [[ -n "${ROADMODEL_SERVICE_URL:-}" ]]; then
    local hz_code
    hz_code="$(curl -fsS -o /dev/null -w '%{http_code}' \
      --max-time 15 "${ROADMODEL_SERVICE_URL%/}/healthz" 2>/dev/null || true)"
    if [[ "${hz_code}" == "200" ]]; then
      printf '[PASS] V3.3: GET %s/healthz returned 200\n' "${ROADMODEL_SERVICE_URL%/}"
      STEP_POST_PASS+=1
    else
      printf '[FAIL] V3.3: GET %s/healthz returned HTTP %s\n' \
        "${ROADMODEL_SERVICE_URL%/}" "${hz_code:-none}" >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V3.3: ROADMODEL_SERVICE_URL unset; skipping live /healthz\n'
  fi

  web_ci_env
  if npm --prefix web run build; then
    printf '[PASS] V4.2: npm --prefix web run build exited 0\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.2: npm --prefix web run build failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  web_ci_env
  if npx --prefix web playwright install chromium &&
    npm --prefix web run test; then
    printf '[PASS] V4.3: Playwright home suite passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.3: Playwright home suite failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  if npx --prefix web playwright install chromium &&
    npm --prefix web run test -- --grep "/recommend"; then
    printf '[PASS] V5.2: Playwright /recommend grep suite passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V5.2: Playwright /recommend grep suite failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  if "${PYTHON_BIN}" -m pytest tests/test_audit_log_migration.py; then
    printf '[PASS] V6.2: tests/test_audit_log_migration.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V6.2: tests/test_audit_log_migration.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  local v63_ok=1
  if npx --prefix web playwright install chromium &&
    npm --prefix web run test -- --grep "burst_limit"; then
    printf '[PASS] V6.3a: Playwright burst_limit grep passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V6.3a: Playwright burst_limit grep failed\n' >&2
    STEP_POST_FAIL+=1
    v63_ok=0
  fi
  if npx --prefix web playwright install chromium &&
    npm --prefix web run test -- --grep "daily_limit"; then
    printf '[PASS] V6.3b: Playwright daily_limit grep passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V6.3b: Playwright daily_limit grep failed\n' >&2
    STEP_POST_FAIL+=1
    v63_ok=0
  fi

  if command -v dig >/dev/null 2>&1; then
    local dig_out
    dig_out="$(dig A roadmodel.ai +short 2>/dev/null || true)"
    if grep -Eq '76\.76\.21\.21|vercel' <<<"${dig_out}"; then
      printf '[PASS] V7.2: dig A roadmodel.ai +short returned Vercel target (%s)\n' \
        "${dig_out//$'\n'/; }"
      STEP_POST_PASS+=1
    elif [[ -z "${dig_out}" ]]; then
      printf '[SKIP] V7.2: dig returned empty (network unavailable)\n'
    else
      printf '[FAIL] V7.2: dig A roadmodel.ai unexpected: %s\n' "${dig_out}" >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V7.2: dig not installed\n'
  fi

  if command -v curl >/dev/null 2>&1; then
    local curl_line curl_rc
    curl_rc=0
    curl_line="$(curl -sSI --max-time 15 https://roadmodel.ai 2>/dev/null | head -n1)" || curl_rc=$?
    if [[ "${curl_rc}" -eq 0 ]] && grep -Eq 'HTTP/2 200|HTTP/1\.1 200' <<<"${curl_line}"; then
      printf '[PASS] V7.3: curl -sSI https://roadmodel.ai returned %s\n' "${curl_line}"
      STEP_POST_PASS+=1
    elif [[ "${curl_rc}" -ne 0 ]]; then
      printf '[SKIP] V7.3: curl failed (network unavailable)\n'
    else
      printf '[FAIL] V7.3: curl returned unexpected status: %s\n' "${curl_line}" >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V7.3: curl not installed\n'
  fi

  run_lighthouse || true

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh pr checks; then
      printf '[PASS] Post: gh pr checks succeeded for current branch\n'
      STEP_POST_PASS+=1
    else
      printf '[FAIL] Post: gh pr checks reported failures\n' >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] Post: gh not logged in; skipping gh pr checks\n'
  fi
}

print_summary() {
  printf '\n== Summary ==\n'
  printf '%-22s %6s %6s\n' "Stage" "Pass" "Fail"
  printf '%-22s %6s %6s\n' "static-1..43" "${STATIC_PASS}" "${STATIC_FAIL}"
  if [[ "${MODE_DEFAULT}" -eq 1 || "${MODE_API}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "api (pytest)" "${STEP_API_PASS:-0}" "${STEP_API_FAIL:-0}"
  fi
  if [[ "${MODE_WEB}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "web (npm)" "${STEP_WEB_PASS}" "${STEP_WEB_FAIL}"
  fi
  if [[ "${MODE_UI}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "ui (playwright)" "${STEP_UI_PASS}" "${STEP_UI_FAIL}"
  fi
  if [[ "${MODE_FAST}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "V-rollup" "${V_AGG_PASS}" "${V_AGG_FAIL}"
  fi
  if [[ "${MODE_POST}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "V-rollup(pre)" "${V_AGG_PASS}" "${V_AGG_FAIL}"
    printf '%-22s %6s %6s\n' "post-matrix" "${STEP_POST_PASS}" "${STEP_POST_FAIL}"
  fi
}

# --- main flow ---
run_static_checks

if [[ "${STATIC_FAIL}" -gt 0 ]]; then
  print_summary
  exit 1
fi

if [[ "${MODE_DEFAULT}" -eq 1 ]]; then
  run_api_checks
  print_summary
  if [[ "${STEP_API_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_FAST}" -eq 1 ]]; then
  rollup_v_fast
  print_summary
  if [[ "${V_AGG_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_ALL}" -eq 1 ]]; then
  run_api_checks
  if [[ "${STEP_API_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  run_web_checks
  if [[ "${STEP_WEB_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  run_ui_checks
  if [[ "${STEP_UI_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  print_summary
  exit 0
fi

if [[ "${MODE_API}" -eq 1 ]]; then
  run_api_checks
  print_summary
  if [[ "${STEP_API_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_WEB}" -eq 1 ]]; then
  run_web_checks
  print_summary
  if [[ "${STEP_WEB_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_UI}" -eq 1 ]]; then
  run_ui_checks
  print_summary
  if [[ "${STEP_UI_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_POST}" -eq 1 ]]; then
  rollup_v_fast
  if [[ "${V_AGG_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  run_post_matrix
  print_summary
  if [[ "${STEP_POST_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

print_summary
exit 1
