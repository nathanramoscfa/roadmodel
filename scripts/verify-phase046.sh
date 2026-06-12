#!/usr/bin/env bash
# scripts/verify-phase046.sh
#
# Phase 4.6 (catalog-source federation) deliverable verification. Mirrors the
# verify-phaseNN.sh contract (record_pass/record_fail, summary table, --fast for
# CI). Covers T2-T6: the federation chassis (merge_catalog.py +
# validate_catalog_conformance.py), the six provider-direct catalog snapshots, the
# deepseek-api + mistral-api methods, the eu-jurisdiction win, the federation-aware
# cron prompt + deterministic price overlay, and the Mistral onboarding.
#
# Usage:
#   ./scripts/verify-phase046.sh           # static + pytest (federation + schema)
#   ./scripts/verify-phase046.sh --fast    # static checks only (CI; Ubuntu-safe, <30s)
#   ./scripts/verify-phase046.sh --all      # static + ruff + format + mypy + pytest
#   ./scripts/verify-phase046.sh --post    # static + conformance gate + pytest (CI post)
#
# Discipline: this script always names the selector by its qualified path
# (docs/model-selector.txt) so verify-phase01.sh's rename-sweep stays green.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-phase046.sh: not inside a git checkout" >&2
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

SELECTOR="docs/model-selector.txt"
COST_SCALE="docs/model-tier-cost-scale.md"
PROMPT="update/prompt.md"
WORKFLOW=".github/workflows/update-models.yml"
PROVIDERS=(anthropic openai google xai deepseek mistral)

MODE_FAST=0
MODE_ALL=0
MODE_POST=0
MODE_DEFAULT=0

if [[ $# -eq 0 ]]; then
  MODE_DEFAULT=1
else
  case "$1" in
    --fast) MODE_FAST=1 ;;
    --all) MODE_ALL=1 ;;
    --post) MODE_POST=1 ;;
    -h | --help)
      sed -n '1,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
fi

declare -i STATIC_PASS=0 STATIC_FAIL=0
declare -i LANE_PASS=0 LANE_FAIL=0
FAILED_CHECKS=()

record_pass() {
  STATIC_PASS+=1
  printf '[PASS] Check %s: %s\n' "$1" "$2"
}

record_fail() {
  STATIC_FAIL+=1
  FAILED_CHECKS+=("$1")
  printf '[FAIL] Check %s: %s — %s\n' "$1" "$2" "$3" >&2
}

# file_has <n> <desc> <path> <fixed-string>  — record pass iff the file exists
# and contains the fixed string (grep -F, no regex surprises).
file_has() {
  local n="$1" desc="$2" path="$3" needle="$4"
  if [[ -f "${path}" ]] && grep -Fq -- "${needle}" "${path}"; then
    record_pass "${n}" "${desc}"
  else
    record_fail "${n}" "${desc}" "missing file or string in ${path}: ${needle}"
  fi
}

