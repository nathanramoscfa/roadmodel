#!/bin/bash
# Automated effort-token measurement on the operator's Mac: measure every new
# or unmeasured ladder effort right away (every 2h via --auto) and top up noisy
# efforts weekly (Sundays after 10:00) using update/measure_effort_tokens.py,
# then land docs/effort-tokens.json as a PR via finish-security.sh.
#
#   scripts/measure-weekly.sh               # full run now
#   scripts/measure-weekly.sh --auto        # fast check: measure new models or Sunday top-up
#   scripts/measure-weekly.sh --install     # run --auto every 2 hours (launchd)
#   scripts/measure-weekly.sh --uninstall
#
# Needs the Claude Code and Codex sign-ins (subscription lanes cost no cash)
# and OPENROUTER_API_KEY in the keychain (roadmodel/OPENROUTER_API_KEY).
# OpenRouter spend stops at ROADMODEL_MEASURE_MAX_USD per run (default $3) and
# ROADMODEL_MEASURE_MAX_WEEKLY_USD over any rolling 7 days (default $6).
#
# Works in its own clone (a checkout of main, never the operator's tree), opens
# the PR, then lands it with private/security-tools/finish-security.sh; that
# step refuses on a real new finding and leaves the PR open.
set -euo pipefail

LABEL="ai.roadmodel.measure-weekly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/roadmodel-measure-weekly.log"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
REPO="${ROADMODEL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
CLONE="${ROADMODEL_MEASURE_CLONE:-$HOME/.cache/roadmodel/measure-clone}"
CACHE_DIR="$HOME/.cache/roadmodel"
LOCK_DIR="$CACHE_DIR/measure-weekly.lock"
TOPUP_STAMP="$CACHE_DIR/measure-last-topup-week"
FAIL_FILE="$CACHE_DIR/measure-last-fail"
FAIL_ISSUE_TITLE="chore(effort-tokens): local measurement run failed"
MAX_USD="${ROADMODEL_MEASURE_MAX_USD:-3}"
MAX_WEEKLY_USD="${ROADMODEL_MEASURE_MAX_WEEKLY_USD:-6}"

say() { echo "measure-weekly: $*"; }

MODE="manual"
case "${1:-}" in
  --install)
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SELF</string><string>--auto</string></array>
  <key>StartInterval</key><integer>7200</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>ROADMODEL_REPO</key><string>$REPO</string>
  </dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    say "installed: every 2 hours (--auto), log $LOG"
    exit 0
    ;;
  --uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    say "uninstalled"
    exit 0
    ;;
  --auto)
    MODE="auto"
    ;;
  "") ;;
  *)
    echo "usage: $0 [--auto | --install | --uninstall]" >&2
    exit 2
    ;;
esac

mkdir -p "$CACHE_DIR"

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    return 0
  fi
  local old_pid=""
  if [ -f "$LOCK_DIR/pid" ]; then
    old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  fi
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    say "another run is active (pid $old_pid); skipping"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    return 0
  fi
  say "could not acquire lock $LOCK_DIR; skipping"
  exit 0
}

release_lock() {
  rm -rf "$LOCK_DIR" 2>/dev/null || true
}

MAIN_SHA=""
UNMEASURED_MODELS=""

refresh_subscription_clis() {
  local targets="${1:-all}"
  if [ "$targets" = "all" ] || [[ ",$targets," == *"gpt-"* ]]; then
    npm install -g @openai/codex@latest >/dev/null 2>&1 || true
  fi
  if [ "$targets" = "all" ] || [[ ",$targets," == *"claude-"* ]]; then
    npm install -g @anthropic-ai/claude-code@latest >/dev/null 2>&1 || true
  fi
}

close_failure_issue() {
  local num=""
  num="$(gh issue list --repo nathanramoscfa/roadmodel --state open --limit 100 --json number,title \
    -q ".[] | select(.title == \"$FAIL_ISSUE_TITLE\") | .number" 2>/dev/null | head -n1 || true)"
  if [ -n "$num" ]; then
    gh issue close "$num" --repo nathanramoscfa/roadmodel \
      --comment "Effort-token measurement run succeeded on $(date '+%Y-%m-%d %H:%M')." >/dev/null 2>&1 || true
  fi
}

