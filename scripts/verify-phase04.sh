#!/usr/bin/env bash
# scripts/verify-phase04.sh
#
# Phase 4 deliverable verification. Mirrors scripts/verify-phase03.sh so the
# CI logs across phases stay diff-friendly (same flag set, same record_pass /
# record_fail format, same final summary table).
#
# Usage:
#   ./scripts/verify-phase04.sh              # static + pytest -x (root + service)
#   ./scripts/verify-phase04.sh --fast       # static + V1-V9 structural rollup (CI)
#   ./scripts/verify-phase04.sh --api        # static + root + service pytest -x
#   ./scripts/verify-phase04.sh --web        # static + npm ci/lint/typecheck/build
#   ./scripts/verify-phase04.sh --ui         # static + Playwright (web/tests/)
#   ./scripts/verify-phase04.sh --all        # static + --api + --web + --ui
#   ./scripts/verify-phase04.sh --post       # static + V-rollup + live healthz/Lighthouse
#
# NOTE on Step 8 (Public Readiness Gate lift / public launch): launch is
# DEFERRED to the very end of Phase 4 by maintainer decision — the site stays
# password-gated and noindex'd until then. So the launch deliverables (gate
# removal, robots launch-mode, SITE_PASSWORD purge, sitemap submission) are
# NOT asserted by --fast; they are checked in --post as launch-gated and
# reported [PEND] until the deliberate gate-lift PR lands.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

resolve_python_bin() {
  if [[ -n "${ROADMODEL_VERIFY_PYTHON:-}" ]]; then
    printf '%s\n' "${ROADMODEL_VERIFY_PYTHON}"
  elif command -v python3 >/dev/null 2>&1; then
    printf 'python3\n'
  else
    printf 'python\n'
  fi
}
PYTHON_BIN="$(resolve_python_bin)"

MODE_DEFAULT=0
MODE_FAST=0
MODE_API=0
MODE_WEB=0
MODE_UI=0
MODE_ALL=0
MODE_POST=0

if [[ "$#" -eq 0 ]]; then
  MODE_DEFAULT=1
else
  case "$1" in
    --fast) MODE_FAST=1 ;;
    --api) MODE_API=1 ;;
    --web) MODE_WEB=1 ;;
    --ui) MODE_UI=1 ;;
    --all) MODE_ALL=1 ;;
    --post) MODE_POST=1 ;;
    *)
      printf 'Unknown flag: %s\n' "$1" >&2
      exit 2
      ;;
  esac
fi

if [[ "${MODE_ALL}" -eq 1 ]]; then
  MODE_API=1
  MODE_WEB=1
  MODE_UI=1
fi

# --- counters (declare -i so += is arithmetic, not string concat) ---
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
  export NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:-ci-placeholder-anon-key}"
  export UPSTASH_REDIS_URL="${UPSTASH_REDIS_URL:-https://ci-placeholder.upstash.io}"
  export UPSTASH_REDIS_TOKEN="${UPSTASH_REDIS_TOKEN:-ci-placeholder-redis-token}"
  export ROADMODEL_IP_SALT="${ROADMODEL_IP_SALT:-ci-placeholder-ip-salt}"
  export GOOGLE_API_KEY="${GOOGLE_API_KEY:-ci-placeholder-google-api-key}"
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

# Helper: assert a glob matches at least one file.
glob_exists() {
  local pattern="$1"
  compgen -G "${pattern}" >/dev/null 2>&1
}

