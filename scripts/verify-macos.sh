#!/usr/bin/env bash
# scripts/verify-macos.sh
#
# Native macOS verification, run locally on the Mac Studio.
#
# Context: roadmodel is a PUBLIC repo, so its Linux GitHub Actions minutes
# are free — but macOS runners are NOT covered by the public-repo discount
# and were the only paid Actions minutes on this project. The macOS legs of
# phase-verify.yml and verify-pypi.yml were removed to stop that spend. This
# script preserves the same macOS coverage by running it here, for free, on
# Apple hardware.
#
# Usage:
#   ./scripts/verify-macos.sh              # all phases, --fast (default; matches CI `verify` job)
#   ./scripts/verify-macos.sh --post       # all phases, --post (matches CI `post` job; heavier)
#   ./scripts/verify-macos.sh --phase 03   # a single phase (repeatable)
#   ./scripts/verify-macos.sh --pypi 0.2.20  # install-smoke a published wheel on macOS
#
# Python resolution is delegated to the verify-phaseNN.sh scripts, which honor
# (in order) ROADMODEL_VERIFY_PYTHON, ./.venv/bin/python, python3.11, python3.
# Per project convention, point ROADMODEL_VERIFY_PYTHON at a 3.11+ interpreter
# (e.g. ~/.cache/rmverify) — base conda 3.10 cannot import roadmodel.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-macos.sh: not inside a git checkout" >&2
  exit 1
fi
cd "${ROOT}"

ALL_PHASES=("01" "02" "03" "04" "046")
MODE="--fast"
PHASES=()
PYPI_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast) MODE="--fast" ;;
    --post) MODE="--post" ;;
    --phase)
      shift
      [[ $# -gt 0 ]] || { echo "verify-macos.sh: --phase needs a value" >&2; exit 2; }
      PHASES+=("$1")
      ;;
    --pypi)
      shift
      [[ $# -gt 0 ]] || { echo "verify-macos.sh: --pypi needs a version" >&2; exit 2; }
      PYPI_VERSION="$1"
      ;;
    -h|--help)
      sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "verify-macos.sh: unknown argument '$1'" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "WARNING: verify-macos.sh is meant to run on macOS; this host is $(uname -s)." >&2
  echo "         Running anyway, but it will not exercise macOS-specific behavior." >&2
fi

# --pypi: replicate verify-pypi.yml's install-smoke on macOS. Best-effort
# across whichever python3.11/3.12/3.13 are on PATH.
if [[ -n "${PYPI_VERSION}" ]]; then
  VERSION="${PYPI_VERSION#v}"
  VERSION="${VERSION%-pypi}"
  found_any=0
  for py in python3.11 python3.12 python3.13; do
    command -v "${py}" >/dev/null 2>&1 || continue
    found_any=1
    echo "== macOS install-smoke: roadmodel==${VERSION} on ${py} =="
    workdir="$(mktemp -d)"
    "${py}" -m venv "${workdir}/venv"
    # shellcheck disable=SC1091
    . "${workdir}/venv/bin/activate"
    python -m pip install --quiet --upgrade pip
    python -m pip install "roadmodel==${VERSION}"
    which roadmodel
    roadmodel --help >/dev/null
    python -c "import roadmodel; print('  module __version__ =', roadmodel.__version__)"
    python -c "import platform; print('  ', platform.platform(), 'python', platform.python_version())"
    deactivate
    rm -rf "${workdir}"
  done
  if [[ "${found_any}" -eq 0 ]]; then
    echo "verify-macos.sh: no python3.11/3.12/3.13 found on PATH for --pypi smoke" >&2
    exit 1
  fi
  echo "== macOS install-smoke passed for roadmodel==${VERSION} =="
  exit 0
fi

# Default: run the phase verify scripts natively.
[[ ${#PHASES[@]} -eq 0 ]] && PHASES=("${ALL_PHASES[@]}")

export ROADMODEL_VERIFY_PYTHON="${ROADMODEL_VERIFY_PYTHON:-}"
failed=()
for phase in "${PHASES[@]}"; do
  script="scripts/verify-phase${phase}.sh"
  if [[ ! -x "${script}" ]]; then
    echo "verify-macos.sh: no such phase script: ${script}" >&2
    exit 2
  fi
  echo "========================================================"
  echo "== macOS verify phase ${phase} (${MODE})"
  echo "========================================================"
  if bash "${script}" "${MODE}"; then
    echo "[PASS] phase ${phase}"
  else
    echo "[FAIL] phase ${phase}" >&2
    failed+=("${phase}")
  fi
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "verify-macos.sh: FAILED phases: ${failed[*]}" >&2
  exit 1
fi
echo "verify-macos.sh: all phases passed (${MODE}) on $(uname -sm)"
