# Phase 1 QA Findings

## Step 6 Release Verification

Status: **PASS** for both `roadmodel==0.1.0` and `roadmodel==0.1.1` on
PyPI. `0.1.1` is the security-hardened follow-up to `0.1.0` (drops the
repo-walk fallback, masks the api_key in `Config.__repr__`, atomically
creates user-context.md with `0o600`, sanitizes provider fallback
error strings); see the
[v0.1.1 GitHub Release](https://github.com/nathanramoscfa/roadmodel/releases/tag/v0.1.1-pypi)
for the full notes.

### 0.1.1 — macOS (Python 3.11)

- Date: 2026-05-15
- Host: macOS-26.5-arm64 (Apple Silicon)
- Python: 3.11.15 (Homebrew `python@3.11`)
- TestPyPI install (post tag-push, before manual dispatch to PyPI):
  `pip install --index-url https://test.pypi.org/simple/
  --extra-index-url https://pypi.org/simple/ roadmodel==0.1.1` — green,
  `roadmodel --help` exit 0, `__version__ == "0.1.1"`.
- PyPI install (post manual dispatch): `pip install roadmodel==0.1.1` —
  green, same smoke output.

### 0.1.1 — Linux (Python 3.11 + 3.12 + 3.13, ubuntu-latest)

- Workflow run:
  [25901738047](https://github.com/nathanramoscfa/roadmodel/actions/runs/25901738047)
  on 2026-05-15. All three matrix legs green; `roadmodel --help`
  exit 0 and `__version__ == "0.1.1"` on each.
- Re-run rationale: an earlier dispatch
  ([25901715925](https://github.com/nathanramoscfa/roadmodel/actions/runs/25901715925))
  succeeded on 3.11 and 3.13 but failed on 3.12 because the install ran
  during the PyPI index propagation window (~minutes after upload).
  Re-dispatched after the propagation completed; all legs green.

### 0.1.0 — macOS (Python 3.11 clean venv)

- Date: 2026-05-15
- Host: macOS-26.5-arm64 (Apple Silicon)
- Python: 3.11.15 (Homebrew `python@3.11`)
- Note: pre-hardening release. The audit summary further down records
  why it remained safe to leave live alongside 0.1.1.
- Steps run:

  ```bash
  python3.11 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip
  pip install roadmodel==0.1.0
  which roadmodel
  roadmodel --help
  python -c "import roadmodel; print(roadmodel.__version__)"
  ```

- Result:
  - `pip install roadmodel==0.1.0` resolved and installed cleanly from PyPI.
  - `which roadmodel` returned the venv-scoped entry point.
  - `roadmodel --help` exited 0 and printed the expected `Usage`/`Commands`
    block including `catalog`, `context`, `recommend`, `version`.
  - `roadmodel.__version__` reported `0.1.0`.
  - Installed dependency set matched the resolver output expected from
    `pyproject.toml` (`anthropic`, `click`, `google-genai`, `openai` + transitive).

### 0.1.0 — Linux (Python 3.11 + 3.12 + 3.13 clean venv, ubuntu-latest)

Verification is performed via the dispatchable workflow at
[.github/workflows/verify-pypi.yml](../.github/workflows/verify-pypi.yml).

To re-run on demand for any version:

```bash
gh workflow run verify-pypi.yml -f version=0.1.0
```

- Workflow run: [25900737794](https://github.com/nathanramoscfa/roadmodel/actions/runs/25900737794)
  on 2026-05-15 against `roadmodel==0.1.0`. Each matrix leg installs
  from PyPI into a clean venv on `ubuntu-latest` and asserts
  `roadmodel --help` exits 0 and `roadmodel.__version__ == "0.1.0"`.
- Result: **all three legs green**.
  - `install-smoke (3.11)` — Python 3.11.15 on
    `Linux-6.17.0-1010-azure-x86_64-with-glibc2.39`, 21s.
  - `install-smoke (3.12)` — 17s.
  - `install-smoke (3.13)` — 20s.
- Smoke output (3.11, representative):
  - `which roadmodel` → `/home/runner/work/roadmodel/roadmodel/.venv-verify/bin/roadmodel`
  - `roadmodel --help` exited 0 and printed the same `Usage`/`Commands`
    block recorded in the macOS run.
  - `roadmodel.__version__` reported `0.1.0`.

## Cybersecurity Audit Summary (0.1.0)

A full audit was performed against `roadmodel==0.1.0` as published on PyPI
on 2026-05-15. Conclusion: **release is safe to leave live; no yank
required.**

- Zero CRITICAL / HIGH findings.
- Zero known CVEs in runtime or dev dependencies (`pip-audit`).
- Zero medium-or-high Bandit findings on `src/`.
- Sigstore signature verifies cleanly for both wheel and sdist; OIDC
  identity bound to `refs/tags/v0.1.0-pypi` and
  `.github/workflows/release.yml` at commit `969f2f4`.
- Wheel and sdist contain only intended files (no `private/`, no `.env`,
  no fixtures, no templates).

Hardening items deferred to `0.1.1`:

- M1 — drop or opt-in gate the repo-walk `user-context.md` fallback in
  [src/roadmodel/user_context.py](../src/roadmodel/user_context.py).
- M2 — switch PyPI publish to OIDC trusted publishing; revoke long-lived
  tokens. Requires PyPI Trusted Publisher configuration.
- L1 — mask `api_key` in `Config.__repr__` so `ROADMODEL_DEBUG=1`
  tracebacks rendered by third-party formatters cannot leak it.
- L2 — use `{type(exc).__name__}` in provider bare-`except` fallbacks
  instead of interpolating the full exception.
- L3 — atomic `0o600` create for `user-context.md`; tighten parent dir.
- L4 — enable Ruff `S` (flake8-bandit) rules; add `bandit -r src/` and
  `pip-audit` to CI.
- L5 — pin `pypa/gh-action-pypi-publish` to a commit SHA instead of the
  `release/v1` branch ref.
- I2 — move `/private/` exclusion from `.git/info/exclude` into the
  tracked `.gitignore`.
- L6 — narrow `auto-remediate.yml` `--allowedTools` and switch from
  auto-merge to PR-only.

## Notes

- `0.0.0` exists intentionally on PyPI as a placeholder release used only
  to claim the `roadmodel` project name before publishing `0.1.0`.
- Step 7 will consume this document via `scripts/verify-phase01.sh
  --post` to assert that macOS and Linux PyPI install evidence is
  recorded here.