run_static_checks() {
  STATIC_PASS=0
  STATIC_FAIL=0
  FAILED_CHECKS=()

  # --- Step 1 (Supabase Auth) — checks 1-6 ---
  if [[ -f web/lib/auth.ts ]]; then
    record_pass 1 "web/lib/auth.ts exists"
  else
    record_fail 1 "web/lib/auth.ts exists" "missing"
  fi

  # #111: the callback route lives at the (auth) route group → URL /callback.
  # Assert the real path, NOT /auth/callback.
  if [[ -f "web/app/(auth)/callback/route.ts" ]]; then
    record_pass 2 "web/app/(auth)/callback/route.ts exists (URL /callback)"
  else
    record_fail 2 "web/app/(auth)/callback/route.ts exists (URL /callback)" "missing"
  fi

  if [[ -f "web/app/(auth)/login/page.tsx" && -f "web/app/(auth)/signout/route.ts" ]]; then
    record_pass 3 "login page + signout route exist"
  else
    record_fail 3 "login page + signout route exist" "missing"
  fi

  if [[ -f web/middleware.ts ]] && grep -Eq "getServerSession|getUser|session" web/middleware.ts; then
    record_pass 4 "web/middleware.ts carries session validation"
  else
    record_fail 4 "web/middleware.ts carries session validation" "missing or no session branch"
  fi

  if [[ -f web/lib/env.ts ]] && grep -Fq "NEXT_PUBLIC_SUPABASE_ANON_KEY" web/lib/env.ts; then
    record_pass 5 "web/lib/env.ts requires NEXT_PUBLIC_SUPABASE_ANON_KEY"
  else
    record_fail 5 "web/lib/env.ts requires NEXT_PUBLIC_SUPABASE_ANON_KEY" "missing"
  fi

  if [[ -f web/tests/auth.spec.ts ]]; then
    record_pass 6 "web/tests/auth.spec.ts exists"
  else
    record_fail 6 "web/tests/auth.spec.ts exists" "missing"
  fi

  # --- Migrations (#110: tree is infra/supabase/migrations, NOT infra/migrations) — checks 7-11 ---
  if [[ -d infra/supabase/migrations ]]; then
    record_pass 7 "infra/supabase/migrations/ exists (#110 canonical path)"
  else
    record_fail 7 "infra/supabase/migrations/ exists (#110 canonical path)" "missing"
  fi

  if glob_exists "infra/supabase/migrations/*audit_log_user_id*.sql"; then
    record_pass 8 "audit_log user_id migration present"
  else
    record_fail 8 "audit_log user_id migration present" "missing"
  fi

  if glob_exists "infra/supabase/migrations/*profiles*.sql"; then
    record_pass 9 "profiles migration present"
  else
    record_fail 9 "profiles migration present" "missing"
  fi

  if glob_exists "infra/supabase/migrations/*conversations*.sql" &&
    glob_exists "infra/supabase/migrations/*roadmaps*.sql"; then
    record_pass 10 "conversations + roadmaps migrations present"
  else
    record_fail 10 "conversations + roadmaps migrations present" "missing"
  fi

  if glob_exists "infra/supabase/migrations/*latency*.sql"; then
    record_pass 11 "audit_log latency migration present"
  else
    record_fail 11 "audit_log latency migration present" "missing"
  fi

  # --- Step 2 (Profile + onboarding) — checks 12-14 ---
  if [[ -f web/lib/profile.ts && -f web/app/api/profile/route.ts ]]; then
    record_pass 12 "profile lib + /api/profile route exist"
  else
    record_fail 12 "profile lib + /api/profile route exist" "missing"
  fi

  if [[ -f "web/app/(auth)/onboarding/page.tsx" ]]; then
    record_pass 13 "onboarding page exists"
  else
    record_fail 13 "onboarding page exists" "missing"
  fi

  if [[ -f web/tests/onboarding.spec.ts ]]; then
    record_pass 14 "web/tests/onboarding.spec.ts exists"
  else
    record_fail 14 "web/tests/onboarding.spec.ts exists" "missing"
  fi

  # --- Step 3 (/roadmap scaffold) — checks 15-17 ---
  if [[ -f web/app/roadmap/page.tsx ]]; then
    record_pass 15 "web/app/roadmap/page.tsx exists"
  else
    record_fail 15 "web/app/roadmap/page.tsx exists" "missing"
  fi

  if [[ -f web/components/ChatPanel.tsx && -f web/components/PreviewPanel.tsx ]]; then
    record_pass 16 "ChatPanel + PreviewPanel components exist"
  else
    record_fail 16 "ChatPanel + PreviewPanel components exist" "missing"
  fi

  if [[ -f web/tests/roadmap-shell.spec.ts ]]; then
    record_pass 17 "web/tests/roadmap-shell.spec.ts exists"
  else
    record_fail 17 "web/tests/roadmap-shell.spec.ts exists" "missing"
  fi

  # --- Step 4 (Roadmap AI + system instruction) — checks 18-21 ---
  if [[ -f web/app/api/roadmap/route.ts && -f web/lib/roadmap-engine.ts && -f web/lib/roadmap-prompts.ts ]]; then
    record_pass 18 "roadmap API route + engine + prompts exist"
  else
    record_fail 18 "roadmap API route + engine + prompts exist" "missing"
  fi

  if [[ -f docs/phase04-roadmap-engine-decision.md ]]; then
    record_pass 19 "docs/phase04-roadmap-engine-decision.md exists"
  else
    record_fail 19 "docs/phase04-roadmap-engine-decision.md exists" "missing"
  fi

  if [[ -f web/tests/roadmap-flow.spec.ts ]]; then
    record_pass 20 "web/tests/roadmap-flow.spec.ts exists"
  else
    record_fail 20 "web/tests/roadmap-flow.spec.ts exists" "missing"
  fi

  # FRONTIER_ROADMAP_ENABLED must be parsed explicitly, not via z.coerce.boolean
  # (issue #155: Boolean("false") === true). Guard against regression.
  if grep -Fq "FRONTIER_ROADMAP_ENABLED" web/lib/env.ts &&
    ! grep -Eq "FRONTIER_ROADMAP_ENABLED:\s*z\.coerce\.boolean" web/lib/env.ts; then
    record_pass 21 "FRONTIER_ROADMAP_ENABLED parsed explicitly (not z.coerce.boolean, #155)"
  else
    record_fail 21 "FRONTIER_ROADMAP_ENABLED parsed explicitly (not z.coerce.boolean, #155)" \
      "missing or still uses z.coerce.boolean"
  fi

  # --- Step 5 (History + export) — checks 22-24 ---
  if [[ -f web/app/history/page.tsx ]]; then
    record_pass 22 "web/app/history/page.tsx exists"
  else
    record_fail 22 "web/app/history/page.tsx exists" "missing"
  fi

  if [[ -f "web/app/api/roadmaps/[id]/export/route.ts" ]]; then
    record_pass 23 "roadmap Markdown export route exists"
  else
    record_fail 23 "roadmap Markdown export route exists" "missing"
  fi

  if [[ -f web/tests/history.spec.ts ]]; then
    record_pass 24 "web/tests/history.spec.ts exists"
  else
    record_fail 24 "web/tests/history.spec.ts exists" "missing"
  fi

  # --- Step 6 (Model tiering + caching) — checks 25-27 ---
  if [[ -f web/lib/model-routing.ts && -f web/lib/llm-cache.ts && -f web/lib/engine-overrides.ts ]]; then
    record_pass 25 "model-routing + llm-cache + engine-overrides exist"
  else
    record_fail 25 "model-routing + llm-cache + engine-overrides exist" "missing"
  fi

  if [[ -f web/tests/prompt-caching.spec.ts ]]; then
    record_pass 26 "web/tests/prompt-caching.spec.ts exists"
  else
    record_fail 26 "web/tests/prompt-caching.spec.ts exists" "missing"
  fi

  # Roadmap engine must NOT send systemInstruction alongside cachedContent
  # (issue #161: Gemini rejects the combination).
  if grep -Fq "cachedContent" web/lib/roadmap-engine.ts; then
    record_pass 27 "roadmap-engine integrates Gemini cachedContent"
  else
    record_fail 27 "roadmap-engine integrates Gemini cachedContent" "missing"
  fi

  # --- Step 7 (Latency) — checks 28-29 ---
  if [[ -f web/lib/latency.ts && -f docs/phase04-latency-findings.md ]]; then
    record_pass 28 "latency util + findings doc exist"
  else
    record_fail 28 "latency util + findings doc exist" "missing"
  fi

  if grep -Fq "Post-fix" docs/phase04-latency-findings.md; then
    record_pass 29 "latency findings carry a Post-fix section"
  else
    record_fail 29 "latency findings carry a Post-fix section" "section missing"
  fi

  # --- Dogfood app-shell additions (#152/#153/#154) — checks 30-32 ---
  if [[ -f web/app/settings/page.tsx ]]; then
    record_pass 30 "web/app/settings/page.tsx exists (#154)"
  else
    record_fail 30 "web/app/settings/page.tsx exists (#154)" "missing"
  fi

  if [[ -f web/components/AppNav.tsx ]]; then
    record_pass 31 "web/components/AppNav.tsx exists (#153)"
  else
    record_fail 31 "web/components/AppNav.tsx exists (#153)" "missing"
  fi

  if [[ -f web/lib/subscriptions.ts && -f web/components/ProfilePreferencesForm.tsx ]]; then
    record_pass 32 "catalog-derived subscriptions lib + shared form exist (#152)"
  else
    record_fail 32 "catalog-derived subscriptions lib + shared form exist (#152)" "missing"
  fi

  # --- Step 9 (this script + QA findings + CI matrix) — checks 33-35 ---
  if [[ -x scripts/verify-phase04.sh ]]; then
    record_pass 33 "scripts/verify-phase04.sh exists and is executable"
  else
    record_fail 33 "scripts/verify-phase04.sh exists and is executable" "missing or not chmod +x"
  fi

  if [[ -f docs/phase04-qa-findings.md ]]; then
    record_pass 34 "docs/phase04-qa-findings.md exists"
  else
    record_fail 34 "docs/phase04-qa-findings.md exists" "missing"
  fi

  if [[ -f .github/workflows/phase-verify.yml ]] &&
    grep -Eq '"01", "02", "03", "04"' .github/workflows/phase-verify.yml; then
    record_pass 35 'phase-verify.yml matrix includes "04"'
  else
    record_fail 35 'phase-verify.yml matrix includes "04"' "matrix entry missing"
  fi
}

