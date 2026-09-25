#!/bin/bash
# scripts/release.sh — ship roadmodel to PyPI AND to the production recommender.
#
#   scripts/release.sh [X.Y.Z] [--title "one-line summary"]
#
# Catalog and selector changes reach roadmodel.ai/recommend only through a PyPI
# release plus a floor bump in service/pyproject.toml (a merge alone changes
# /models, not the recommender). This runs every step, and each one is skipped
# when it is already done, so a re-run after a failure resumes where it stopped:
#
#   1. release PR  — version in pyproject.toml, src/roadmodel/__init__.py,
#                    tests/test_packaging.py; [Unreleased] -> [X.Y.Z] — date
#   2. signed tag  — vX.Y.Z on the merged release commit; pushing it builds,
#                    signs, uploads to TestPyPI and verifies the install
#   3. PyPI        — the release.yml workflow_dispatch gate + GitHub Release
#   4. floor bump  — service/pyproject.toml roadmodel[recommend]>=X.Y.Z, merged
#                    (the Vercel build cache keeps an older roadmodel otherwise)
#   5. production  — waits until /healthz reports X.Y.Z
#
# X.Y.Z defaults to the next patch version. Release notes come from
# CHANGELOG.md's [Unreleased] section, which must not be empty; an uncommitted
# edit to CHANGELOG.md is carried onto the release branch.
# Runs on the Mac (signed tags use the local SSH signing key).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=scripts/ops-lib.sh
. "$HERE/ops-lib.sh"
cd "$ROOT" || exit 1

version=""
title=""
while [ $# -gt 0 ]; do
  case "$1" in
    --title) title="${2:-}"; shift 2 ;;
    -h | --help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    [0-9]*.[0-9]*.[0-9]*) version="$1"; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

# ---------------------------------------------------------------- preflight
dirty="$(git status --porcelain --untracked-files=no | grep -v ' CHANGELOG.md$' || true)"
[ -n "$dirty" ] && die "working tree has uncommitted changes besides CHANGELOG.md:
$dirty"
git fetch -q origin main --tags || die "git fetch failed"
pyproject_version() { sed -n 's/^version = "\([^"]*\)".*/\1/p' | head -1; }
current="$(pyproject_version <pyproject.toml)"
main_version="$(git show origin/main:pyproject.toml | pyproject_version)"
if [ -z "$version" ]; then
  version="$(python3 -c "v='$main_version'.split('.');v[-1]=str(int(v[-1])+1);print('.'.join(v))")"
  git ls-remote --exit-code --tags origin "v$main_version" >/dev/null 2>&1 || version="$main_version"
fi
tag="v$version"
log "release $tag (main is at $main_version, working tree at $current)"

# ----------------------------------------------------------- 1. release PR
if [ "$main_version" != "$version" ]; then
  branch="release/$tag"
  pr="$(gh pr list -R "$REPO" --head "$branch" --state open --json number -q '.[0].number // empty')"
  if [ -z "$pr" ]; then
    python3 - "$version" <<'EOF' || die "CHANGELOG [Unreleased] is empty — write the release notes there first"
import re, sys
text = open("CHANGELOG.md").read()
m = re.search(r"## \[Unreleased\]\n(.*?)\n## \[", text, re.S)
sys.exit(0 if m and m.group(1).strip() else 1)
EOF
    stashed=0
    if ! git diff --quiet -- CHANGELOG.md; then
      git stash push -q -- CHANGELOG.md || die "could not set the CHANGELOG.md edit aside"
      stashed=1
    fi
    git checkout -q -B "$branch" origin/main || die "could not branch from main"
    if [ "$stashed" = 1 ]; then
      git stash pop -q || die "the CHANGELOG.md edit did not apply on main (it is in git stash)"
    fi
    python3 - "$main_version" "$version" <<'EOF' || die "version bump failed"
import datetime, re, sys
old, new = sys.argv[1], sys.argv[2]
def sub(path, pattern, repl):
    text = open(path).read()
    out, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        sys.exit(f"{path}: pattern not found: {pattern}")
    open(path, "w").write(out)
sub("pyproject.toml", r'(?m)^version = "[^"]+"', f'version = "{new}"')
sub("src/roadmodel/__init__.py", r'__version__ = "[^"]+"', f'__version__ = "{new}"')
sub("tests/test_packaging.py", r'(project\["version"\] == )"[^"]+"', rf'\1"{new}"')
today = datetime.date.today().isoformat()
sub("CHANGELOG.md", r"## \[Unreleased\]\n", f"## [Unreleased]\n\n## [{new}] — {today}\n")
EOF
    if [ -z "$title" ]; then
      # Default title: the first bold lead-in of this version's notes.
      title="$(awk -v v="## [$version]" 'index($0, v) == 1 {f = 1; next} f && /^## \[/ {exit}
        f && match($0, /\*\*[^*]+\*\*/) {print substr($0, RSTART + 2, RLENGTH - 4); exit}' CHANGELOG.md |
        sed 's/\.$//')"
      [ -n "$title" ] || title="release"
    fi
    git add pyproject.toml src/roadmodel/__init__.py tests/test_packaging.py CHANGELOG.md
    git commit -q -m "release: roadmodel $version — $title" || die "commit failed"
    quiet_push -q -f -u origin "$branch" || die "push failed"
    pr="$(gh pr create -R "$REPO" --base main --head "$branch" \
      --title "release: roadmodel $version — $title" \
      --body "Release $version. Notes: the [$version] section of CHANGELOG.md. Opened by scripts/release.sh." |
      grep -oE '[0-9]+$')"
    [ -n "$pr" ] || die "could not open the release PR"
  fi
  log "release PR #$pr"
  merge_when_green "$pr"
