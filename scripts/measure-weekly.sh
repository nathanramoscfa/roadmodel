#!/bin/bash
# Weekly token measurement on the operator's Mac: measure every ladder effort
# docs/effort-tokens.json lacks or knows too loosely
# (update/measure_effort_tokens.py), and land the file as a PR.
#
#   scripts/measure-weekly.sh               # run now
#   scripts/measure-weekly.sh --install     # run it every Sunday at 10:00 (launchd)
#   scripts/measure-weekly.sh --uninstall
#
# It needs what only this machine has: the Claude Code and Codex sign-ins (the
# subscription lanes cost no cash) and OPENROUTER_API_KEY in the keychain
# (roadmodel/OPENROUTER_API_KEY). OpenRouter spend stops at
# ROADMODEL_MEASURE_MAX_USD a run (default $3; prepaid credits, so never past
# the balance). A new model's efforts are derived from its measured ones (≈ in
# a roadmap ladder) until this runs. The subscription lanes cost no cash, so a
# heavy-tailed level (Fable 5.1 at max) may take up to 24 samples a task.
#
# It works in its own clone (a checkout of main, never the operator's tree),
# opens the PR, then lands it with private/security-tools/finish-security.sh,
# the re-bind every PR needs (docs/effort-tokens.json is not a catalog data
# path); that step refuses on a real new finding and leaves the PR open.
set -euo pipefail

LABEL="ai.roadmodel.measure-weekly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/roadmodel-measure-weekly.log"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
REPO="${ROADMODEL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
CLONE="${ROADMODEL_MEASURE_CLONE:-$HOME/.cache/roadmodel/measure-clone}"
MAX_USD="${ROADMODEL_MEASURE_MAX_USD:-3}"

say() { echo "measure-weekly: $*"; }

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
  <array><string>/bin/bash</string><string>$SELF</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
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
    say "installed: Sundays 10:00, log $LOG"
    exit 0
    ;;
  --uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    say "uninstalled"
    exit 0
    ;;
  "") ;;
  *)
    echo "usage: $0 [--install | --uninstall]" >&2
    exit 2
    ;;
esac

say "$(date '+%Y-%m-%d %H:%M') start (OpenRouter cap \$$MAX_USD)"
if [ ! -d "$CLONE/.git" ]; then
  mkdir -p "$(dirname "$CLONE")"
  git clone -q "$(git -C "$REPO" remote get-url origin)" "$CLONE"
fi
cd "$CLONE"
git fetch -q origin
git checkout -q main
git reset -q --hard origin/main
[ -e private ] || ln -s "$REPO/private" private

uv run --quiet --no-project --with requests --with beautifulsoup4 \
  python update/measure_effort_tokens.py --max-usd "$MAX_USD" --max-samples 24

if git diff --quiet -- docs/effort-tokens.json; then
  say "docs/effort-tokens.json unchanged; nothing to land"
  exit 0
fi

DAY="$(date +%F)"
BRANCH="chore/effort-tokens-$DAY"
git checkout -q -B "$BRANCH"
git add docs/effort-tokens.json
git commit -q -m "chore(effort-tokens): weekly measurement $DAY"
git push -q --force -u origin "$BRANCH"
if ! gh pr view "$BRANCH" --json number >/dev/null 2>&1; then
  gh pr create --base main --head "$BRANCH" \
    --title "chore(effort-tokens): weekly measurement $DAY" \
    --body "Weekly run of scripts/measure-weekly.sh: token measurements for new or noisy ladder efforts (update/measure_effort_tokens.py, OpenRouter cap \$$MAX_USD). Data only."
fi

if [ -x private/security-tools/finish-security.sh ]; then
  private/security-tools/finish-security.sh
else
  say "no private/security-tools/finish-security.sh: PR left open for the re-bind"
fi
say "$(date '+%Y-%m-%d %H:%M') done"