run_static_checks() {
  STATIC_PASS=0
  STATIC_FAIL=0
  FAILED_CHECKS=()

  # 1 — federation compose/overlay engine (T2).
  if [[ -f update/merge_catalog.py ]]; then record_pass 1 "update/merge_catalog.py exists (compose + overlay engine)"
  else record_fail 1 "update/merge_catalog.py exists" "missing"; fi

  # 2 — offline conformance gate (T2/T3).
  if [[ -f update/validate_catalog_conformance.py ]]; then record_pass 2 "update/validate_catalog_conformance.py exists (G1-G4 gate)"
  else record_fail 2 "update/validate_catalog_conformance.py exists" "missing"; fi

  # 3 — all six provider-direct catalog snapshots present.
  local missing_snap=()
  local p
  for p in "${PROVIDERS[@]}"; do
    [[ -f "update/catalog-${p}.json" ]] || missing_snap+=("${p}")
  done
  if [[ ${#missing_snap[@]} -eq 0 ]]; then
    record_pass 3 "All 6 catalog snapshots exist (${PROVIDERS[*]})"
  else
    record_fail 3 "All 6 catalog snapshots exist" "missing: ${missing_snap[*]}"
  fi

  # 4 — a catalog source/extractor script per provider.
  local missing_ex=()
  for p in "${PROVIDERS[@]}"; do
    [[ -f "update/extract_${p}_catalog.py" ]] || missing_ex+=("${p}")
  done
  if [[ ${#missing_ex[@]} -eq 0 ]]; then
    record_pass 4 "A catalog source/extractor exists per provider"
  else
    record_fail 4 "A catalog source/extractor exists per provider" "missing: ${missing_ex[*]}"
  fi

  # 5 — G4 price-provenance check in the gate (T3).
  file_has 5 "G4 price-provenance check present in the gate" \
    update/validate_catalog_conformance.py "check_price_provenance"

  # 6 — deterministic price overlay (selector + cost-scale) in the engine (T4 backstop).
  file_has 6 "Selector price overlay present (T4 backstop)" \
    update/merge_catalog.py "def apply_price_overlay"
  file_has 7 "Cost-scale price overlay present (T4 backstop)" \
    update/merge_catalog.py "def apply_cost_scale_price_overlay"

  # 8 — federation-aware cron prompt (T4): provider-direct prices are not re-derived.
  file_has 8 "Cron prompt carries the federation provider-direct price rule (T4)" \
    "${PROMPT}" "Federation — provider-direct prices"

  # 9 — deepseek-api method (T2 wiring).
  file_has 9 "deepseek-api method present in the selector" \
    "${SELECTOR}" 'id="deepseek-api"'

  # 10 — mistral-api method (T5).
  file_has 10 "mistral-api method present in the selector" \
    "${SELECTOR}" 'id="mistral-api"'

  # 11 — the eu-jurisdiction win: at least one eu model + the eu method.
  if grep -Eq 'jurisdiction="eu"' "${SELECTOR}" && grep -Fq 'provider-jurisdiction="eu"' "${SELECTOR}"; then
    record_pass 11 "eu jurisdiction is recommendable (>=1 eu model + an eu-operator method)"
  else
    record_fail 11 "eu jurisdiction is recommendable" "no eu model and/or no eu method in the selector"
  fi

  # 12 — Mistral models in the registry (T5).
  file_has 12 "Mistral models present in the selector (mistral-medium-3.5)" \
    "${SELECTOR}" 'id="mistral-medium-3.5"'

  # 13 — DeepSeek models in the registry (T2 wiring).
  file_has 13 "DeepSeek models present in the selector (deepseek-v4-pro)" \
    "${SELECTOR}" 'id="deepseek-v4-pro"'

  # 14 — reasoning dials documented for the new providers.
  if grep -Fq "DeepSeek (DeepSeek API)" "${SELECTOR}" && grep -Fq "Mistral (Mistral API" "${SELECTOR}"; then
    record_pass 14 "thinking-context documents the DeepSeek + Mistral reasoning dials"
  else
    record_fail 14 "thinking-context documents the DeepSeek + Mistral reasoning dials" "a provider bullet is missing"
  fi

  # 15 — Mistral catalog is manually maintained + its extractor is a drift-checker (T5 source decision).
  file_has 15 "Mistral catalog snapshot is manually maintained (no auto price parse)" \
    update/catalog-mistral.json '"price_maintenance": "manual"'

  # 16 — cron is federation-aware: overlay step + provider-direct snapshot refresh.
  file_has 16 "Cron re-applies the federation overlay after the Opus refresh" \
    "${WORKFLOW}" "merge_catalog.py --write"

  # 17 — the federation test suite exists.
  if [[ -f tests/test_catalog_federation.py ]]; then record_pass 17 "tests/test_catalog_federation.py exists"
  else record_fail 17 "tests/test_catalog_federation.py exists" "missing"; fi

  # 18 — overlay_mode declared on every snapshot (whole-element | price-only).
  local bad_overlay=()
  for p in "${PROVIDERS[@]}"; do
    grep -Fq '"overlay_mode"' "update/catalog-${p}.json" 2>/dev/null || bad_overlay+=("${p}")
  done
  if [[ ${#bad_overlay[@]} -eq 0 ]]; then
    record_pass 18 "Every snapshot declares overlay_mode"
  else
    record_fail 18 "Every snapshot declares overlay_mode" "missing on: ${bad_overlay[*]}"
  fi

  # 19 — key update scripts compile.
  if "${PYTHON_BIN}" -m py_compile \
    update/merge_catalog.py \
    update/validate_catalog_conformance.py \
    update/extract_mistral_catalog.py 2>/dev/null; then
    record_pass 19 "Federation update scripts compile"
  else
    record_fail 19 "Federation update scripts compile" "py_compile failed"
  fi

  # 20 — QA findings doc present (this step's rollup).
  if [[ -f docs/phase046-qa-findings.md ]]; then record_pass 20 "docs/phase046-qa-findings.md exists"
  else record_fail 20 "docs/phase046-qa-findings.md exists" "missing"; fi
}

run_lanes() {
  LANE_PASS=0
  LANE_FAIL=0
  printf '\n-- rmverify lanes --\n'

  if "${PYTHON_BIN}" update/validate_catalog_conformance.py; then
    printf '[PASS] Lane: conformance gate (G1-G4)\n'
    LANE_PASS+=1
  else
    printf '[FAIL] Lane: conformance gate (G1-G4)\n' >&2
    LANE_FAIL+=1
  fi

  if "${PYTHON_BIN}" -m pytest -q tests/test_catalog_federation.py tests/test_doc_schema.py tests/test_catalog_json.py; then
    printf '[PASS] Lane: pytest (federation + schema + catalog)\n'
    LANE_PASS+=1
  else
    printf '[FAIL] Lane: pytest (federation + schema + catalog)\n' >&2
    LANE_FAIL+=1
  fi

  if [[ "${MODE_ALL}" -eq 1 ]]; then
    if "${PYTHON_BIN}" -m ruff check --no-cache src tests update &&
      "${PYTHON_BIN}" -m ruff format --check src tests update &&
      "${PYTHON_BIN}" -m mypy --strict src update; then
      printf '[PASS] Lane: ruff + format + mypy\n'
      LANE_PASS+=1
    else
      printf '[FAIL] Lane: ruff + format + mypy\n' >&2
      LANE_FAIL+=1
    fi
  fi
}

run_pytest_only() {
  LANE_PASS=0
  LANE_FAIL=0
  if "${PYTHON_BIN}" -m pytest -q tests/test_catalog_federation.py; then
    LANE_PASS+=1
  else
    LANE_FAIL+=1
  fi
}

print_summary() {
  printf '\n== Summary ==\n'
  printf '%-22s %6s %6s\n' "Stage" "Pass" "Fail"
  printf '%-22s %6s %6s\n' "static-1..20" "${STATIC_PASS}" "${STATIC_FAIL}"
  if [[ "${MODE_DEFAULT}" -eq 1 || "${MODE_ALL}" -eq 1 || "${MODE_POST}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "lanes" "${LANE_PASS}" "${LANE_FAIL}"
  fi
  if [[ ${#FAILED_CHECKS[@]} -gt 0 ]]; then
    printf 'Failed static checks: %s\n' "${FAILED_CHECKS[*]}" >&2
  fi
}

# --- main flow ---
run_static_checks

if [[ "${STATIC_FAIL}" -gt 0 ]]; then
  print_summary
  exit 1
fi

if [[ "${MODE_FAST}" -eq 1 ]]; then
  print_summary
  exit 0
fi

if [[ "${MODE_DEFAULT}" -eq 1 ]]; then
  run_pytest_only
  print_summary
  [[ "${LANE_FAIL}" -gt 0 ]] && exit 1
  exit 0
fi

# --all / --post: static + the lanes.
run_lanes
print_summary
[[ "${LANE_FAIL}" -gt 0 ]] && exit 1
exit 0
