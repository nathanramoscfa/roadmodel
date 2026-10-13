#!/usr/bin/env bash
# scripts/with-prod-secrets.sh
#
# Fetches roadmodel production secrets from the macOS login keychain
# under service name "roadmodel/<VAR>", exports them, and exec's the
# remainder of argv. Replaces the per-script paste-from-Google-PWM
# ritual for maintainer scripts that need production credentials.
#
# Usage:
#   scripts/with-prod-secrets.sh [--extra NAME ...] [--] <command> [args...]
#
# Example:
#   scripts/with-prod-secrets.sh node web/node_modules/.bin/tsx \
#       scripts/measure-recommend-latency.ts \
#       --target https://roadmodel.ai --requests 50 --window-seconds 600
#
# Seed or replace an entry using the hidden prompt and captured verification:
#   python3 scripts/seed-prod-secret.py SUPABASE_URL

set -euo pipefail

SECRETS=(
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  NEXT_PUBLIC_SUPABASE_ANON_KEY
  GOOGLE_API_KEY
  SITE_PASSWORD
  ROADMODEL_LATENCY_BYPASS_TOKEN
  UPSTASH_REDIS_URL
  UPSTASH_REDIS_TOKEN
  AA_API_KEY
  ROADMODEL_INTERNAL_TOKEN
)

# Validate the entire option list before the first credential lookup.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --) shift; break ;;
    --extra)
      [[ $# -ge 2 ]] || { echo 'with-prod-secrets: --extra requires a name' >&2; exit 64; }
      case "$2" in
        ROADMODEL_IP_SALT|POOL_SYNC_REFRESH_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|DEEPSEEK_API_KEY|XAI_API_KEY|GROQ_API_KEY|MISTRAL_API_KEY|ZAI_API_KEY|OPENROUTER_API_KEY|TOGETHER_API_KEY|OLLAMA_API_KEY|ROADMODEL_API_KEY) ;;
        *) echo 'with-prod-secrets: unsupported extra credential' >&2; exit 64 ;;
      esac
      found=false
      for name in "${SECRETS[@]}"; do
        if [[ "$name" == "$2" ]]; then found=true; fi
      done
      if [[ "$found" == false ]]; then SECRETS+=("$2"); fi
      shift 2 ;;
    -*) echo 'with-prod-secrets: unsupported option' >&2; exit 64 ;;
    *) break ;;
  esac
done
if [[ $# -eq 0 ]]; then
  echo 'usage: with-prod-secrets.sh [--extra NAME ...] [--] command [args...]' >&2
  exit 64
fi

fetch() {
  local name="$1"
  local value
  if ! value=$(/usr/bin/security find-generic-password -s "roadmodel/${name}" -w 2>/dev/null) || [[ -z "$value" ]]; then
    echo "with-prod-secrets: missing keychain entry roadmodel/${name}; use seed-prod-secret.py" >&2
    return 1
  fi
  printf '%s' "$value"
}

for var in "${SECRETS[@]}"; do
  value=$(fetch "$var") || exit 1
  export "$var=$value"
done

exec "$@"
