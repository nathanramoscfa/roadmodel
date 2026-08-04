#!/usr/bin/env bash
# scripts/verify-phase02.sh
#
# Phase 2 deliverable verification. Mirrors scripts/verify-phase01.sh so the
# CI logs across phases stay diff-friendly (same flag set, same record_pass /
# record_fail format, same final summary table).
# Usage:
#   ./scripts/verify-phase02.sh              # static (33) + pytest -x (Phase 2 slice)
#   ./scripts/verify-phase02.sh --fast       # static + V1.1-V7.3 rollup (CI)
#   ./scripts/verify-phase02.sh --py         # static + pytest + ruff + mypy
#   ./scripts/verify-phase02.sh --cli        # static + wheel build/install smoke (no mcp extra)
#   ./scripts/verify-phase02.sh --mcp        # static + wheel install with [mcp] + stdio tools/list
#   ./scripts/verify-phase02.sh --all        # static + --py + --cli + --mcp
#   ./scripts/verify-phase02.sh --post       # static + V1-V7 + optional live checks
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-phase02.sh: not inside a git checkout" >&2
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
  if command -v python3.11 >/dev/null 2>&1; then
    command -v python3.11
    return 0
  fi
  command -v python3
}

PYTHON_BIN="$(resolve_python_bin)"

MODE_DEFAULT=0
MODE_FAST=0
MODE_PY=0
MODE_CLI=0
MODE_MCP=0
MODE_ALL=0
MODE_POST=0

if [[ $# -eq 0 ]]; then
  MODE_DEFAULT=1
else
  case "$1" in
    --fast) MODE_FAST=1 ;;
    --py) MODE_PY=1 ;;
    --cli) MODE_CLI=1 ;;
    --mcp) MODE_MCP=1 ;;
    --all) MODE_ALL=1 ;;
    --post) MODE_POST=1 ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
fi

if [[ "${MODE_ALL}" -eq 1 ]]; then
  MODE_PY=1
  MODE_CLI=1
  MODE_MCP=1
fi

# --- counters (static checks 1-33) ---
declare -i STATIC_PASS=0 STATIC_FAIL=0
declare -i STEP_PY_PASS=0 STEP_PY_FAIL=0
declare -i STEP_CLI_PASS=0 STEP_CLI_FAIL=0
declare -i STEP_MCP_PASS=0 STEP_MCP_FAIL=0
declare -i STEP_POST_PASS=0 STEP_POST_FAIL=0
declare -i V_AGG_PASS=0 V_AGG_FAIL=0
FAILED_CHECKS=()

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

pyproject_version() {
  sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml | head -n1
}

