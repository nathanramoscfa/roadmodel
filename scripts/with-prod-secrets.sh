#!/usr/bin/env bash
# scripts/with-prod-secrets.sh
#
# Fetches roadmodel production secrets from the macOS login keychain
# under service name "roadmodel/<VAR>", exports them, and exec's the
# remainder of argv. Replaces the per-script paste-from-Google-PWM
# ritual for maintainer scripts that need production credentials.
#
# Usage:
#   scripts/with-prod-secrets.sh <command> [args...]
#
# Example:
#   scripts/with-prod-secrets.sh node web/node_modules/.bin/tsx \
#       scripts/measure-recommend-latency.ts \
#       --target https://roadmodel.ai --requests 50 --window-seconds 600
#
# One-time setup (paste once, values from Google Password Manager):
#   security add-generic-password -U -a "$USER" -s "roadmodel/<VAR>" -w '<value>'
# for each of the SECRETS listed below.
#
# Verify any entry:
#   security find-generic-password -s "roadmodel/SUPABASE_URL" -w

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <command> [args...]" >&2
  exit 64
fi

SECRETS=(
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  NEXT_PUBLIC_SUPABASE_ANON_KEY
  GOOGLE_API_KEY
  SITE_PASSWORD
  ROADMODEL_LATENCY_BYPASS_TOKEN
  UPSTASH_REDIS_URL
  UPSTASH_REDIS_TOKEN
)

fetch() {
  local name="$1"
  local value
  if ! value=$(security find-generic-password -s "roadmodel/${name}" -w 2>/dev/null); then
    cat >&2 <<EOF
with-prod-secrets: missing keychain entry roadmodel/${name}
  Seed it once with:
    security add-generic-password -U -a "\$USER" -s "roadmodel/${name}" -w '<value-from-GPM>'
EOF
    return 1
  fi
  printf '%s' "$value"
}

for var in "${SECRETS[@]}"; do
  value=$(fetch "$var") || exit 1
  export "$var=$value"
done

exec "$@"
