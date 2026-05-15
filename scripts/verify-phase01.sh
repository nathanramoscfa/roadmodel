#!/usr/bin/env bash
# scripts/verify-phase01.sh
#
# Phase 1 deliverable verification (canonical template for verify-phaseNN.sh).
# Usage:
#   ./scripts/verify-phase01.sh              # static (33) + pytest -x
#   ./scripts/verify-phase01.sh --fast       # static + V1.1–V7.3 rollup (CI)
#   ./scripts/verify-phase01.sh --py         # static + pytest + ruff + mypy
#   ./scripts/verify-phase01.sh --cli        # static + wheel build/install smoke
#   ./scripts/verify-phase01.sh --all        # static + --py + --cli
#   ./scripts/verify-phase01.sh --post     # static + V1–V7 + optional live checks
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-phase01.sh: not inside a git checkout" >&2
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
MODE_ALL=0
MODE_POST=0

if [[ $# -eq 0 ]]; then
  MODE_DEFAULT=1
else
  case "$1" in
    --fast) MODE_FAST=1 ;;
    --py) MODE_PY=1 ;;
    --cli) MODE_CLI=1 ;;
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
fi

# --- counters (static checks 1–33) ---
declare -i STATIC_PASS=0 STATIC_FAIL=0
declare -i STEP_PY_PASS=0 STEP_PY_FAIL=0
declare -i STEP_CLI_PASS=0 STEP_CLI_FAIL=0
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

  # 1
  if [[ -f LICENSE ]]; then record_pass 1 "LICENSE exists at repo root"
  else record_fail 1 "LICENSE exists at repo root" "missing"; fi

  # 2 — first non-empty line must name Apache License 2.0 header family
  local lic_line=""
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line//[[:space:]]/}" ]] && continue
    lic_line="${line}"
    break
  done < LICENSE
  if [[ "${lic_line}" =~ Apache[[:space:]]+License ]]; then
    record_pass 2 "LICENSE opens with Apache-2.0 upstream header"
  else
    record_fail 2 "LICENSE opens with Apache-2.0 upstream header" \
      "first non-empty line does not match Apache License"
  fi

  if [[ -f NOTICE ]]; then record_pass 3 "NOTICE exists at repo root"
  else record_fail 3 "NOTICE exists at repo root" "missing"; fi

  if [[ -f CONTRIBUTING.md ]]; then record_pass 4 "CONTRIBUTING.md exists at repo root"
  else record_fail 4 "CONTRIBUTING.md exists at repo root" "missing"; fi

  if [[ -f CODE_OF_CONDUCT.md ]] && grep -Fq "Contributor Covenant" CODE_OF_CONDUCT.md; then
    record_pass 5 "CODE_OF_CONDUCT.md exists and names Contributor Covenant"
  else
    record_fail 5 "CODE_OF_CONDUCT.md exists and names Contributor Covenant" \
      "missing or string not found"
  fi

  if [[ -f SECURITY.md ]]; then record_pass 6 "SECURITY.md exists at repo root"
  else record_fail 6 "SECURITY.md exists at repo root" "missing"; fi

  if [[ -f .github/ISSUE_TEMPLATE/bug_report.md ]] &&
    [[ -f .github/ISSUE_TEMPLATE/feature_request.md ]] &&
    [[ -f .github/PULL_REQUEST_TEMPLATE.md ]]; then
    record_pass 7 "GitHub issue + PR templates exist"
  else
    record_fail 7 "GitHub issue + PR templates exist" "one or more missing"
  fi

  # 8 — rename sweep: hits only inside three canonical doc paths or allowlisted
  local bad8=0
  local allow_rx='model-selector\.(txt|md)|docs/model-selector\.|<model-selector>|@model-selector|previously named|Project renamed from|was previously named|renamed from'
  while IFS= read -r rec; do
    [[ -z "${rec}" ]] && continue
    local fn="${rec%%:*}"
    local rest="${rec#*:}"
    case "${fn}" in
      docs/model-selector.txt|docs/model-selector.md|docs/model-tier-cost-scale.md)
        continue
        ;;
    esac
    if grep -Eq "${allow_rx}" <<< "${rest}"; then
      continue
    fi
    bad8=1
    printf '  disallowed hit: %s\n' "${rec}" >&2
  done < <(git grep -nI --extended-regexp 'model[-_]selector' -- . || true)
  if [[ "${bad8}" -eq 0 ]]; then
    record_pass 8 "Rename sweep: no stray model[-_]selector hits outside canonical docs"
  else
    record_fail 8 "Rename sweep: no stray model[-_]selector hits outside canonical docs" \
      "see disallowed git grep lines above"
  fi

  # 9
  if [[ -f tests/test_doc_schema.py ]] && [[ -f tests/test_freshness.py ]]; then
    if "${PYTHON_BIN}" -m py_compile tests/test_doc_schema.py tests/test_freshness.py; then
      record_pass 9 "tests/test_doc_schema.py and tests/test_freshness.py present and compile"
    else
      record_fail 9 "tests/test_doc_schema.py and tests/test_freshness.py present and compile" \
        "py_compile failed"
    fi
  else
    record_fail 9 "tests/test_doc_schema.py and tests/test_freshness.py present and compile" \
      "missing file"
  fi

  if [[ -f pyproject.toml ]] && grep -Fq 'name = "roadmodel"' pyproject.toml; then
    record_pass 10 "pyproject.toml declares name = roadmodel"
  else
    record_fail 10 "pyproject.toml declares name = roadmodel" "missing or wrong name"
  fi

  if grep -Fq 'roadmodel = "roadmodel.cli:main"' pyproject.toml; then
    record_pass 11 "pyproject.toml has roadmodel console script entry"
  else
    record_fail 11 "pyproject.toml has roadmodel console script entry" "entry missing"
  fi

  if [[ -f hatch_build.py ]]; then record_pass 12 "hatch_build.py exists"
  else record_fail 12 "hatch_build.py exists" "missing"; fi

  if [[ -f src/roadmodel/__init__.py ]] && grep -Fq "__version__" src/roadmodel/__init__.py; then
    record_pass 13 "src/roadmodel/__init__.py defines __version__"
  else
    record_fail 13 "src/roadmodel/__init__.py defines __version__" "missing"
  fi

  if grep -Fq "src/roadmodel/data/" .gitignore; then
    record_pass 14 "src/roadmodel/data/ is gitignored"
  else
    record_fail 14 "src/roadmodel/data/ is gitignored" "pattern missing from .gitignore"
  fi

  if grep -Fq "model-selector.txt" hatch_build.py &&
    grep -Fq "model-tier-cost-scale.md" hatch_build.py &&
    grep -Fq "user-context.example.md" hatch_build.py; then
    record_pass 15 "hatch_build.py lists all three bundled docs"
  else
    record_fail 15 "hatch_build.py lists all three bundled docs" "missing reference"
  fi

  local s4=(
    src/roadmodel/cli.py
    src/roadmodel/recommend.py
    src/roadmodel/config.py
    src/roadmodel/user_context.py
  )
  local ok16=1
  for p in "${s4[@]}"; do
    [[ -f "${p}" ]] || ok16=0
  done
  if [[ "${ok16}" -eq 1 ]]; then record_pass 16 "Core CLI modules exist"
  else record_fail 16 "Core CLI modules exist" "one of cli/recommend/config/user_context missing"
  fi

  local prov=(
    src/roadmodel/providers/anthropic.py
    src/roadmodel/providers/openai.py
    src/roadmodel/providers/google.py
  )
  local ok17=1
  for p in "${prov[@]}"; do
    [[ -f "${p}" ]] || ok17=0
  done
  if [[ "${ok17}" -eq 1 ]]; then record_pass 17 "Provider adapters exist"
  else record_fail 17 "Provider adapters exist" "missing provider module"
  fi

  if [[ -f tests/test_cli.py ]]; then record_pass 18 "tests/test_cli.py exists"
  else record_fail 18 "tests/test_cli.py exists" "missing"; fi

  if [[ -f tests/fixtures/sample_response.txt ]] &&
    grep -Fq "MODEL:" tests/fixtures/sample_response.txt &&
    grep -Fq "PLATFORM:" tests/fixtures/sample_response.txt &&
    grep -Fq "MAX MODE:" tests/fixtures/sample_response.txt &&
    grep -Fq "THINKING:" tests/fixtures/sample_response.txt &&
    grep -Fq "CONVERSATION:" tests/fixtures/sample_response.txt &&
    grep -Fq "RATIONALE:" tests/fixtures/sample_response.txt; then
    record_pass 19 "sample_response.txt has all six field labels"
  else
    record_fail 19 "sample_response.txt has all six field labels" "missing file or label"
  fi

  if [[ -f tests/fixtures/sample_user_context.md ]]; then
    record_pass 20 "sample_user_context.md fixture exists"
  else
    record_fail 20 "sample_user_context.md fixture exists" "missing"
  fi

  if grep -Eq '@click\.(group|command)|click\.group' src/roadmodel/cli.py; then
    record_pass 21 "CLI wires a Click group/command entry"
  else
    record_fail 21 "CLI wires a Click group/command entry" "no @click.group / click.group"
  fi

  if grep -Fq '"platform"' src/roadmodel/recommend.py &&
    grep -Fq '"thinking"' src/roadmodel/recommend.py &&
    grep -Fq '"model"' src/roadmodel/recommend.py; then
    record_pass 22 "parse_response normalizes six keys including platform and thinking"
  else
    record_fail 22 "parse_response normalizes six keys including platform and thinking" \
      "expected string keys not found in recommend.py"
  fi

  if grep -Fq "pip install roadmodel" README.md; then
    record_pass 23 "README documents pip install roadmodel"
  else
    record_fail 23 "README documents pip install roadmodel" "install line missing"
  fi

  if [[ -f CHANGELOG.md ]] && grep -Fq "## [0.1.0]" CHANGELOG.md; then
    record_pass 24 "CHANGELOG has ## [0.1.0] section"
  else
    record_fail 24 "CHANGELOG has ## [0.1.0] section" "missing"
  fi

  if [[ -f docs/byo-key-setup.md ]] &&
    grep -Fq "ANTHROPIC_API_KEY" docs/byo-key-setup.md &&
    grep -Fq "OPENAI_API_KEY" docs/byo-key-setup.md &&
    grep -Fq "GOOGLE_API_KEY" docs/byo-key-setup.md; then
    record_pass 25 "docs/byo-key-setup.md names all three provider env vars"
  else
    record_fail 25 "docs/byo-key-setup.md names all three provider env vars" "missing names"
  fi

  if [[ -f docs/user-context-setup.md ]] &&
    grep -Fq "~/.config/roadmodel/user-context.md" docs/user-context-setup.md &&
    grep -Fq "ROADMODEL_USER_CONTEXT" docs/user-context-setup.md; then
    record_pass 26 "docs/user-context-setup.md documents default path + env override"
  else
    record_fail 26 "docs/user-context-setup.md documents default path + env override" \
      "missing strings"
  fi

  if [[ -f .github/workflows/release.yml ]] &&
    grep -Fq "sigstore/gh-action-sigstore-python" .github/workflows/release.yml; then
    record_pass 27 "release.yml references Sigstore Python action"
  else
    record_fail 27 "release.yml references Sigstore Python action" "missing action id"
  fi

  if grep -q "ruff" .github/workflows/tests.yml && grep -q "mypy" .github/workflows/tests.yml; then
    record_pass 28 "tests.yml runs ruff and mypy"
  else
    record_fail 28 "tests.yml runs ruff and mypy" "job/step text missing"
  fi

  if [[ -f tests/test_ci_smoke.py ]]; then record_pass 29 "tests/test_ci_smoke.py exists"
  else record_fail 29 "tests/test_ci_smoke.py exists" "missing"; fi

  if [[ -x scripts/verify-phase01.sh ]]; then
    record_pass 30 "verify-phase01.sh exists and is executable"
  else
    record_fail 30 "verify-phase01.sh exists and is executable" "missing or not chmod +x"
  fi

  if [[ -f docs/phase01-qa-findings.md ]]; then
    record_pass 31 "docs/phase01-qa-findings.md exists"
  else
    record_fail 31 "docs/phase01-qa-findings.md exists" "missing"
  fi

  if [[ -f private/phase01-roadmap.md ]]; then
    record_pass 32 "private/phase01-roadmap.md exists (local planning doc)"
  elif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    record_pass 32 "private/phase01-roadmap.md absent on CI (gitignored locally)"
  else
    record_fail 32 "private/phase01-roadmap.md exists (local planning doc)" "missing"
  fi

  if [[ -f .github/workflows/phase-verify.yml ]] &&
    grep -Eq 'phase:[[:space:]]*\[[[:space:]]*1[[:space:]]*\]' .github/workflows/phase-verify.yml; then
    record_pass 33 "phase-verify.yml exists with matrix phase list including 1"
  else
    record_fail 33 "phase-verify.yml exists with matrix phase list including 1" \
      "missing file or matrix.phase lacks 1"
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
  v_range_pass 1 7 V1.1 || true
  v_range_pass 8 9 V2.1 || true
  v_range_pass 10 15 V3.1 || true
  v_range_pass 16 22 V4.1 || true
  v_range_pass 23 26 V5.1 || true
  v_range_pass 27 29 V6.1 || true
  if [[ "${STATIC_FAIL}" -eq 0 && "${STATIC_PASS}" -eq 33 ]]; then
    printf '[PASS] V7.1: verify-phase01.sh running in --fast mode completed static gate\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V7.1: static gate incomplete\n' >&2
    V_AGG_FAIL+=1
  fi
  if [[ "${STATIC_FAIL}" -eq 0 ]] &&
    grep -Eq 'phase:[[:space:]]*\[[[:space:]]*1[[:space:]]*\]' .github/workflows/phase-verify.yml; then
    printf '[PASS] V7.2: phase-verify.yml matrix includes phase 1\n'
    V_AGG_PASS+=1
  else
    printf '[FAIL] V7.2: matrix phase 1 not confirmed\n' >&2
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

