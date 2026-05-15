# Phase 1 Release Runbook

This runbook covers the Step 6 release flow for `roadmodel`.

## Required GitHub Secrets

- `TEST_PYPI_TOKEN`
- `PYPI_TOKEN`

## Stub `0.0.0` Claim Sequence

Use this sequence once to claim the `roadmodel` name on TestPyPI and PyPI
before publishing `0.1.0`.

1. Create a short-lived branch from `main`.
2. Change `pyproject.toml` version to `0.0.0`.
3. Commit and push branch.
4. Tag and push `v0.0.0` to trigger `.github/workflows/release.yml`.
5. Approve the `pypi-production` environment when prompted.
6. Verify install:

```bash
python -m venv .venv-claim
. .venv-claim/bin/activate
python -m pip install --upgrade pip
pip install roadmodel==0.0.0
```

7. Merge/reset version on `main` back to `0.1.0`.

## `v0.1.0` Tag Flow

1. Update `CHANGELOG.md` date for `0.1.0` to the real tag date.
2. Ensure manual TestPyPI verification is complete on macOS and Linux and
   recorded in `docs/phase01-qa-findings.md`.
3. Tag and push:

```bash
git tag -a v0.1.0-phase-1 -m "Phase 1: OSS CLI on PyPI"
git tag -a v0.1.0-pypi -m "v0.1.0 PyPI publish"
git push origin main v0.1.0-phase-1 v0.1.0-pypi
```

Note: `release.yml` skips publish/release jobs for `*-phase-*` tags, so
`v0.1.0-phase-1` is a milestone marker and `v0.1.0-pypi` is the publishing
tag when `v0.1.0` already exists historically.

4. Monitor `.github/workflows/release.yml`.
5. Approve `pypi-production` after `testpypi-upload` succeeds.
6. Confirm PyPI upload success and GitHub Release publication.

## PR Description Note (Required)

Include this in the PR description:

> `0.0.0` exists intentionally as a placeholder release to claim the PyPI
> project name (`roadmodel`) before the real `0.1.0` launch. This reduces
> typosquatting risk during the release window and has no runtime impact.