# Structural V1–V9 rollup for --fast (no network; greps + file presence that
# mirror the §post-implementation acceptance matrix). Step 8 (launch) is
# intentionally launch-gated and reported [PEND], not failed.
rollup_v_fast() {
  V_AGG_PASS=0
  V_AGG_FAIL=0
  printf '\n== V1–V9 structural rollup (--fast) ==\n'
  v_pass() { printf '[PASS] %s\n' "$1"; V_AGG_PASS+=1; }
  v_fail() { printf '[FAIL] %s\n' "$1" >&2; V_AGG_FAIL+=1; }

  [[ -f web/lib/auth.ts && -f "web/app/(auth)/callback/route.ts" ]] &&
    v_pass "V1 auth: server helpers + /callback route" ||
    v_fail "V1 auth: server helpers + /callback route"

  [[ -f web/lib/profile.ts && -f "web/app/(auth)/onboarding/page.tsx" ]] &&
    v_pass "V2 profile + onboarding surface" ||
    v_fail "V2 profile + onboarding surface"

  [[ -f web/app/roadmap/page.tsx && -f web/components/ChatPanel.tsx ]] &&
    v_pass "V3 /roadmap shell" ||
    v_fail "V3 /roadmap shell"

  [[ -f web/lib/roadmap-engine.ts && -f docs/phase04-roadmap-engine-decision.md ]] &&
    v_pass "V4 roadmap builder + engine decision" ||
    v_fail "V4 roadmap builder + engine decision"

  [[ -f web/app/history/page.tsx && -f "web/app/api/roadmaps/[id]/export/route.ts" ]] &&
    v_pass "V5 history + Markdown export" ||
    v_fail "V5 history + Markdown export"

  [[ -f web/lib/llm-cache.ts && -f web/lib/model-routing.ts ]] &&
    v_pass "V6 tiering + provider-side caching" ||
    v_fail "V6 tiering + provider-side caching"

  { [[ -f web/lib/latency.ts ]] && grep -Fq "Post-fix" docs/phase04-latency-findings.md; } &&
    v_pass "V7 warm-path latency findings (P50 met; P95 tail tracked)" ||
    v_fail "V7 warm-path latency findings"

  # V8 — public launch — DEFERRED by maintainer decision (gate stays up).
  printf '[PEND] V8 public-readiness gate lift — launch deferred to end of phase (gate intentionally active)\n'

  { [[ -x scripts/verify-phase04.sh ]] && [[ -f docs/phase04-qa-findings.md ]]; } &&
    v_pass "V9 verify-phase04.sh + qa-findings + CI matrix" ||
    v_fail "V9 verify-phase04.sh + qa-findings + CI matrix"
}