run_cli_checks() {
  STEP_CLI_PASS=0
  STEP_CLI_FAIL=0
  local ver
  ver="$(pyproject_version)"
  rm -rf dist build
  "${PYTHON_BIN}" -m pip install -q build
  "${PYTHON_BIN}" -m build
  local whl="dist/roadmodel-${ver}-py3-none-any.whl"
  if [[ ! -f "${whl}" ]]; then
    printf '[FAIL] CLI gate: expected wheel missing at %s\n' "${whl}" >&2
    STEP_CLI_FAIL+=1
    return 1
  fi
  STEP_CLI_PASS+=1
  for need in \
    roadmodel/data/model-selector.txt \
    roadmodel/data/model-tier-cost-scale.md \
    roadmodel/data/user-context.example.md; do
    if "${PYTHON_BIN}" -m zipfile -l "${whl}" | grep -Fq "${need}"; then
      STEP_CLI_PASS+=1
    else
      printf '[FAIL] CLI gate: wheel missing %s\n' "${need}" >&2
      STEP_CLI_FAIL+=1
    fi
  done

  local venv
  venv="$(mktemp -d)/rm-cli-venv"
  "${PYTHON_BIN}" -m venv "${venv}"
  # shellcheck disable=SC1090
  source "${venv}/bin/activate"
  python -m pip install -q --upgrade pip
  pip install -q "${whl}"
  local help_out rc
  help_out="$(roadmodel --help 2>&1)" || rc=$?
  rc="${rc:-0}"
  if [[ "${rc}" -eq 0 ]] && grep -Fq recommend <<<"${help_out}" &&
    grep -Fq catalog <<<"${help_out}" && grep -Fq context <<<"${help_out}"; then
    STEP_CLI_PASS+=1
  else
    printf '[FAIL] CLI gate: roadmodel --help missing subcommand or non-zero exit\n' >&2
    STEP_CLI_FAIL+=1
  fi

  # V4.4 — isolated HOME
  local fake_home
  fake_home="$(mktemp -d)/rm-home"
  mkdir -p "${fake_home}"
  if HOME="${fake_home}" roadmodel context init &&
    HOME="${fake_home}" roadmodel context path | grep -Fq "user-context.md"; then
    STEP_CLI_PASS+=1
  else
    printf '[FAIL] CLI gate: roadmodel context init/path under tmp HOME\n' >&2
    STEP_CLI_FAIL+=1
  fi
  deactivate || true
}

