#!/usr/bin/env bash
# scripts/verify-infra.sh
#
# Phase 3 Step 2 infrastructure verification. Confirms:
#   1. DNS:   `dig CNAME staging.roadmodel.ai +short` returns a
#             Vercel-domain target.
#   2. TLS:   `curl -sSI https://staging.roadmodel.ai` returns
#             HTTP/2 200 or HTTP/2 404 (TLS handshake succeeded
#             either way).
#   3. Docs:  the required infra/README.md section headings are
#             present.
#   4. Schema: every env var documented in infra/README.md
#             "Environment variables" appears in
#             infra/.env.example.
#
# Will be invoked by scripts/verify-phase03.sh in Step 8. The DNS
# and TLS checks fail until the maintainer completes the
# Provisioning sequence in infra/README.md; the docs and schema
# checks pass from this commit onward.
#
# Usage:
#   ./scripts/verify-infra.sh
#
# Exit codes:
#   0 — every check PASSed.
#   1 — at least one check FAILed.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "verify-infra.sh: not inside a git checkout" >&2
  exit 1
fi
cd "${ROOT}"

README="infra/README.md"
ENV_EXAMPLE="infra/.env.example"
STAGING_HOST="staging.roadmodel.ai"
STAGING_URL="https://${STAGING_HOST}"

FAILED=0
declare -a PASS_LINES=()
declare -a FAIL_LINES=()

pass() {
  PASS_LINES+=("PASS  $1")
  echo "PASS  $1"
}

fail() {
  FAIL_LINES+=("FAIL  $1")
  echo "FAIL  $1"
  FAILED=1
}

# -----------------------------------------------------------------------------
# Check 1: DNS — staging.roadmodel.ai CNAME points at a Vercel target.
# -----------------------------------------------------------------------------
echo "==> Check 1: DNS CNAME"
if ! command -v dig >/dev/null 2>&1; then
  fail "1 DNS: dig not installed; cannot resolve ${STAGING_HOST}"
else
  DIG_OUTPUT="$(dig CNAME "${STAGING_HOST}" +short 2>/dev/null || true)"
  if [[ -z "${DIG_OUTPUT}" ]]; then
    fail "1 DNS: ${STAGING_HOST} has no CNAME record (run step 4 of infra/README.md Provisioning sequence)"
  elif echo "${DIG_OUTPUT}" | grep -qi "vercel-dns"; then
    pass "1 DNS: ${STAGING_HOST} CNAME -> ${DIG_OUTPUT}"
  else
    fail "1 DNS: ${STAGING_HOST} CNAME does not point at vercel-dns (got: ${DIG_OUTPUT})"
  fi
fi

# -----------------------------------------------------------------------------
# Check 2: TLS — curl -sSI returns HTTP/2 200 or 404 (handshake OK).
# -----------------------------------------------------------------------------
echo "==> Check 2: TLS handshake"
if ! command -v curl >/dev/null 2>&1; then
  fail "2 TLS: curl not installed; cannot probe ${STAGING_URL}"
else
  # --max-time bounds the probe; --http2 prefers HTTP/2 but falls back to 1.1
  # so the check still succeeds against any cert-issuing TLS responder.
  CURL_STATUS="$(curl -sSI --max-time 10 --http2 "${STAGING_URL}" 2>/dev/null | head -1 | tr -d '\r' || true)"
  if [[ -z "${CURL_STATUS}" ]]; then
    fail "2 TLS: no response from ${STAGING_URL} (DNS/TLS not yet provisioned)"
  elif echo "${CURL_STATUS}" | grep -Eq '^HTTP/[12](\.[01])?[[:space:]]+(200|404)'; then
    pass "2 TLS: ${STAGING_URL} -> ${CURL_STATUS}"
  else
    fail "2 TLS: unexpected status from ${STAGING_URL}: ${CURL_STATUS}"
  fi
fi

# -----------------------------------------------------------------------------
# Check 3: Docs — required infra/README.md section headings present.
# -----------------------------------------------------------------------------
echo "==> Check 3: infra/README.md sections"
if [[ ! -f "${README}" ]]; then
  fail "3 Docs: ${README} not found"
else
  REQUIRED_SECTIONS=(
    "## Cloud projects"
    "## Environment variables"
    "## DNS records"
    "## TLS posture"
    "## Provider cost ceilings"
    "## UptimeRobot monitors"
    "## Provisioning sequence"
    "## Disaster recovery"
  )
  MISSING=0
  for heading in "${REQUIRED_SECTIONS[@]}"; do
    if grep -qxF "${heading}" "${README}"; then
      pass "3 Docs: ${README} contains \"${heading}\""
    else
      fail "3 Docs: ${README} missing \"${heading}\""
      MISSING=$((MISSING + 1))
    fi
  done
fi

# -----------------------------------------------------------------------------
# Check 4: Schema cross-reference — every env var in the README's
# "Environment variables" section appears in infra/.env.example.
# -----------------------------------------------------------------------------
echo "==> Check 4: env var cross-reference"
if [[ ! -f "${README}" ]] || [[ ! -f "${ENV_EXAMPLE}" ]]; then
  fail "4 Schema: ${README} or ${ENV_EXAMPLE} not found"
else
  # Extract the "## Environment variables" section: everything between
  # that heading and the next "## " heading.
  SECTION="$(awk '
    /^## Environment variables[[:space:]]*$/ { in_section = 1; next }
    /^## / && in_section { exit }
    in_section { print }
  ' "${README}")"

  if [[ -z "${SECTION}" ]]; then
    fail "4 Schema: could not extract \"## Environment variables\" section from ${README}"
  else
    # Pull every backtick-wrapped UPPER_SNAKE_CASE token from the section.
    # These are the variable names in the table's first column.
    DOCUMENTED_VARS="$(echo "${SECTION}" | grep -oE '`[A-Z][A-Z0-9_]+`' | tr -d '`' | sort -u)"

    if [[ -z "${DOCUMENTED_VARS}" ]]; then
      fail "4 Schema: no env vars extracted from \"## Environment variables\" section"
    else
      VAR_COUNT=0
      MISS_COUNT=0
      while IFS= read -r var; do
        VAR_COUNT=$((VAR_COUNT + 1))
        if grep -qE "^${var}=" "${ENV_EXAMPLE}"; then
          pass "4 Schema: ${var} present in ${ENV_EXAMPLE}"
        else
          fail "4 Schema: ${var} documented in ${README} but missing from ${ENV_EXAMPLE}"
          MISS_COUNT=$((MISS_COUNT + 1))
        fi
      done <<< "${DOCUMENTED_VARS}"
    fi
  fi
fi

# -----------------------------------------------------------------------------
# Summary.
# -----------------------------------------------------------------------------
echo
echo "==> Summary"
echo "  PASS: ${#PASS_LINES[@]}"
echo "  FAIL: ${#FAIL_LINES[@]}"
if [[ ${FAILED} -ne 0 ]]; then
  echo "verify-infra.sh: at least one check failed" >&2
  exit 1
fi
echo "verify-infra.sh: all checks passed"
exit 0
