# Phase 1 QA Findings

This document rolls up Phase 1 verification: static checks
`scripts/verify-phase01.sh` (checks 1–33), targeted pytest surfaces,
and manual install evidence. Automation mapping follows
`private/phase01-roadmap.md` (V1–V7).

## Per-step verification rollup

### Step 1 — Licensing and repo hygiene

- **Static checks:** 1–7 (LICENSE, NOTICE, CONTRIBUTING, COC, SECURITY,
  GitHub templates).
- **Pytest:** none specific to this step.
- **Manual result:** **PASS** — files present; `LICENSE` matches the
  Apache 2.0 header pattern enforced by check 2.

### Step 2 — Rename sweep (previous package name → `roadmodel`)

- **Static checks:** 8–9 (git grep contract for `model[-_]selector`;
  schema/freshness modules compile).
- **Pytest:** `tests/test_doc_schema.py`, `tests/test_freshness.py`
  (also exercised under `--py` / `--post` as V2.2).
- **Manual result:** **PASS** — check 8 allowlists the three canonical
  bundled-doc paths plus filename / narration references; no stray
  legacy project slug hits.

### Step 3 — Packaging scaffold

- **Static checks:** 10–15 (`pyproject.toml`, `hatch_build.py`,
  `__version__`, `.gitignore` data dir, bundled doc list).
- **Pytest:** `tests/test_packaging.py` under the main CI matrix
  (wheel layout).
- **Manual result:** **PASS** — `python -m build` produces a wheel
  whose version matches `pyproject.toml` (V3.2 / `--cli`).

### Step 4 — CLI implementation

- **Static checks:** 16–22 (module tree, fixtures, Click wiring,
  `parse_response` keys).
- **Pytest:** `tests/test_cli.py` (V4.2 under `--post`).
- **Manual result:** **PASS** — `--cli` / `--post` smoke runs
  `roadmodel --help` and `context init` + `context path` under an
  isolated `HOME`.

### Step 5 — Public documentation

- **Static checks:** 23–26 (README install line, CHANGELOG 0.1.0
  section, BYO key doc env vars, user-context default path + override).
- **Pytest:** none specific.
- **Manual result:** **PASS** — strings verified by static checks.

### Step 6 — CI and release

- **Static checks:** 27–29 (`release.yml` Sigstore hook, `tests.yml`
  ruff/mypy text, `tests/test_ci_smoke.py`).
- **Pytest:** `tests/test_ci_smoke.py` (YAML smoke in CI).
- **Manual result:** **PASS** — Sigstore action id present; full lint
  matrix lives in `tests.yml`.

### Step 7 — QA + verification script

- **Static checks:** 30–33 (this script + executable bit, this doc,
  `private/phase01-roadmap.md`, `phase-verify.yml` matrix entry `1`).
- **Pytest:** none beyond the default suite invoked by
  `./scripts/verify-phase01.sh` (static + `pytest -x tests/`).
- **Manual result:** **PASS** — canonical `verify-phase01.sh` template
  landed; CI runs `--fast` only (under 30 seconds on Ubuntu).

## Manual macOS + Linux TestPyPI installation verification

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

## Pre-ship items

- **Doc-bundled recommender:** v0.1.x ships the Anthropic/OpenAI/Google
  BYO-key path against the bundled selector docs. **Phase 2** will add
  the Python scoring engine, platform-aware cost comparison, and MCP;
  the BYO-key flow remains through **Phase 3** per the product roadmap.
- **Private planning paths:** `private/phase01-roadmap.md` is maintained
  locally (gitignored from the public tree). Check 32 records **PASS**
  on GitHub Actions when the file is absent because CI cannot materialise
  gitignored paths; local maintainer clones should still carry the file
  for human review of the V1–V7 spec.
- **`gitleaks` (V1.2):** optional in `--post`; Ubuntu CI images may or
  may not ship the binary — the script logs `[SKIP]` when absent.
- **`gh pr checks` (post):** optional; requires an authenticated `gh`
  session and an open PR for the current branch.
- **Interpreter selection:** `scripts/verify-phase01.sh` prefers, in
  order: `ROADMODEL_VERIFY_PYTHON`, `./.venv/bin/python`, `python3.11`,
  then `python3`. `requires-python >= 3.11` means plain `python3` on
  older macOS/Xcode installs is unsuitable for wheel install smoke.

## Notes

- `0.0.0` exists intentionally on PyPI as a placeholder release used only
  to claim the `roadmodel` project name before publishing `0.1.0`.
- CI: [.github/workflows/phase-verify.yml](../.github/workflows/phase-verify.yml)
  runs `bash scripts/verify-phase${{ matrix.phase }}.sh --fast` on every
  push and pull request to `main` (matrix starts at `phase: [1]` for
  forward-compatible expansion).
