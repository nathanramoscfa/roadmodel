# Phase 1 Release Runbook

This runbook covers the release flow for `roadmodel` introduced in
Phase 1 Step 6 and updated in the CI hardening pass.

## Required GitHub Secrets

- `TEST_PYPI_TOKEN`
- `PYPI_TOKEN`

A follow-up will switch the publish jobs to PyPI OIDC trusted
publishing, at which point both secrets can be revoked.

## Release model (post-hardening)

`.github/workflows/release.yml` has two entry points:

1. **Tag push** (`push: tags: ['v*']`) → builds, signs with sigstore,
   uploads to TestPyPI. Stops there. The `pypi-upload` and
   `github-release` jobs are gated off this trigger.
2. **`workflow_dispatch`** with a `tag` input → checks out that tag,
   re-builds, re-signs, uploads to PyPI, and creates the GitHub
   Release. This is the manual gate: PyPI is never published as a
   side effect of pushing a tag.

`*-phase-*` tags are excluded from both publish paths; they are
milestone markers only.

## `0.1.x` release flow

1. Update `CHANGELOG.md` for the version (bump version + add a dated
   section).
2. Bump `pyproject.toml` `version` and `src/roadmodel/__init__.py`
   `__version__` to match.
3. Open the change as a PR, merge to `main` after CI is green.
4. Verify manually on macOS and (via the dispatchable
   `verify-pypi.yml`) on Linux that the prior released version still
   installs from PyPI as a sanity check, if the prior version is
   relevant.
5. Tag and push:

   ```bash
   git tag -a v0.1.x-phase-1 -m "Phase 1 milestone for 0.1.x"
   git tag -a v0.1.x-pypi -m "v0.1.x PyPI publish"
   git push origin main v0.1.x-phase-1 v0.1.x-pypi
   ```

6. The tag-push triggers `release.yml`. It runs `build → sign →
   testpypi-upload`. Watch the run finish green.
7. Verify TestPyPI install (optional but recommended):

   ```bash
   python3.11 -m venv .venv-testpypi
   . .venv-testpypi/bin/activate
   python -m pip install --upgrade pip
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "roadmodel==0.1.x"
   roadmodel --help
   ```

8. **Manual gate:** when ready to publish to PyPI, dispatch the
   workflow:

   ```bash
   gh workflow run release.yml -f tag=v0.1.x-pypi
   ```

   This run executes `build → sign → pypi-upload → github-release`
   using the same tag's source. The `pypi-production` environment is
   still declared on `pypi-upload`, so if/when GitHub's billing-plan
   gate is satisfied, required-reviewer approval will also fire here.
9. Confirm PyPI upload success and that the GitHub Release appears
   with the CHANGELOG entry as the body.
10. Verify PyPI install on Linux via the dispatchable workflow:

    ```bash
    gh workflow run verify-pypi.yml -f version=0.1.x
    ```

11. Record the verification in `docs/phase01-qa-findings.md`.

## Why two tags

- `v0.1.x-phase-1` — Phase 1 milestone marker. Never publishes.
- `v0.1.x-pypi` — the PyPI publishing tag. Drives the tag-push half
  of the workflow and is the value passed to `workflow_dispatch`.

`v0.1.x` is a pre-existing historical tag (originally created when the
release flow was simpler) and is no longer pushed by this runbook.

## Stub `0.0.0` claim (historical)

`0.0.0` exists intentionally on PyPI as a placeholder release used to
claim the `roadmodel` project name before publishing `0.1.0`. The
sequence used was:

1. Branch from `main`, set `pyproject.toml` version to `0.0.0`.
2. Tag and push `v0.0.0` (or a re-attempt suffix like `v0.0.0-r1`).
3. Approve the `pypi-production` environment when prompted
   (historical; with the new dispatch-based gate, this is replaced by
   the `gh workflow run release.yml -f tag=...` step).
4. Confirm `pip install roadmodel==0.0.0` resolves on PyPI.
5. Reset `pyproject.toml` to the real version on `main`.

The stub remains live on PyPI and is intentionally lightweight; the
real release is `0.1.0` and later.