on_err() {
  local rc=$?
  local line="${1:-?}"
  local cmd="${2:-?}"
  set +e
  local now_ts
  now_ts="$(date +%s)"
  printf '%s|%s|%s\n' "$now_ts" "${MAIN_SHA:-unknown}" "${UNMEASURED_MODELS:-}" > "$FAIL_FILE" 2>/dev/null || true
  local tail_log=""
  if [ -f "$LOG" ]; then
    tail_log="$(tail -n 40 "$LOG" 2>/dev/null || true)"
  fi
  local body
  body="Local Mac effort-token measurement (\`scripts/measure-weekly.sh\`) failed on $(date -u '+%Y-%m-%dT%H:%M:%SZ') at line ${line} (exit ${rc}):

- Mode: \`${MODE}\`
- Command: \`${cmd}\`
- \`origin/main\`: \`${MAIN_SHA:-unknown}\`
- Unmeasured models: \`${UNMEASURED_MODELS:-none}\`

\`\`\`text
${tail_log}
\`\`\`"
  local num=""
  num="$(gh issue list --repo nathanramoscfa/roadmodel --state open --limit 100 --json number,title \
    -q ".[] | select(.title == \"$FAIL_ISSUE_TITLE\") | .number" 2>/dev/null | head -n1 || true)"
  if [ -n "$num" ]; then
    gh issue edit "$num" --repo nathanramoscfa/roadmodel --body "$body" >/dev/null 2>&1 || true
  else
    gh issue create --repo nathanramoscfa/roadmodel --title "$FAIL_ISSUE_TITLE" --body "$body" >/dev/null 2>&1 || true
  fi
  exit "$rc"
}

acquire_lock
trap release_lock EXIT
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

if [ ! -d "$CLONE/.git" ]; then
  mkdir -p "$(dirname "$CLONE")"
  git clone -q "$(git -C "$REPO" remote get-url origin)" "$CLONE"
fi
cd "$CLONE"
git fetch -q --tags --force origin
MAIN_SHA="$(git rev-parse origin/main)"
git checkout -q main
git reset -q --hard origin/main
[ -e private ] || ln -s "$REPO/private" private

RUN_TOPUP=""
if [ "$MODE" = "auto" ]; then
  UNMEASURED_MODELS="$(
    uv run --quiet --no-project --with requests --with beautifulsoup4 \
      python update/measure_effort_tokens.py --unmeasured | cut -d: -f1 | paste -sd, -
  )"
  DOW="$(date +%u)"
  HOUR="$(date +%H)"
  WEEK="$(date +%G-W%V)"
  LAST_WEEK=""
  if [ -f "$TOPUP_STAMP" ]; then
    LAST_WEEK="$(cat "$TOPUP_STAMP" 2>/dev/null || true)"
  fi
  if [ -n "$UNMEASURED_MODELS" ]; then
    if [ -f "$FAIL_FILE" ]; then
      IFS='|' read -r fail_ts fail_sha fail_models < "$FAIL_FILE" || true
      now_ts="$(date +%s)"
      if [ "$fail_sha" = "$MAIN_SHA" ] && [ "$fail_models" = "$UNMEASURED_MODELS" ] \
        && [ -n "$fail_ts" ] && [ "$((now_ts - fail_ts))" -lt 43200 ]; then
        say "backoff active after recent failure on $MAIN_SHA ($UNMEASURED_MODELS); skipping"
        exit 0
      fi
    fi
    refresh_subscription_clis "$UNMEASURED_MODELS"
    say "$(date '+%Y-%m-%d %H:%M') auto: measuring unmeasured models ($UNMEASURED_MODELS; cap \$$MAX_USD, weekly \$$MAX_WEEKLY_USD)"
    uv run --quiet --no-project --with requests --with beautifulsoup4 \
      python update/measure_effort_tokens.py \
      --models "$UNMEASURED_MODELS" \
      --rounds 1 \
      --max-samples 12 \
      --max-usd "$MAX_USD" \
      --max-weekly-usd "$MAX_WEEKLY_USD"
  elif [ "$DOW" -eq 7 ] && [ "$((10#$HOUR))" -ge 10 ] && [ "$LAST_WEEK" != "$WEEK" ]; then
    RUN_TOPUP="$WEEK"
    say "$(date '+%Y-%m-%d %H:%M') auto: weekly Sunday top-up ($WEEK; cap \$$MAX_USD, weekly \$$MAX_WEEKLY_USD)"
    uv run --quiet --no-project --with requests --with beautifulsoup4 \
      python update/measure_effort_tokens.py \
      --max-samples 24 \
      --max-usd "$MAX_USD" \
      --max-weekly-usd "$MAX_WEEKLY_USD"
  else
    say "$(date '+%Y-%m-%d %H:%M') auto: nothing unmeasured and weekly top-up not due; exiting"
    rm -f "$FAIL_FILE"
    close_failure_issue
    exit 0
  fi
else
  refresh_subscription_clis all
  say "$(date '+%Y-%m-%d %H:%M') start (OpenRouter cap \$$MAX_USD, weekly \$$MAX_WEEKLY_USD)"
  uv run --quiet --no-project --with requests --with beautifulsoup4 \
    python update/measure_effort_tokens.py \
    --max-samples 24 \
    --max-usd "$MAX_USD" \
    --max-weekly-usd "$MAX_WEEKLY_USD"
fi

if git diff --quiet -- docs/effort-tokens.json; then
  say "docs/effort-tokens.json unchanged; nothing to land"
  [ -n "$RUN_TOPUP" ] && printf '%s\n' "$RUN_TOPUP" > "$TOPUP_STAMP"
  rm -f "$FAIL_FILE"
  close_failure_issue
  exit 0
fi

DAY="$(date +%F)"
BRANCH="chore/effort-tokens-$DAY"
git checkout -q -B "$BRANCH"
git add docs/effort-tokens.json
git commit -q -m "chore(effort-tokens): weekly measurement $DAY"
git push -q --force -u origin "$BRANCH"

for old in $(gh pr list --state open --search "head:chore/effort-tokens-" --json number,headRefName \
    -q ".[] | select(.headRefName | startswith(\"chore/effort-tokens-\") and . != \"$BRANCH\") | .number" 2>/dev/null || true); do
  gh pr close "$old" --delete-branch --comment "Superseded by $DAY token measurement." || true
done

if ! gh pr view "$BRANCH" --json number >/dev/null 2>&1; then
  gh pr create --base main --head "$BRANCH" \
    --title "chore(effort-tokens): token measurement $DAY" \
    --body "Automated run of scripts/measure-weekly.sh: token measurements for new or noisy ladder efforts (update/measure_effort_tokens.py, OpenRouter cap \$$MAX_USD/run, \$$MAX_WEEKLY_USD/week). Data only."
fi

if [ -x private/security-tools/finish-security.sh ]; then
  private/security-tools/finish-security.sh
else
  say "no private/security-tools/finish-security.sh: PR left open for the re-bind"
fi

[ -n "$RUN_TOPUP" ] && printf '%s\n' "$RUN_TOPUP" > "$TOPUP_STAMP"
rm -f "$FAIL_FILE"
close_failure_issue
say "$(date '+%Y-%m-%d %H:%M') done"