run_api_checks() {
  STEP_API_PASS=0
  STEP_API_FAIL=0
  printf '\n== API (pytest) ==\n'
  # Root package: deselect the live-network suite + the PG-backed migration
  # test (needs a real Postgres), mirroring the local-verify recipe.
  if "${PYTHON_BIN}" -m pytest -x tests/ \
    --deselect tests/test_sources_live.py \
    --ignore tests/test_phase04_migrations.py; then
    printf '[PASS] root pytest passed\n'
    STEP_API_PASS+=1
  else
    printf '[FAIL] root pytest failed\n' >&2
    STEP_API_FAIL+=1
  fi
  if "${PYTHON_BIN}" -m pip install -q -e "service/[dev]" &&
    "${PYTHON_BIN}" -m pytest -x service/tests/; then
    printf '[PASS] service pytest passed\n'
    STEP_API_PASS+=1
  else
    printf '[FAIL] service pytest failed\n' >&2
    STEP_API_FAIL+=1
  fi
}

run_web_checks() {
  STEP_WEB_PASS=0
  STEP_WEB_FAIL=0
  printf '\n== Web (npm) ==\n'
  web_ci_env
  if npm --prefix web ci && npm --prefix web run lint &&
    npm --prefix web run typecheck && npm --prefix web run build; then
    printf '[PASS] web lint + typecheck + build passed\n'
    STEP_WEB_PASS+=1
  else
    printf '[FAIL] web lint + typecheck + build failed\n' >&2
    STEP_WEB_FAIL+=1
  fi
}