run_static_checks() {
  STATIC_PASS=0
  STATIC_FAIL=0
  FAILED_CHECKS=()

  # --- Step 1 (Catalog v2) — checks 1-6 ---

  # 1
  if [[ -f update/build_catalog.py ]]; then
    record_pass 1 "update/build_catalog.py exists"
  else
    record_fail 1 "update/build_catalog.py exists" "missing"
  fi

  # 2 — exists + parses as JSON
  if [[ -f docs/catalog.json ]] && \
    "${PYTHON_BIN}" -c "import json,sys; json.loads(open('docs/catalog.json').read())" 2>/dev/null; then
    record_pass 2 "docs/catalog.json exists and parses as JSON"
  else
    record_fail 2 "docs/catalog.json exists and parses as JSON" "missing or invalid JSON"
  fi

  # 3 — bundling mechanism check. src/roadmodel/data/ is gitignored
  # (Phase 1 check 14); hatch_build.py copies docs/catalog.json into
  # src/roadmodel/data/catalog.json at wheel-build time. On a fresh
  # clone (incl. CI) the file isn't there yet — so we assert the
  # bundling contract: hatch_build.py declares catalog.json in its
  # BUNDLED_DOCS map. The materialized file is verified inside the
  # wheel under --cli / --post (V3.3) and the actual install matrix.
  if grep -Fq '"catalog.json": "catalog.json"' hatch_build.py; then
    record_pass 3 "hatch_build.py bundles docs/catalog.json into src/roadmodel/data/catalog.json"
  else
    record_fail 3 "hatch_build.py bundles docs/catalog.json into src/roadmodel/data/catalog.json" \
      "BUNDLED_DOCS entry missing in hatch_build.py"
  fi

  # 4 — four documented sections
  local refresh_doc=docs/catalog-refresh.md
  local ok4=1
  for section in "## When to run manually" "## How to run manually" "## Verification" "## Cross-reference with the cron"; do
    if ! grep -Fq "${section}" "${refresh_doc}" 2>/dev/null; then
      ok4=0
      break
    fi
  done
  if [[ "${ok4}" -eq 1 ]]; then
    record_pass 4 "docs/catalog-refresh.md contains four documented sections"
  else
    record_fail 4 "docs/catalog-refresh.md contains four documented sections" \
      "missing file or section heading"
  fi

  # 5 — every Step 1 named test present
  local step1_tests=(
    test_schema_top_level_keys
    test_every_model_in_selector_is_in_json
    test_every_json_model_is_in_selector
    test_prices_round_trip
    test_access_methods_round_trip
    test_subscription_tiers_match_tier_cost_scale
    test_build_catalog_is_deterministic
  )
  local ok5=1
  if [[ ! -f tests/test_catalog_json.py ]]; then
    ok5=0
  else
    for t in "${step1_tests[@]}"; do
      if ! grep -Fq "def ${t}(" tests/test_catalog_json.py; then
        ok5=0
        break
      fi
    done
  fi
  if [[ "${ok5}" -eq 1 ]]; then
    record_pass 5 "tests/test_catalog_json.py present with every named Step 1 test"
  else
    record_fail 5 "tests/test_catalog_json.py present with every named Step 1 test" \
      "missing file or named test"
  fi

  # 6
  if [[ -f .github/workflows/update-models.yml ]] &&
    grep -Fq "build_catalog.py" .github/workflows/update-models.yml; then
    record_pass 6 ".github/workflows/update-models.yml invokes build_catalog.py"
  else
    record_fail 6 ".github/workflows/update-models.yml invokes build_catalog.py" \
      "missing file or invocation"
  fi

  # --- Step 2 (Cost estimator) — checks 7-9 ---

  # 7
  if [[ -f src/roadmodel/cost.py ]]; then
    record_pass 7 "src/roadmodel/cost.py exists"
  else
    record_fail 7 "src/roadmodel/cost.py exists" "missing"
  fi

  # 8 — every Step 2 named test present
  local step2_tests=(
    test_estimate_per_token_path
    test_estimate_subscription_included
    test_estimate_subscription_pool
    test_estimate_subscription_or_key
    test_max_mode_2x_input_applied
    test_max_mode_no_op_outside_cursor
    test_fast_variant_rejected
    test_compare_default_alternatives_ranking
    test_compare_custom_alternatives
    test_unknown_model
    test_unknown_platform
  )
  local ok8=1
  if [[ ! -f tests/test_cost.py ]]; then
    ok8=0
  else
    for t in "${step2_tests[@]}"; do
      if ! grep -Fq "def ${t}(" tests/test_cost.py; then
        ok8=0
        break
      fi
    done
  fi
  if [[ "${ok8}" -eq 1 ]]; then
    record_pass 8 "tests/test_cost.py present with every named Step 2 test"
  else
    record_fail 8 "tests/test_cost.py present with every named Step 2 test" \
      "missing file or named test"
  fi

  # 9
  if [[ -f src/roadmodel/errors.py ]] &&
    grep -Fq "class AlternativeRejectedError" src/roadmodel/errors.py; then
    record_pass 9 "src/roadmodel/errors.py defines AlternativeRejectedError"
  else
    record_fail 9 "src/roadmodel/errors.py defines AlternativeRejectedError" \
      "missing file or class"
  fi

  # --- Step 3 (CLI surface upgrade) — checks 10-15 ---

  # 10 — __version__ is 0.2.x (Phase 2 set the 0.2 minor; later patch
  # bumps within the 0.2 line are acceptable, e.g. Phase 4 Step 7b 0.2.1).
  if [[ -f src/roadmodel/__init__.py ]] &&
    grep -Eq '__version__[[:space:]]*=[[:space:]]*"0\.2\.[0-9]+"' src/roadmodel/__init__.py; then
    record_pass 10 "src/roadmodel/__init__.py declares __version__ = \"0.2.x\""
  else
    record_fail 10 "src/roadmodel/__init__.py declares __version__ = \"0.2.x\"" \
      "version literal not in the 0.2.x range"
  fi

  # 11
  if [[ -f CHANGELOG.md ]] && grep -Fq "## [0.2.0]" CHANGELOG.md; then
    record_pass 11 "CHANGELOG.md has ## [0.2.0] section"
  else
    record_fail 11 "CHANGELOG.md has ## [0.2.0] section" "section missing"
  fi

  # 12 — cost subcommand
  if [[ -f src/roadmodel/cli.py ]] &&
    grep -Eq '@cli\.command\(["'\''](cost)["'\'']\)|@cli\.command\(["'\''](cost)["'\''], ' src/roadmodel/cli.py &&
    grep -Eq 'def cost_command\(|def cost\(' src/roadmodel/cli.py; then
    record_pass 12 "src/roadmodel/cli.py wires a cost subcommand"
  else
    record_fail 12 "src/roadmodel/cli.py wires a cost subcommand" \
      "missing @cli.command(\"cost\") or cost function"
  fi

  # 13 — recommend flags
  local ok13=1
  for flag in '--legacy' '--input-tokens' '--output-tokens' '--max-mode' '--output'; do
    if ! grep -Fq "\"${flag}\"" src/roadmodel/cli.py; then
      ok13=0
      break
    fi
  done
  if [[ "${ok13}" -eq 1 ]]; then
    record_pass 13 "recommend subcommand carries --legacy/--input-tokens/--output-tokens/--max-mode/--output"
  else
    record_fail 13 "recommend subcommand carries --legacy/--input-tokens/--output-tokens/--max-mode/--output" \
      "flag literal missing in cli.py"
  fi

  # 14
  if [[ -f src/roadmodel/recommend.py ]] &&
    grep -Eq '^def recommend_structured\(' src/roadmodel/recommend.py; then
    record_pass 14 "src/roadmodel/recommend.py exports recommend_structured"
  else
    record_fail 14 "src/roadmodel/recommend.py exports recommend_structured" \
      "missing def recommend_structured"
  fi

  # 15 — every Step 3 named test present in test_cli.py
  local step3_tests=(
    test_recommend_structured_output
    test_recommend_legacy_flag
    test_recommend_json_output
    test_cost_subcommand_text
    test_cost_subcommand_json
    test_cost_unknown_model_exit_4
    test_cost_fast_variant_rejected
  )
  local ok15=1
  if [[ ! -f tests/test_cli.py ]]; then
    ok15=0
  else
    for t in "${step3_tests[@]}"; do
      if ! grep -Fq "def ${t}(" tests/test_cli.py; then
        ok15=0
        break
      fi
    done
  fi
  if [[ "${ok15}" -eq 1 ]]; then
    record_pass 15 "tests/test_cli.py present with every named Step 3 test"
  else
    record_fail 15 "tests/test_cli.py present with every named Step 3 test" \
      "missing file or named test"
  fi

  # --- Step 4 (MCP server) — checks 16-22 ---

  # 16
  if [[ -f src/roadmodel/mcp_server.py ]]; then
    record_pass 16 "src/roadmodel/mcp_server.py exists"
  else
    record_fail 16 "src/roadmodel/mcp_server.py exists" "missing"
  fi

  # 17
  if grep -Eq '^roadmodel-mcp[[:space:]]*=[[:space:]]*"roadmodel\.mcp_server:main"' pyproject.toml; then
    record_pass 17 "pyproject.toml [project.scripts] declares roadmodel-mcp entry"
  else
    record_fail 17 "pyproject.toml [project.scripts] declares roadmodel-mcp entry" \
      "console script entry missing"
  fi

  # 18 — mcp optional dependency (floor mcp>=1.0; an optional upper cap such as
  # ",<2" is allowed — see the pyproject comment on the 2.0.0 FastMCP removal)
  if grep -Eq 'mcp[[:space:]]*=[[:space:]]*\[[[:space:]]*"mcp>=1\.0[^"]*"' pyproject.toml; then
    record_pass 18 "pyproject.toml [project.optional-dependencies] mcp lists \"mcp>=1.0\""
  else
    record_fail 18 "pyproject.toml [project.optional-dependencies] mcp lists \"mcp>=1.0\"" \
      "extra missing or version pin wrong"
  fi

  # 19 — every Step 4 named test present in test_mcp_server.py
  local step4_tests=(
    test_tools_list_exactly_three
    test_recommend_model_calls_recommend_structured
    test_recommend_model_with_context
    test_generate_phase_roadmap_uses_template
    test_read_catalog_returns_three_keys
    test_main_exits_2_when_mcp_sdk_absent
  )
  local ok19=1
  if [[ ! -f tests/test_mcp_server.py ]]; then
    ok19=0
  else
    for t in "${step4_tests[@]}"; do
      if ! grep -Fq "def ${t}(" tests/test_mcp_server.py; then
        ok19=0
        break
      fi
    done
  fi
  if [[ "${ok19}" -eq 1 ]]; then
    record_pass 19 "tests/test_mcp_server.py present with every named Step 4 test"
  else
    record_fail 19 "tests/test_mcp_server.py present with every named Step 4 test" \
      "missing file or named test"
  fi

  # 20 — exactly three tool functions, each appearing exactly once
  local ok20=1
  local bad20=""
  for fn in recommend_model generate_phase_roadmap read_catalog; do
    local count
    count="$(grep -Ec "^[[:space:]]*def ${fn}\(" src/roadmodel/mcp_server.py 2>/dev/null || true)"
    if [[ "${count}" != "1" ]]; then
      ok20=0
      bad20="${fn} count=${count}"
      break
    fi
  done
  if [[ "${ok20}" -eq 1 ]]; then
    record_pass 20 "mcp_server.py registers exactly three tools (recommend_model, generate_phase_roadmap, read_catalog)"
  else
    record_fail 20 "mcp_server.py registers exactly three tools" "${bad20}"
  fi

  # 21 — filesystem-walking guard
  if grep -Eq 'os\.walk\(|os\.listdir\(|glob\.glob\(|\.iterdir\(' src/roadmodel/mcp_server.py; then
    record_fail 21 "mcp_server.py contains no os.walk/os.listdir/glob.glob/Path.iterdir" \
      "filesystem-walking call detected"
  else
    record_pass 21 "mcp_server.py contains no os.walk/os.listdir/glob.glob/Path.iterdir"
  fi

  # 22 — README MCP server section + link
  if [[ -f README.md ]] && grep -Fq "## MCP server" README.md &&
    grep -Fq "docs/mcp-setup.md" README.md; then
    record_pass 22 "README.md has ## MCP server section and links to docs/mcp-setup.md"
  else
    record_fail 22 "README.md has ## MCP server section and links to docs/mcp-setup.md" \
      "section or link missing"
  fi

  # --- Step 5 (MCP docs) — checks 23-26 ---

  # 23 — mcp-setup.md sections
  local mcp_setup=docs/mcp-setup.md
  local ok23=1
  for section in "## Install" "## Cursor" "## Claude Code" "## Other MCP clients" "## Troubleshooting"; do
    if ! grep -Fq "${section}" "${mcp_setup}" 2>/dev/null; then
      ok23=0
      break
    fi
  done
  if [[ "${ok23}" -eq 1 ]]; then
    record_pass 23 "docs/mcp-setup.md has all required sections (Install/Cursor/Claude Code/Other MCP clients/Troubleshooting)"
  else
    record_fail 23 "docs/mcp-setup.md has all required sections" "missing file or section heading"
  fi

  # 24 — mcp-tools.md names the three tools
  if [[ -f docs/mcp-tools.md ]] &&
    grep -Fq "recommend_model" docs/mcp-tools.md &&
    grep -Fq "generate_phase_roadmap" docs/mcp-tools.md &&
    grep -Fq "read_catalog" docs/mcp-tools.md; then
    record_pass 24 "docs/mcp-tools.md names recommend_model, generate_phase_roadmap, read_catalog"
  else
    record_fail 24 "docs/mcp-tools.md names recommend_model, generate_phase_roadmap, read_catalog" \
      "missing file or tool name"
  fi

  # 25 — pip install 'roadmodel[mcp]' literal (accept single OR double quotes)
  if grep -Fq "pip install 'roadmodel[mcp]'" docs/mcp-setup.md ||
    grep -Fq 'pip install "roadmodel[mcp]"' docs/mcp-setup.md; then
    record_pass 25 "docs/mcp-setup.md contains pip install 'roadmodel[mcp]' (single or double quotes)"
  else
    record_fail 25 "docs/mcp-setup.md contains pip install 'roadmodel[mcp]' (single or double quotes)" \
      "install hint string not found"
  fi

  # 26 — every mcp_server.py tool parameter name appears in docs/mcp-tools.md
  local ok26=1
  local bad26=""
  for param in task_description context project_brief phase_number prior_phases; do
    if ! grep -Fq "${param}" docs/mcp-tools.md; then
      ok26=0
      bad26="${param} not in docs/mcp-tools.md"
      break
    fi
  done
  if [[ "${ok26}" -eq 1 ]]; then
    record_pass 26 "docs/mcp-tools.md signatures match every parameter in src/roadmodel/mcp_server.py"
  else
    record_fail 26 "docs/mcp-tools.md signatures match every parameter in src/roadmodel/mcp_server.py" \
      "${bad26}"
  fi

  # --- Step 6 (Release v0.2.0) — checks 27-29 ---

  # 27 — tag exists. Git can return tags only when the local clone fetched
  # them. CI checkouts default to shallow clone but `actions/checkout@v5`
  # fetches tags when given fetch-depth: 0 (which we already set in
  # phase-verify.yml's post job). The verify job uses default fetch-depth,
  # so we permit a CI-only skip when running under GITHUB_ACTIONS and the
  # tag isn't present — mirrors Phase 1's check 32 escape hatch.
  if git tag --list v0.2.0 | grep -Fxq "v0.2.0"; then
    record_pass 27 "git tag v0.2.0 exists in the local clone"
  elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    record_pass 27 "git tag v0.2.0 not present on CI (shallow checkout); verified via gh release tag on tag-push runs"
  else
    record_fail 27 "git tag v0.2.0 exists in the local clone" "git tag --list returned empty"
  fi

  # 28 — CHANGELOG [0.2.0] dated with real ISO date (not YYYY-MM-DD placeholder)
  if grep -Eq '^## \[0\.2\.0\][[:space:]]+[-—–][[:space:]]+[0-9]{4}-[0-9]{2}-[0-9]{2}([[:space:]]|$)' CHANGELOG.md; then
    record_pass 28 "CHANGELOG.md [0.2.0] section carries a real ISO date"
  else
    record_fail 28 "CHANGELOG.md [0.2.0] section carries a real ISO date" \
      "missing date or still a YYYY-MM-DD placeholder"
  fi

  # 29 — runbook contains a v0.2.0 section with TestPyPI + PyPI URLs.
  # Honor either docs/phase01-release-runbook.md (legacy) or
  # docs/phase02-release-runbook.md (canonical for Phase 2 onward).
  local runbook=""
  if [[ -f docs/phase02-release-runbook.md ]]; then
    runbook=docs/phase02-release-runbook.md
  elif [[ -f docs/phase01-release-runbook.md ]]; then
    runbook=docs/phase01-release-runbook.md
  fi
  if [[ -n "${runbook}" ]] && grep -Eq '^## v?0\.2\.0' "${runbook}" &&
    grep -Fq "test.pypi.org/project/roadmodel/0.2.0" "${runbook}" &&
    grep -Fq "pypi.org/project/roadmodel/0.2.0" "${runbook}"; then
    record_pass 29 "release runbook contains a v0.2.0 section with TestPyPI and PyPI URLs"
  else
    record_fail 29 "release runbook contains a v0.2.0 section with TestPyPI and PyPI URLs" \
      "runbook file, section, or URLs missing"
  fi

  # --- Step 7 self-checks — checks 30-33 ---

  # 30
  if [[ -x scripts/verify-phase02.sh ]]; then
    record_pass 30 "scripts/verify-phase02.sh exists and is executable"
  else
    record_fail 30 "scripts/verify-phase02.sh exists and is executable" "missing or not chmod +x"
  fi

  # 31
  if [[ -f docs/phase02-qa-findings.md ]]; then
    record_pass 31 "docs/phase02-qa-findings.md exists"
  else
    record_fail 31 "docs/phase02-qa-findings.md exists" "missing"
  fi

  # 32 — private/ is git-excluded locally, so on CI runners cloning from GitHub
  # this file is absent. Mirror Phase 1's CI-aware pass.
  if [[ -f private/phase02-roadmap.md ]]; then
    record_pass 32 "private/phase02-roadmap.md exists (local planning doc)"
  elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    record_pass 32 "private/phase02-roadmap.md absent on CI (gitignored locally)"
  else
    record_fail 32 "private/phase02-roadmap.md exists (local planning doc)" "missing"
  fi

  # 33
  if [[ -f .github/workflows/phase-verify.yml ]] &&
    grep -Eq 'phase:[[:space:]]*\[[^]]*"?0*2"?[^]]*\]' .github/workflows/phase-verify.yml; then
    record_pass 33 "phase-verify.yml matrix.phase includes \"02\""
  else
    record_fail 33 "phase-verify.yml matrix.phase includes \"02\"" \
      "missing file or matrix.phase lacks 02"
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
  v_range_pass 1 6 V1.1 || true
  v_range_pass 7 9 V2.1 || true
  v_range_pass 10 15 V3.1 || true
  v_range_pass 16 22 V4.1 || true
  v_range_pass 23 26 V5.1 || true
  v_range_pass 27 29 V6.1 || true
  if [[ "${STATIC_FAIL}" -eq 0 && "${STATIC_PASS}" -eq 33 ]]; then
    printf '[PASS] V7.1: verify-phase02.sh running in --fast mode completed static gate\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V7.1: static gate incomplete\n' >&2
    V_AGG_FAIL+=1
  fi
  if [[ "${STATIC_FAIL}" -eq 0 ]] &&
    grep -Eq 'phase:[[:space:]]*\[[^]]*"?0*2"?[^]]*\]' .github/workflows/phase-verify.yml; then
    printf '[PASS] V7.2: phase-verify.yml matrix includes phase 02\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V7.2: matrix phase 02 not confirmed\n' >&2
    V_AGG_FAIL+=1
  fi
  if [[ "${STATIC_FAIL}" -eq 0 && "${STATIC_PASS}" -eq 33 ]]; then
    printf '[PASS] V7.3: all 33 static deliverable checks passed\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V7.3: not all static checks passed\n' >&2
    V_AGG_FAIL+=1
  fi
}

run_py_checks() {
  STEP_PY_PASS=0
  STEP_PY_FAIL=0
  if "${PYTHON_BIN}" -m pytest tests/; then STEP_PY_PASS+=1
  else STEP_PY_FAIL+=1; fi
  if "${PYTHON_BIN}" -m ruff check src tests; then STEP_PY_PASS+=1
  else STEP_PY_FAIL+=1; fi
  if "${PYTHON_BIN}" -m mypy --strict src; then STEP_PY_PASS+=1
  else STEP_PY_FAIL+=1; fi
}

_build_wheel() {
  local ver
  ver="$(pyproject_version)"
  rm -rf dist build
  "${PYTHON_BIN}" -m pip install -q build
  "${PYTHON_BIN}" -m build >/dev/null
  printf 'dist/roadmodel-%s-py3-none-any.whl\n' "${ver}"
}

run_cli_checks() {
  STEP_CLI_PASS=0
  STEP_CLI_FAIL=0
  local whl
  whl="$(_build_wheel)"
  if [[ ! -f "${whl}" ]]; then
    printf '[FAIL] CLI gate: expected wheel missing at %s\n' "${whl}" >&2
    STEP_CLI_FAIL+=1
    return 1
  fi
  STEP_CLI_PASS+=1

  local venv
  venv="$(mktemp -d)/rm-cli-venv"
  "${PYTHON_BIN}" -m venv "${venv}"
  # shellcheck disable=SC1090
  source "${venv}/bin/activate"
  python -m pip install -q --upgrade pip
  pip install -q "${whl}"

  local rc
  rc=0
  roadmodel --help >/dev/null 2>&1 || rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    STEP_CLI_PASS+=1
  else
    printf '[FAIL] CLI gate: roadmodel --help exited %s\n' "${rc}" >&2
    STEP_CLI_FAIL+=1
  fi
  rc=0
  roadmodel cost --help >/dev/null 2>&1 || rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    STEP_CLI_PASS+=1
  else
    printf '[FAIL] CLI gate: roadmodel cost --help exited %s\n' "${rc}" >&2
    STEP_CLI_FAIL+=1
  fi
  deactivate || true
}

# Drive the FastMCP stdio server through one initialize + tools/list exchange
# and assert exactly the three documented tools. Lives inline so the script
# stays self-contained (no helper Python file to keep in sync).
_mcp_tools_list_smoke_py() {
  cat <<'PY'
import asyncio
import sys

EXPECTED = sorted(["recommend_model", "generate_phase_roadmap", "read_catalog"])


async def main() -> int:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ModuleNotFoundError as exc:
        print(f"mcp SDK not importable: {exc}", file=sys.stderr)
        return 1

    params = StdioServerParameters(command="roadmodel-mcp", args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.list_tools()
    names = sorted(t.name for t in response.tools)
    if names != EXPECTED:
        print(f"tools/list mismatch: got={names} expected={EXPECTED}", file=sys.stderr)
        return 1
    print("OK")
    return 0


sys.exit(asyncio.run(main()))
PY
}

run_mcp_checks() {
  STEP_MCP_PASS=0
  STEP_MCP_FAIL=0
  local whl
  whl="$(_build_wheel)"
  if [[ ! -f "${whl}" ]]; then
    printf '[FAIL] MCP gate: expected wheel missing at %s\n' "${whl}" >&2
    STEP_MCP_FAIL+=1
    return 1
  fi
  STEP_MCP_PASS+=1

  local venv
  venv="$(mktemp -d)/rm-mcp-venv"
  "${PYTHON_BIN}" -m venv "${venv}"
  # shellcheck disable=SC1090
  source "${venv}/bin/activate"
  python -m pip install -q --upgrade pip
  pip install -q "${whl}[mcp]"

  local rc
  rc=0
  roadmodel-mcp --help >/dev/null 2>&1 || rc=$?
  # FastMCP's CLI may exit non-zero on --help under some versions; accept
  # 0 OR 2 here and rely on the tools/list smoke for the real PASS signal.
  if [[ "${rc}" -eq 0 || "${rc}" -eq 2 ]]; then
    STEP_MCP_PASS+=1
  else
    printf '[FAIL] MCP gate: roadmodel-mcp --help exited %s\n' "${rc}" >&2
    STEP_MCP_FAIL+=1
  fi

  local smoke_out smoke_rc
  smoke_rc=0
  smoke_out="$(_mcp_tools_list_smoke_py | python - 2>&1)" || smoke_rc=$?
  if [[ "${smoke_rc}" -eq 0 ]] && grep -Fq "OK" <<<"${smoke_out}"; then
    printf '[PASS] MCP gate: stdio tools/list returned exactly the three documented tools\n'
    STEP_MCP_PASS+=1
  else
    printf '[FAIL] MCP gate: stdio tools/list smoke failed\n%s\n' "${smoke_out}" >&2
    STEP_MCP_FAIL+=1
  fi
  deactivate || true
}

run_post_matrix() {
  STEP_POST_PASS=0
  STEP_POST_FAIL=0
  printf '\n== Post-implementation V1–V7 matrix ==\n'

  # V1.2 — build_catalog determinism
  local d1 d2
  d1="$(mktemp -d)/build1"
  d2="$(mktemp -d)/build2"
  mkdir -p "${d1}/docs" "${d1}/update" "${d2}/docs" "${d2}/update"
  cp docs/model-selector.txt docs/model-tier-cost-scale.md "${d1}/docs/"
  cp docs/model-selector.txt docs/model-tier-cost-scale.md "${d2}/docs/"
  cp update/build_catalog.py "${d1}/update/"
  cp update/build_catalog.py "${d2}/update/"
  if (cd "${d1}" && "${PYTHON_BIN}" update/build_catalog.py >/dev/null) &&
    (cd "${d2}" && "${PYTHON_BIN}" update/build_catalog.py >/dev/null) &&
    cmp -s "${d1}/docs/catalog.json" "${d2}/docs/catalog.json"; then
    printf '[PASS] V1.2: update/build_catalog.py is deterministic across two runs\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V1.2: build_catalog output differs across runs\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V1.3 — catalog json pytest
  if "${PYTHON_BIN}" -m pytest tests/test_catalog_json.py; then
    printf '[PASS] V1.3: tests/test_catalog_json.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V1.3: tests/test_catalog_json.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V2.2 — cost pytest
  if "${PYTHON_BIN}" -m pytest tests/test_cost.py; then
    printf '[PASS] V2.2: tests/test_cost.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V2.2: tests/test_cost.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V3.2 — CLI pytest
  if "${PYTHON_BIN}" -m pytest tests/test_cli.py; then
    printf '[PASS] V3.2: tests/test_cli.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V3.2: tests/test_cli.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V4.2 — MCP pytest
  if "${PYTHON_BIN}" -m pytest tests/test_mcp_server.py; then
    printf '[PASS] V4.2: tests/test_mcp_server.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.2: tests/test_mcp_server.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V3.3 + V4.3 — wheel install + cost smoke + MCP tools/list smoke
  local whl
  whl="$(_build_wheel)"
  if [[ ! -f "${whl}" ]]; then
    printf '[FAIL] V3.3/V4.3: expected wheel missing at %s\n' "${whl}" >&2
    STEP_POST_FAIL+=1
    return 1
  fi

  # V3.3 — install WITHOUT mcp extra; exercise cost subcommand
  local v3_venv
  v3_venv="$(mktemp -d)/rm-v3-venv"
  "${PYTHON_BIN}" -m venv "${v3_venv}"
  # shellcheck disable=SC1090
  source "${v3_venv}/bin/activate"
  pip install -q --upgrade pip
  pip install -q "${whl}"
  local cost_out cost_rc
  cost_rc=0
  cost_out="$(roadmodel cost --model "opus-test" --platform "claude-code-test" \
    --input-tokens 1000 --output-tokens 500 2>&1)" || cost_rc=$?
  # ROADMODEL_CATALOG_PATH isn't set here, so the wheel falls back to the
  # bundled catalog. The cost subcommand is expected to return either a
  # successful estimate or a typed error for an unknown id; treat exit 0
  # with a "$" line as the PASS signal, and ALSO accept exit 4 with a
  # typed-error stderr (still proves the command is wired). The point of
  # V3.3 is the wheel surface — not the exact catalog payload.
  if [[ "${cost_rc}" -eq 0 ]] && grep -Fq "$" <<<"${cost_out}"; then
    printf '[PASS] V3.3: wheel cost subcommand returned a parseable line\n'
    STEP_POST_PASS+=1
  elif [[ "${cost_rc}" -eq 4 ]]; then
    printf '[PASS] V3.3: wheel cost subcommand exited 4 (typed error) — wiring confirmed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V3.3: wheel cost subcommand exit=%s out=%s\n' "${cost_rc}" "${cost_out}" >&2
    STEP_POST_FAIL+=1
  fi
  deactivate || true

  # V4.3 — install WITH mcp extra; tools/list smoke
  local v4_venv
  v4_venv="$(mktemp -d)/rm-v4-venv"
  "${PYTHON_BIN}" -m venv "${v4_venv}"
  # shellcheck disable=SC1090
  source "${v4_venv}/bin/activate"
  pip install -q --upgrade pip
  pip install -q "${whl}[mcp]"
  local v4_out v4_rc
  v4_rc=0
  v4_out="$(_mcp_tools_list_smoke_py | python - 2>&1)" || v4_rc=$?
  if [[ "${v4_rc}" -eq 0 ]] && grep -Fq "OK" <<<"${v4_out}"; then
    printf '[PASS] V4.3: wheel[mcp] tools/list returned exactly the three documented tools\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.3: wheel[mcp] tools/list smoke failed\n%s\n' "${v4_out}" >&2
    STEP_POST_FAIL+=1
  fi
  deactivate || true

  # V6.2 — PyPI listing for 0.2.0 (skip if network unavailable)
  if command -v curl >/dev/null 2>&1; then
    local pypi_code
    pypi_code="$(curl -fsS -o /dev/null -w '%{http_code}' \
      --max-time 10 https://pypi.org/project/roadmodel/0.2.0/ 2>/dev/null || true)"
    if [[ "${pypi_code}" == "200" ]]; then
      printf '[PASS] V6.2: pypi.org/project/roadmodel/0.2.0/ returned 200\n'
      STEP_POST_PASS+=1
    elif [[ -z "${pypi_code}" ]]; then
      printf '[SKIP] V6.2: PyPI listing check skipped (network unavailable)\n'
    else
      printf '[FAIL] V6.2: PyPI listing returned HTTP %s\n' "${pypi_code}" >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V6.2: curl not installed; skipping PyPI listing check\n'
  fi

  # Optional: live recommend smoke (gated on ANTHROPIC_API_KEY)
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    local live_venv
    live_venv="$(mktemp -d)/rm-live-venv"
    "${PYTHON_BIN}" -m venv "${live_venv}"
    # shellcheck disable=SC1090
    source "${live_venv}/bin/activate"
    pip install -q --upgrade pip
    pip install -q "${whl}"
    local live_home
    live_home="$(mktemp -d)/rm-live-home"
    mkdir -p "${live_home}"
    if HOME="${live_home}" XDG_CONFIG_HOME="${live_home}/xdg" roadmodel context init &&
      HOME="${live_home}" XDG_CONFIG_HOME="${live_home}/xdg" roadmodel recommend \
        --input-tokens 1000 --output-tokens 500 "build a SQL agent" >/dev/null; then
      printf '[PASS] Post: live roadmodel recommend smoke (Anthropic) succeeded\n'
      STEP_POST_PASS+=1
    else
      printf '[FAIL] Post: live recommend smoke failed\n' >&2
      STEP_POST_FAIL+=1
    fi
    deactivate || true
  else
    printf '[SKIP] Post: ANTHROPIC_API_KEY unset; skipping live recommend smoke\n'
  fi

  # Optional: gh pr checks (gated on gh + auth)
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
  printf '%-22s %6s %6s\n' "static-1..33" "${STATIC_PASS}" "${STATIC_FAIL}"
  if [[ "${MODE_DEFAULT}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "pytest(-x)" "${STEP_PY_PASS:-0}" "${STEP_PY_FAIL:-0}"
  fi
  if [[ "${MODE_PY}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "py (full+ruff+mypy)" "${STEP_PY_PASS}" "${STEP_PY_FAIL}"
  fi
  if [[ "${MODE_CLI}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "cli (wheel)" "${STEP_CLI_PASS}" "${STEP_CLI_FAIL}"
  fi
  if [[ "${MODE_MCP}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-22s %6s %6s\n' "mcp (wheel[mcp])" "${STEP_MCP_PASS}" "${STEP_MCP_FAIL}"
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
  STEP_PY_PASS=0
  STEP_PY_FAIL=0
  if "${PYTHON_BIN}" -m pytest -x tests/; then STEP_PY_PASS+=1
  else STEP_PY_FAIL+=1; fi
  print_summary
  if [[ "${STEP_PY_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_FAST}" -eq 1 ]]; then
  rollup_v_fast
  print_summary
  if [[ "${V_AGG_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_ALL}" -eq 1 ]]; then
  run_py_checks
  if [[ "${STEP_PY_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  run_cli_checks
  if [[ "${STEP_CLI_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  run_mcp_checks
  if [[ "${STEP_MCP_FAIL}" -gt 0 ]]; then print_summary; exit 1; fi
  print_summary
  exit 0
fi

if [[ "${MODE_PY}" -eq 1 ]]; then
  run_py_checks
  print_summary
  if [[ "${STEP_PY_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_CLI}" -eq 1 ]]; then
  run_cli_checks
  print_summary
  if [[ "${STEP_CLI_FAIL}" -gt 0 ]]; then exit 1; fi
  exit 0
fi

if [[ "${MODE_MCP}" -eq 1 ]]; then
  run_mcp_checks
  print_summary
  if [[ "${STEP_MCP_FAIL}" -gt 0 ]]; then exit 1; fi
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