run_post_matrix() {
  STEP_POST_PASS=0
  STEP_POST_FAIL=0
  printf '\n== Post-implementation V1–V7 matrix ==\n'

  # V1.2
  if command -v gitleaks >/dev/null 2>&1; then
    if gitleaks detect --no-banner --source .; then
      printf '[PASS] V1.2: gitleaks detect --no-banner exited 0\n'
      STEP_POST_PASS+=1
    else
      printf '[FAIL] V1.2: gitleaks reported leaks\n' >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] V1.2: gitleaks not installed; skipping\n'
  fi

  # V2.2
  if "${PYTHON_BIN}" -m pytest tests/test_doc_schema.py tests/test_freshness.py; then
    printf '[PASS] V2.2: schema + freshness pytest targets passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V2.2: schema and/or freshness pytest failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V3.2 + V3.3 (build + wheel contents)
  local ver
  ver="$(pyproject_version)"
  rm -rf dist build
  "${PYTHON_BIN}" -m pip install -q build
  if "${PYTHON_BIN}" -m build; then
    printf '[PASS] V3.2: python -m build succeeded (version %s)\n' "${ver}"
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V3.2: python -m build failed\n' >&2
    STEP_POST_FAIL+=1
    return 1
  fi
  local whl="dist/roadmodel-${ver}-py3-none-any.whl"
  local zok=1
  for need in \
    roadmodel/data/model-selector.txt \
    roadmodel/data/model-tier-cost-scale.md \
    roadmodel/data/user-context.example.md; do
    if ! "${PYTHON_BIN}" -m zipfile -l "${whl}" | grep -Fq "${need}"; then
      zok=0
      break
    fi
  done
  if [[ "${zok}" -eq 1 ]]; then
    printf '[PASS] V3.3: wheel bundles all three roadmodel/data/*.md|.txt artifacts\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V3.3: wheel missing a bundled data file\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V4.2
  if "${PYTHON_BIN}" -m pytest tests/test_cli.py; then
    printf '[PASS] V4.2: tests/test_cli.py passed\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.2: tests/test_cli.py failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # V4.3 + V4.4 (reuse CLI venv pattern)
  local venv road_bin
  venv="$(mktemp -d)/rm-post-venv"
  "${PYTHON_BIN}" -m venv "${venv}"
  road_bin="${venv}/bin/roadmodel"
  # shellcheck disable=SC1090
  source "${venv}/bin/activate"
  pip install -q --upgrade pip
  pip install -q "${whl}"
  local ho rc
  rc=0
  ho="$(roadmodel --help 2>&1)" || rc=$?
  if [[ "${rc}" -eq 0 ]] && grep -Fq context <<<"${ho}" && grep -Fq recommend <<<"${ho}" &&
    grep -Fq catalog <<<"${ho}"; then
    printf '[PASS] V4.3: installed wheel; roadmodel --help lists recommend/catalog/context\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.3: help output smoke failed\n' >&2
    STEP_POST_FAIL+=1
  fi
  local fake_home
  fake_home="$(mktemp -d)/rm-post-home"
  mkdir -p "${fake_home}"
  if HOME="${fake_home}" roadmodel context init &&
    HOME="${fake_home}" roadmodel context path | grep -Fq "user-context.md"; then
    printf '[PASS] V4.4: context init + path under isolated HOME\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V4.4: context init/path smoke failed\n' >&2
    STEP_POST_FAIL+=1
  fi
  deactivate || true

  # V6.2 YAML parse (PyYAML is not a hard dev dependency; install on demand)
  if ! "${PYTHON_BIN}" -c "import yaml" 2>/dev/null; then
    "${PYTHON_BIN}" -m pip install -q pyyaml
  fi
  if "${PYTHON_BIN}" -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/release.yml').read_text())" &&
    "${PYTHON_BIN}" -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/tests.yml').read_text())"; then
    printf '[PASS] V6.2: release.yml and tests.yml parse as YAML\n'
    STEP_POST_PASS+=1
  else
    printf '[FAIL] V6.2: YAML parse failed\n' >&2
    STEP_POST_FAIL+=1
  fi

  # Live recommend (optional)
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    local smoke_home
    smoke_home="$(mktemp -d)/rm-live-home"
    mkdir -p "${smoke_home}"
    if HOME="${smoke_home}" "${road_bin}" context init --force &&
      HOME="${smoke_home}" "${road_bin}" recommend "Reply with the single word OK." \
        --provider anthropic --json >/dev/null; then
      printf '[PASS] Post: live roadmodel recommend smoke (Anthropic) succeeded\n'
      STEP_POST_PASS+=1
    else
      printf '[FAIL] Post: live recommend smoke failed\n' >&2
      STEP_POST_FAIL+=1
    fi
  else
    printf '[SKIP] Post: ANTHROPIC_API_KEY unset; skipping live recommend smoke\n'
  fi

  # gh pr checks (optional)
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
  printf '%-14s %6s %6s\n' "Stage" "Pass" "Fail"
  printf '%-14s %6s %6s\n' "static-1..33" "${STATIC_PASS}" "${STATIC_FAIL}"
  if [[ "${MODE_DEFAULT}" -eq 1 ]]; then
    printf '%-14s %6s %6s\n' "pytest(-x)" "${STEP_PY_PASS:-0}" "${STEP_PY_FAIL:-0}"
  fi
  if [[ "${MODE_PY}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-14s %6s %6s\n' "py (full+ruff+mypy)" "${STEP_PY_PASS}" "${STEP_PY_FAIL}"
  fi
  if [[ "${MODE_CLI}" -eq 1 || "${MODE_ALL}" -eq 1 ]]; then
    printf '%-14s %6s %6s\n' "cli (wheel)" "${STEP_CLI_PASS}" "${STEP_CLI_FAIL}"
  fi
  if [[ "${MODE_FAST}" -eq 1 ]]; then
    printf '%-14s %6s %6s\n' "V-rollup" "${V_AGG_PASS}" "${V_AGG_FAIL}"
  fi
  if [[ "${MODE_POST}" -eq 1 ]]; then
    printf '%-14s %6s %6s\n' "V-rollup(pre)" "${V_AGG_PASS}" "${V_AGG_FAIL}"
    printf '%-14s %6s %6s\n' "post-matrix" "${STEP_POST_PASS}" "${STEP_POST_FAIL}"
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