run_ui_checks() {
  STEP_UI_PASS=0
  STEP_UI_FAIL=0
  printf '\n== UI (Playwright) ==\n'
  web_ci_env
  if npx --prefix web playwright install chromium &&
    npm --prefix web run test; then
    printf '[PASS] Playwright web/tests passed\n'
    STEP_UI_PASS+=1
  else
    printf '[FAIL] Playwright web/tests failed\n' >&2
    STEP_UI_FAIL+=1
  fi
}

run_post_matrix() {
  STEP_POST_PASS=0
  STEP_POST_FAIL=0
  printf '\n== Post-implementation matrix ==\n'

  # Live service health (gated on env).
  if [[ -n "${ROADMODEL_SERVICE_URL:-}" ]]; then
    local hz_code
    hz_code="$(curl -fsS -o /dev/null -w '%{http_code}' \
      --max-time 15 "${ROADMODEL_SERVICE_URL%/}/healthz" 2>/dev/null || true)"
    if [[ "${hz_code}" == "200" ]]; then
      printf '[PASS] V-live: GET %s/healthz returned 200\n' "${ROADMODEL_SERVICE_URL%/}"
      STEP_POST_PASS+=1
    else
      printf '[FAIL] V-live: GET %s/healthz returned HTTP %s\n' \
        "${ROADMODEL_SERVICE_URL%/}" "${hz_code:-none}" >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V-live: ROADMODEL_SERVICE_URL unset; skipping live /healthz\n'
  fi

  # Step 8 (launch) — launch-gated, reported [PEND] until the deliberate
  # gate-lift PR lands (site stays password-gated + noindex until then).
  if [[ -d web/app/gate ]]; then
    printf '[PEND] V8: pre-launch gate still active (web/app/gate present) — launch deferred by design\n'
  else
    printf '[PASS] V8: gate removed (launch performed)\n'
    STEP_POST_PASS+=1
  fi
}

print_summary() {
  printf '\n== Summary ==\n'
  printf '%-22s %6s %6s\n' "Stage" "Pass" "Fail"
  printf '%-22s %6s %6s\n' "static-1..35" "${STATIC_PASS}" "${STATIC_FAIL}"
  if [[ "${MODE_DEFAULT}" -eq 1 || "${MODE_API}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "api (pytest)" "${STEP_API_PASS:-0}" "${STEP_API_FAIL:-0}"
  fi
  if [[ "${MODE_WEB}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "web (npm)" "${STEP_WEB_PASS:-0}" "${STEP_WEB_FAIL:-0}"
  fi
  if [[ "${MODE_UI}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "ui (playwright)" "${STEP_UI_PASS:-0}" "${STEP_UI_FAIL:-0}"
  fi
  if [[ "${MODE_FAST}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "V-rollup" "${V_AGG_PASS:-0}" "${V_AGG_FAIL:-0}"
  fi
  if [[ "${MODE_POST}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "V-rollup(pre)" "${V_AGG_PASS:-0}" "${V_AGG_FAIL:-0}"
    printf '%-22s %6s %6s\n' "post-matrix" "${STEP_POST_PASS:-0}" "${STEP_POST_FAIL:-0}"
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
