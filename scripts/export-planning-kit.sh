#!/usr/bin/env bash
# Export the roadmodel planning kit using the published wheel.
# Usage: export-planning-kit.sh TARGET [--dest DIR] [--user-context FILE] [--force] [--local]
# Default: use roadmodel >=0.2.81, bootstrapping an isolated temporary venv if needed.
# --local explicitly reads this reviewed checkout's code and docs, including edits.
# --ref is retired: use a released wheel, or review a checkout and use --local.
set -euo pipefail

usage() { sed -n '2,6p' "$0" | sed 's/^# //'; }
TARGET=""
DEST_SUBDIR="planning"
MODE="release"
FORCE="0"
USER_CONTEXT="${XDG_CONFIG_HOME:-$HOME/.config}/roadmodel/user-context.md"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST_SUBDIR="${2:?--dest needs a value}"; shift 2 ;;
    --user-context) USER_CONTEXT="${2:?--user-context needs a value}"; shift 2 ;;
    --force) FORCE="1"; shift ;;
    --local) MODE="local"; shift ;;
    --ref) echo "ERROR: --ref is retired; use a released wheel or a reviewed checkout with --local." >&2; exit 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "ERROR: unknown option." >&2; exit 2 ;;
    *) if [[ -z "$TARGET" ]]; then TARGET="$1"; shift
       else echo "ERROR: unexpected argument." >&2; exit 2; fi ;;
  esac
done
if [[ -z "$TARGET" || ! -d "$TARGET" ]]; then
  echo "ERROR: target directory does not exist." >&2; exit 2
fi
PYTHON="${ROADMODEL_PYTHON:-python3}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$MODE" == "release" ]]; then
  EXPORT_PYTHON="$PYTHON"
  if ! "$PYTHON" -I -X utf8 -c 'from importlib.metadata import version; from roadmodel import private_files; assert tuple(map(int, version("roadmodel").split("."))) >= (0, 2, 81)' 2>/dev/null; then
    umask 077
    BOOTSTRAP="$(mktemp -d)"
    trap 'rm -rf -- "$BOOTSTRAP"' EXIT
    "$PYTHON" -I -X utf8 -m venv "$BOOTSTRAP/venv"
    EXPORT_PYTHON="$BOOTSTRAP/venv/bin/python"
    if [[ ! -f "$EXPORT_PYTHON" ]]; then EXPORT_PYTHON="$BOOTSTRAP/venv/Scripts/python.exe"; fi
    "$EXPORT_PYTHON" -I -X utf8 -m pip install --disable-pip-version-check --only-binary=:all: 'roadmodel>=0.2.81,<0.3'
  fi
  ARGS=(export-kit "$TARGET" --dest "$DEST_SUBDIR" --user-context "$USER_CONTEXT")
  if [[ "$FORCE" == "1" ]]; then ARGS+=(--force); fi
  "$EXPORT_PYTHON" -I -X utf8 -m roadmodel "${ARGS[@]}"
  exit 0
fi

# Local developer mode uses the same stdlib path policy as the released CLI.
# No code or instructions are fetched from a moving Git ref.
"$PYTHON" -I -X utf8 - "$REPO_ROOT" "$TARGET" "$DEST_SUBDIR" "$USER_CONTEXT" "$FORCE" <<'PYLOCAL'
import importlib.util
import sys
from pathlib import Path

repo, project, destination, source, force = sys.argv[1:]
root = Path(repo)
spec = importlib.util.spec_from_file_location("private_files", root / "src/roadmodel/private_files.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
files = {
    "model-selector.txt": "model-selector.txt",
    "model-tier-cost-scale.md": "model-tier-cost-scale.md",
    "settings-display.md": "settings-display.md",
    "templates/project-roadmap-template.md": "templates/project-roadmap-template.md",
    "templates/phase-roadmap-template.md": "templates/phase-roadmap-template.md",
    "templates/planning-kit-how-to-use.md": "HOW-TO-USE.md",
    "templates/prompt-project-roadmap.md": "prompts/project-roadmap.md",
    "templates/prompt-phase-roadmap.md": "prompts/phase-roadmap.md",
}
try:
    project = Path(project).resolve(strict=True)
    outputs = [(root / "docs" / name, module.safe_destination(project, Path(destination) / rel))
               for name, rel in files.items()]
    context = module.protect_export(project, Path(destination) / "user-context.md")
    contents = [(path.read_bytes(), output) for path, output in outputs]
    if any(not data for data, _ in contents) or b"<model-selector>" not in contents[0][0]:
        raise ValueError("Incomplete planning kit")
    source = Path(source).expanduser().resolve()
    if context.exists() and (force != "1" or not source.is_file()):
        private = module.read_private_output(context)
    elif source.is_file():
        private = source.read_bytes()
    else:
        private = b"# User Context (PLACEHOLDER)\n\nFill in your subscriptions and access preferences.\n"
    for data, output in contents:
        module.atomic_private_write(output, data)
    module.atomic_private_write(context, private)
except (OSError, ValueError):
    print("ERROR: export refused; check source files, destination links and Git exclusions.", file=sys.stderr)
    sys.exit(1)
print("Exported planning kit. Open its HOW-TO-USE.md to continue.")
PYLOCAL