fi
git checkout -q main && git pull -q --ff-only origin main || die "could not update main"

# ---------------------------------------------------------------- 2. tag
if ! git ls-remote --exit-code --tags origin "$tag" >/dev/null 2>&1; then
  on_main="$(pyproject_version <pyproject.toml)"
  [ "$on_main" = "$version" ] || die "main is at $on_main, not $version — will not tag"
  git tag -s "$tag" -m "roadmodel $version" 2>/dev/null ||
    { log "signed tag failed — using an annotated tag"; git tag -a "$tag" -m "roadmodel $version"; } ||
    die "could not create $tag"
  quiet_push -q origin "$tag" || die "could not push $tag"
  log "pushed $tag"
fi

# ------------------------------------------- 2b. TestPyPI (tag-push run)
if ! curl -sf "https://pypi.org/pypi/roadmodel/$version/json" >/dev/null; then
  for i in $(seq 1 40); do
    tag_run="$(gh run list -R "$REPO" -w release.yml -e push -b "$tag" -L 1 --json databaseId -q '.[0].databaseId // empty')"
    [ -n "$tag_run" ] && break
    sleep 3
  done
  [ -n "${tag_run:-}" ] || die "no release.yml run for $tag"
  log "TestPyPI build + verify: https://github.com/$REPO/actions/runs/$tag_run"
  gh run watch "$tag_run" -R "$REPO" --exit-status --interval 15 >/dev/null 2>&1 ||
    die "the $tag build/TestPyPI run failed — https://github.com/$REPO/actions/runs/$tag_run (a TestPyPI 'No matching distribution' is CDN lag: gh run rerun $tag_run --failed, then re-run this script)"

  # ------------------------------------------------------------ 3. PyPI
  run_id="$(dispatch_and_wait release.yml -f "tag=$tag")" ||
    die "PyPI publish failed — https://github.com/$REPO/actions/runs/$run_id"
  for i in $(seq 1 60); do
    curl -sf "https://pypi.org/pypi/roadmodel/$version/json" >/dev/null && break
    sleep 15
  done
fi
curl -sf "https://pypi.org/pypi/roadmodel/$version/json" >/dev/null ||
  die "roadmodel $version is not on PyPI yet"
log "roadmodel $version is on PyPI"
for i in $(seq 1 60); do
  pypi_index_has "$version" && break
  [ "$i" = 1 ] && log "waiting for PyPI's package index to serve $version (CDN lag)"
  sleep 15
done
pypi_index_has "$version" || die "PyPI's package index still does not list $version after 15 minutes"

# ---------------------------------------------------------- 4. floor bump
if ! grep -q "roadmodel\[recommend\]>=$version," service/pyproject.toml; then
  branch="chore/service-floor-$version"
  pr="$(gh pr list -R "$REPO" --head "$branch" --state open --json number -q '.[0].number // empty')"
  if [ -z "$pr" ]; then
    git checkout -q -B "$branch" origin/main
    python3 - "$version" <<'EOF' || die "floor bump failed"
import re, sys
p = "service/pyproject.toml"
t = open(p).read()
t2, n = re.subn(r"roadmodel\[recommend\]>=[0-9.]+,", f"roadmodel[recommend]>={sys.argv[1]},", t)
if n != 1:
    sys.exit("roadmodel[recommend] pin not found")
open(p, "w").write(t2)
EOF
    git add service/pyproject.toml
    git commit -q -m "chore(service): bump roadmodel floor to >=$version" || die "commit failed"
    quiet_push -q -f -u origin "$branch" || die "push failed"
    pr="$(gh pr create -R "$REPO" --base main --head "$branch" \
      --title "chore(service): bump roadmodel floor to >=$version" \
      --body "Ships $version to the production recommender. The floor bump is what makes the cached Vercel build install the new release. Opened by scripts/release.sh." |
      grep -oE '[0-9]+$')"
    [ -n "$pr" ] || die "could not open the floor-bump PR"
  fi
  log "floor-bump PR #$pr"
  merge_when_green "$pr"
  git checkout -q main && git pull -q --ff-only origin main
fi

# ---------------------------------------------------------- 5. production
for i in $(seq 1 80); do
  live="$(healthz_version)"
  [ "$live" = "$version" ] && { log "production /healthz reports $version — release complete"; exit 0; }
  sleep 15
done
die "production still reports ${live:-nothing} after 20 minutes — check the roadmodel-api deployment on Vercel"
