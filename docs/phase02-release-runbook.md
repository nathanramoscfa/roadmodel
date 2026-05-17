# Phase 2 Release Runbook

This runbook covers the release flow for `roadmodel` starting with
Phase 2's v0.2.0 cut. The Phase 1 runbook
([docs/phase01-release-runbook.md](phase01-release-runbook.md)) is
preserved as historical context for the v0.1.x two-tag scheme; from
v0.2.0 onward the flow is single-tag with OIDC trusted publishing
throughout.

## What changed from Phase 1

- **One tag per release.** The `vX.Y.Z-phase-N` / `vX.Y.Z-pypi`
  split is gone. The tag itself is `vX.Y.Z` (signed) and drives the
  full publish path.
- **OIDC end to end.** PyPI and TestPyPI publishes use trusted
  publishing (the GitHub OIDC token is exchanged for a short-lived
  index token). No `TEST_PYPI_TOKEN` / `PYPI_TOKEN` secrets are read
  by `release.yml`.
- **Verify-PyPI matrix runs inline.** `verify-pypi.yml` is called
  as a reusable workflow from `release.yml`'s tag-push path, so the
  Ubuntu+macOS × Python 3.11/3.12/3.13 install smoke is automatic
  before the PyPI promote gate.
- **Signed tags required.** `git tag -s` (SSH or GPG signing
  configured on the maintainer's machine). The signature is
  verifiable with `git tag -v vX.Y.Z` and the
  `gpg.ssh.allowedSignersFile` configured locally.

## `0.2.x` release flow

1. **CHANGELOG date PR.** On a feature branch off `main`, set the
   `## [0.2.x] — YYYY-MM-DD` heading in `CHANGELOG.md` to the UTC
   date you intend to push the tag. Commit, open the PR, merge after
   CI is green. This is the only content change in the PR.
2. **Sign and push the tag** from a clean, up-to-date `main`:

   ```bash
   git switch main && git pull --ff-only origin main
   git tag -s v0.2.x -m "roadmodel 0.2.x"
   git tag -v v0.2.x   # confirm "Good \"git\" signature"
   git push origin v0.2.x
   ```

3. **Watch the tag-push `release.yml` run.** Jobs in order:
   `build → sign (sigstore) → testpypi-upload →
   verify-testpypi (matrix)`. The `pypi-upload` and
   `github-release` jobs are skipped on tag-push by design.
4. **Halt if any matrix entry is red.** Every Ubuntu+macOS ×
   Python 3.11/3.12/3.13 verify cell must be green before the
   PyPI promote dispatch. If a cell fails, do not dispatch — triage,
   fix on `main`, and restart the release at v0.2.(x+1). Do not
   force-push or replace the tag.
5. **Dispatch the PyPI promote gate** once verify-testpypi is fully
   green:

   ```bash
   gh workflow run release.yml -f tag=v0.2.x
   ```

   This run executes `build → sign → pypi-upload → github-release`
   against the same tag's source. The `pypi-production` GitHub
   environment is declared on `pypi-upload`; if/when the repo's
   billing plan supports required-reviewer rules, they will apply
   here automatically.
6. **Verify the GitHub Release.** The `github-release` job creates
   it from the CHANGELOG section. Confirm:
   - Title equals `roadmodel 0.2.x` (the workflow defaults the title
     to the tag name — rename if needed:
     `gh release edit v0.2.x --title "roadmodel 0.2.x"`).
   - Body is the `[0.2.x]` section of CHANGELOG.md verbatim.
   - Assets include the wheel, sdist, and `.sigstore.json`
     signature bundles for both.
   - `isPrerelease` is `false`.
7. **Manual macOS install confirmation.** The verify-pypi matrix
   covers Ubuntu and macOS for TestPyPI; production PyPI requires
   one explicit confirmation. From a fresh venv:

   ```bash
   python3.12 -m venv .venv-verify
   . .venv-verify/bin/activate
   python -m pip install --upgrade pip --no-cache-dir
   pip install --no-cache-dir "roadmodel==0.2.x"
   roadmodel --help
   python -c "import roadmodel; print(roadmodel.__version__)"
   pip install --no-cache-dir "roadmodel[mcp]==0.2.x"
   which roadmodel-mcp
   ```

   PyPI's CDN can lag a few seconds after the publish; if the first
   `pip install` cannot find the version, retry without
   `--no-cache-dir` after ~30s. Record the run in the version
   section below.
8. **Record the run** under the version section in this file: tag,
   tag-push run URL, dispatch run URL, TestPyPI URL, PyPI URL, and
   the macOS manual install confirmation timestamp.

## v0.2.0 (Phase 2)

- **Tag:** `v0.2.0`, signed with SSH (ed25519). Verifiable via
  `git tag -v v0.2.0`. Dated `2026-05-17` (UTC) in CHANGELOG.md.
- **Tag-push `release.yml` run:**
  <https://github.com/nathanramoscfa/roadmodel/actions/runs/25976682110>
  — `build`, `sign`, `testpypi-upload`, and all six
  `verify-testpypi` matrix cells (Ubuntu+macOS × Python
  3.11/3.12/3.13) green.
- **TestPyPI:** <https://test.pypi.org/project/roadmodel/0.2.0/>.
- **PyPI promote dispatch run:**
  <https://github.com/nathanramoscfa/roadmodel/actions/runs/25976747458>
  — `build`, `sign`, `pypi-upload`, `github-release` green.
- **PyPI:** <https://pypi.org/project/roadmodel/0.2.0/>.
- **GitHub Release:**
  <https://github.com/nathanramoscfa/roadmodel/releases/tag/v0.2.0>
  — title `roadmodel 0.2.0`, body = `[0.2.0]` CHANGELOG section
  verbatim, assets include `roadmodel-0.2.0-py3-none-any.whl`,
  `roadmodel-0.2.0.tar.gz`, and `.sigstore.json` signatures for
  both. Not marked pre-release.
- **macOS manual install confirmation:** 2026-05-17T00:29:08Z on
  macOS-26.5-arm64-arm-64bit / CPython 3.12.13.
  `pip install --no-cache-dir "roadmodel==0.2.0"` then
  `pip install --no-cache-dir "roadmodel[mcp]==0.2.0"` both
  succeeded in a fresh venv; `roadmodel --help` and
  `roadmodel-mcp` entry point both wired and importable
  (`roadmodel.__version__ == "0.2.0"`).
