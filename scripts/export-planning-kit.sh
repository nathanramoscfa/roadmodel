#!/usr/bin/env bash
# scripts/export-planning-kit.sh
#
# Export the roadmodel "planning kit" into another project so an in-editor AI
# (Claude Code, Cursor, etc.) can author project/phase roadmaps WITH per-step
# model recommendations at $0 marginal cost — the AI runs the selector
# algorithm in its own context instead of calling a paid API or MCP server.
#
# Files are fetched fresh from the public roadmodel GitHub repo by default, so
# the kit stays current with the catalog crons (new models, prices, and
# availability exclusions such as a withdrawn flagship). Use --local to copy
# from this clone's working tree instead (offline; reflects uncommitted edits).
#
# Usage:
#   scripts/export-planning-kit.sh <target-project-dir> [options]
#
# Options:
#   --dest <subdir>        Destination subdir inside the target project
#                          (default: planning)
#   --ref <git-ref>        Fetch from this branch/tag/sha (default: main)
#   --local                Copy from this repo's working tree, not GitHub
#   --user-context <path>  Path to user-context.md (default:
#                          $XDG_CONFIG_HOME/roadmodel/user-context.md, else
#                          ~/.config/roadmodel/user-context.md)
#   -h, --help             Show this help and exit

set -euo pipefail

REPO_SLUG="nathanramoscfa/roadmodel"

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

# --- defaults -------------------------------------------------------------
TARGET=""
DEST_SUBDIR="planning"
REF="main"
MODE="remote"
XDG="${XDG_CONFIG_HOME:-$HOME/.config}"
USER_CONTEXT="$XDG/roadmodel/user-context.md"

# --- arg parsing ----------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)         DEST_SUBDIR="${2:?--dest needs a value}"; shift 2 ;;
    --ref)          REF="${2:?--ref needs a value}"; shift 2 ;;
    --local)        MODE="local"; shift ;;
    --user-context) USER_CONTEXT="${2:?--user-context needs a value}"; shift 2 ;;
    -h|--help)      usage; exit 0 ;;
    -*)             echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -z "$TARGET" ]]; then TARGET="$1"; shift
      else echo "ERROR: unexpected argument: $1" >&2; exit 2; fi
      ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "ERROR: target project directory is required." >&2
  usage >&2
  exit 2
fi
if [[ ! -d "$TARGET" ]]; then
  echo "ERROR: target directory does not exist: $TARGET" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$(cd "$TARGET" && pwd)/$DEST_SUBDIR"

# --- source -> destination map -------------------------------------------
# Each entry: "<repo-relative source>::<destination path under $DEST>"
# settings-display.md is the DISPLAY CONTRACT — how the selector's setting
# fields map to the real controls each surface exposes (which dials to show,
# which to omit). `roadmodel export-kit` has always shipped it; omitting it here
# meant shell-exported kits carried the selector without its display rules.
FILES=(
  "docs/model-selector.txt::model-selector.txt"
  "docs/model-tier-cost-scale.md::model-tier-cost-scale.md"
  "docs/settings-display.md::settings-display.md"
  "docs/templates/project-roadmap-template.md::templates/project-roadmap-template.md"
  "docs/templates/phase-roadmap-template.md::templates/phase-roadmap-template.md"
  "docs/templates/planning-kit-how-to-use.md::HOW-TO-USE.md"
)

fetch_one() {  # <src_rel> <dest_abs>
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ "$MODE" == "local" ]]; then
    if [[ ! -f "$REPO_ROOT/$src" ]]; then
      echo "ERROR: source not found in local tree: $REPO_ROOT/$src" >&2
      exit 1
    fi
    cp "$REPO_ROOT/$src" "$dest"
  else
    local url="https://raw.githubusercontent.com/${REPO_SLUG}/${REF}/${src}"
    if ! curl -fsSL "$url" -o "$dest"; then
      echo "ERROR: failed to fetch $url" >&2
      echo "       (check the --ref value and your network connection)" >&2
      exit 1
    fi
  fi
  if [[ ! -s "$dest" ]]; then
    echo "ERROR: fetched an empty file: $dest" >&2
    exit 1
  fi
}

echo "Exporting roadmodel planning kit -> $DEST"
echo "  source: $([[ "$MODE" == local ]] && echo "local tree ($REPO_ROOT)" || echo "github ${REPO_SLUG}@${REF}")"
mkdir -p "$DEST"

for entry in "${FILES[@]}"; do
  src="${entry%%::*}"
  rel="${entry##*::}"
  fetch_one "$src" "$DEST/$rel"
  echo "  + $rel"
done

# --- sanity: confirm we got the real selector, not an error page ----------
if ! grep -q "<model-selector>" "$DEST/model-selector.txt"; then
  echo "ERROR: model-selector.txt is missing its '<model-selector>' marker —" >&2
  echo "       the fetch may have returned an error page. Aborting." >&2
  exit 1
fi

# --- user-context (machine-local; never fetched from GitHub) --------------
if [[ -f "$USER_CONTEXT" ]]; then
  cp "$USER_CONTEXT" "$DEST/user-context.md"
  echo "  + user-context.md (from $USER_CONTEXT)"
else
  cat > "$DEST/user-context.md" <<'PLACEHOLDER'
# User Context (PLACEHOLDER — fill this in)

No user-context.md was found at the default path
($XDG_CONFIG_HOME/roadmodel/user-context.md). Without it, model picks still
work but PLATFORM selection falls back to the selector's generic default order
instead of your real subscriptions.

Create the real file at ~/.config/roadmodel/user-context.md (subscriptions,
API keys, platform preference order) and re-run the exporter, or replace this
placeholder directly. See the roadmodel repo's docs/user-context.example.md
for the schema.
PLACEHOLDER
  echo "  ! user-context.md NOT found at $USER_CONTEXT — wrote a placeholder" >&2
fi

cat <<EOF

Done. Next, in that project open a new AI chat and paste:

  Write the Phase 1 roadmap .md using @${DEST_SUBDIR}/templates/phase-roadmap-template.md
  as the template. For each step's Settings table and Model rationale, run the
  model selector in @${DEST_SUBDIR}/model-selector.txt (prices from
  @${DEST_SUBDIR}/model-tier-cost-scale.md) against @${DEST_SUBDIR}/user-context.md
  — you are the engine, do not call any external API. Honor every availability
  exclusion in the selector, and include a backup model per step.

See @${DEST_SUBDIR}/HOW-TO-USE.md for the full workflow. Re-run this exporter at
the start of each phase to stay current with the catalog.
EOF
