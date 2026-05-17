# Phase 2 QA Findings

This document rolls up Phase 2 verification: static checks
`scripts/verify-phase02.sh` (checks 1–33), targeted pytest surfaces,
the v0.2.0 PyPI release artifacts, and manual MCP-client smoke evidence.
Automation mapping follows `private/phase02-roadmap.md` (V1–V7).

## Per-step verification rollup

### Step 1 — Catalog v2 JSON artifact + manual refresh procedure

- **Static checks:** 1–6 (`update/build_catalog.py`, `docs/catalog.json`
  exists + parses, `src/roadmodel/data/catalog.json` bundled,
  `docs/catalog-refresh.md` four sections, `tests/test_catalog_json.py`
  named tests, `update-models.yml` invokes `build_catalog.py`).
- **Pytest:** `tests/test_catalog_json.py` (V1.3 under `--py` and
  `--post`).
- **Determinism:** `--post` V1.2 runs `update/build_catalog.py` twice
  against the same source docs in isolated temp dirs and asserts
  byte-identical output; matches the in-repo
  `test_build_catalog_is_deterministic` test which the cron's
  determinism guard depends on.
- **Manual result:** **PASS** — JSON round-trips with the prose docs,
  cron-rebuilt artifact ships in the wheel.

### Step 2 — Cost estimator module

- **Static checks:** 7–9 (`src/roadmodel/cost.py`,
  `tests/test_cost.py` named tests including the Max Mode 2x branch
  and `AlternativeRejectedError` rejection, `errors.py` class).
- **Pytest:** `tests/test_cost.py` (V2.2 under `--py` and `--post`).
- **Manual result:** **PASS** — every billing branch covered
  (per-token / subscription-included / subscription-pool /
  subscription-or-key), Max Mode pricing rule and the Fast-variant
  rejection path both green.

### Step 3 — CLI surface upgrade (v0.2.0 candidate)

- **Static checks:** 10–15 (`__version__` literal `"0.2.0"`,
  `CHANGELOG.md` `## [0.2.0]` section, `cost` subcommand and the new
  `recommend` flags `--legacy / --input-tokens / --output-tokens /
  --max-mode / --output`, `recommend.recommend_structured` export,
  `tests/test_cli.py` Step 3 named tests).
- **Pytest:** `tests/test_cli.py` (V3.2 under `--py` and `--post`).
- **Smoke:** `--cli` builds the wheel, installs it WITHOUT the `mcp`
  extra into a fresh venv, and runs `roadmodel --help` plus
  `roadmodel cost --help`. `--post` V3.3 additionally runs a real
  `roadmodel cost --model ... --platform ... --input-tokens 1000
  --output-tokens 500` against the bundled catalog and accepts either
  a parseable `$`-line total or the typed exit-4 path (since the
  wheel ships the production catalog, not the fixture catalog used by
  the pytest run; either response proves the subcommand is wired).
- **Manual result:** **PASS** — wheel-installed `roadmodel cost`
  returns the expected ASCII output on macOS (`Total $X.XX
  (subscription pool, Cursor Ultra) ...`).

### Step 4 — MCP server core

- **Static checks:** 16–22 (`src/roadmodel/mcp_server.py`,
  `pyproject.toml [project.scripts] roadmodel-mcp = ...`,
  `[project.optional-dependencies] mcp = ["mcp>=1.0"]`,
  `tests/test_mcp_server.py` named tests, exactly three tool functions
  registered, no `os.walk / os.listdir / glob.glob / Path.iterdir`
  filesystem walking, README MCP section + link to
  `docs/mcp-setup.md`).
- **Pytest:** `tests/test_mcp_server.py` (V4.2 under `--py` and
  `--post`). Includes the SDK-absent path (`test_main_exits_2_when_
  mcp_sdk_absent`) and the registration smoke
  (`test_tools_list_exactly_three`).
- **Smoke:** `--mcp` builds the wheel, installs it WITH the `mcp`
  extra into a fresh venv, and exercises an actual MCP stdio
  `tools/list` exchange through the MCP Python SDK — asserts the
  response names exactly `recommend_model`,
  `generate_phase_roadmap`, and `read_catalog`. `--post` V4.3 repeats
  the same smoke as part of the full rollup.
- **Manual result:** **PASS** — `roadmodel-mcp` boots from the
  installed wheel, FastMCP advertises the three tools, and the
  `mcp` SDK-absent path exits 2 with the install hint when the extra
  is not present.

### Step 5 — MCP setup + tools documentation

- **Static checks:** 23–26 (`docs/mcp-setup.md` sections `Install`,
  `Cursor`, `Claude Code`, `Other MCP clients`, `Troubleshooting`;
  `docs/mcp-tools.md` names all three tools; the `pip install
  'roadmodel[mcp]'` install hint is present in the setup doc; every
  `mcp_server.py` parameter name appears in the tool reference).
- **Pytest:** none specific to this step.
- **Manual result:** **PASS** with one documented drift item — the
  shipped install hint uses double quotes (`pip install
  "roadmodel[mcp]"`) rather than the single-quoted form named in the
  Phase 2 roadmap. Both forms are valid shell; the verify script
  accepts either. See "Pre-ship items" below.

### Step 6 — Release v0.2.0

- **Static checks:** 27–29 (`git tag v0.2.0` exists in the local
  clone, `CHANGELOG.md [0.2.0]` carries a real ISO date,
  `docs/phase02-release-runbook.md` `v0.2.0` section names the
  TestPyPI and PyPI URLs).
- **Release URL:** PyPI listing
  <https://pypi.org/project/roadmodel/0.2.0/>; TestPyPI mirror
  <https://test.pypi.org/project/roadmodel/0.2.0/>; GitHub release
  <https://github.com/nathanramoscfa/roadmodel/releases/tag/v0.2.0>.
- **Pytest:** none specific (release artifacts validated via the
  `release.yml` reusable `verify-pypi.yml` matrix).
- **Manual result:** **PASS** — tag dated `2026-05-17` (UTC) in
  CHANGELOG.md, SSH-signed and verifiable via `git tag -v v0.2.0`,
  OIDC Trusted Publishing path landed both wheel and sdist plus
  Sigstore bundles on PyPI.

### Step 7 — QA + verification script (this step)

- **Static checks:** 30–33 (this script + executable bit, this
  document, `private/phase02-roadmap.md` planning doc — gitignored
  locally but PASSes on CI under the same `GITHUB_ACTIONS` escape
  hatch Phase 1 uses, and the `phase-verify.yml` matrix entry `"02"`
  in both the `verify` and `post` jobs).
- **Pytest:** none beyond the default suite invoked by
  `./scripts/verify-phase02.sh` (static + `pytest -x tests/`).
- **Manual result:** **PASS** — canonical `verify-phase02.sh` mirrors
  the Phase 1 template (record_pass / record_fail / range rollup /
  summary table); `--fast` completes in well under one second on
  macOS and is expected to stay under 30 s on Ubuntu CI.

## Manual macOS + Linux PyPI install verification

Status: **PASS** for `roadmodel==0.2.0` and `roadmodel[mcp]==0.2.0`
on PyPI.

### 0.2.0 — macOS (Python 3.12)

- Date: 2026-05-17
- Host: macOS-25.5-arm64 (Apple Silicon)
- Python: 3.12.13 (Homebrew `python@3.12`)
- `pip install --no-cache-dir "roadmodel==0.2.0"` — green;
  `roadmodel version` returned `0.2.0`; `roadmodel --help` exited 0;
  `roadmodel cost --help` exited 0 and listed every Step 2 flag
  (`--model / --platform / --input-tokens / --output-tokens /
  --max-mode / --output`).
- `pip install --no-cache-dir "roadmodel[mcp]==0.2.0"` — green;
  `roadmodel-mcp --help` exited 0 (FastMCP banner); the
  `tools/list` stdio smoke (via the MCP Python SDK
  `mcp.client.stdio.stdio_client`) returned exactly
  `recommend_model`, `generate_phase_roadmap`, `read_catalog`.
- Without the extra: a separate venv with plain `pip install
  --no-cache-dir "roadmodel==0.2.0"` and then `roadmodel-mcp` exits
  `2` with the install hint
  `roadmodel-mcp: install with 'pip install roadmodel[mcp]' to enable
  the MCP server` — as designed.

### 0.2.0 — Ubuntu 22.04 (Python 3.11)

- Date: 2026-05-17
- Host: Ubuntu 22.04 x86_64 (GitHub Actions `ubuntu-latest` runner
  inside the `release.yml` → `verify-pypi.yml` reusable job, plus a
  local Docker `python:3.11-slim` smoke).
- `pip install --no-cache-dir "roadmodel==0.2.0"` — green;
  `roadmodel version` returned `0.2.0`; `roadmodel cost` smoke
  matched the macOS output shape.
- `pip install --no-cache-dir "roadmodel[mcp]==0.2.0"` — green; the
  `tools/list` smoke matched (same three tool names).
- The cross-platform install matrix runs automatically via the
  `release.yml` `verify-testpypi` reusable-workflow call after the
  v0.2.0 tag push (Ubuntu + macOS × Python 3.11/3.12/3.13).

## MCP client smoke

The bundled `tools/list` response in every client matches the
verify script's stdio smoke: exactly `recommend_model`,
`generate_phase_roadmap`, `read_catalog`. Three tools, no extras.

### Cursor (project scope, `.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "roadmodel": {
      "command": "roadmodel-mcp",
      "args": [],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Settings → **Features → Model Context Protocol** lists `roadmodel`
with a green indicator and three tools.

### Claude Code (user scope, via `claude mcp add`)

```sh
claude mcp add \
  --transport stdio \
  --scope user \
  --env ANTHROPIC_API_KEY=sk-ant-... \
  roadmodel \
  -- roadmodel-mcp
```

`claude mcp list` reports `roadmodel` connected; `/mcp` inside a
Claude Code session shows tool count 3.

A project-shared registration via committed `.mcp.json` (same JSON
shape as the Cursor block, with `"type": "stdio"` and
`"${ANTHROPIC_API_KEY}"` for env forwarding) was also exercised; the
client picked up the entry on next launch without manual reload.

## Pre-ship items

- **Drift — Step 5 install hint quoting.** The Phase 2 roadmap names
  the literal `pip install 'roadmodel[mcp]'` (single-quoted) for
  check 25; the shipped `docs/mcp-setup.md` uses
  `pip install "roadmodel[mcp]"` (double-quoted) for shell parity
  with the rest of the doc and the README. Both are valid POSIX
  shell. The verify script accepts either form, documenting the
  drift rather than blocking on quote style. No behavior change.
- **Drift — Phase 2 §2.5 "Public roadmap publication".** Phase 2
  acceptance bullet 5 in `private/ROADMAP.md` calls for a sanitized
  `ROADMAP.md` at the repo root, linked from `README.md`. That
  artifact was descoped from the V1–V7 verification matrix in
  `private/phase02-roadmap.md` and is not yet shipped. Carrying
  forward as a Phase 3 prerequisite (the public site work in Phase 3
  will surface the same content); call it out in the Phase 3
  planning doc.
- **Downstream contract — Phase 3.** Phase 3's FastAPI recommender
  service imports `roadmodel.recommend` and `roadmodel.cost`
  directly. The `SessionCostEstimate` dataclass shape
  (`funding_source`, `subscription_label`, `input_usd`, `output_usd`,
  `total_usd`, `notes`) is the downstream contract — any Phase 3+
  refactor that touches those fields needs a synchronized service-
  side update. Same for the MCP `recommend_model` return shape
  (`model / platform / settings / rationale / conversation /
  session_cost_estimate / comparison_table`), which any future
  hosted-recommender response schema must keep stable for MCP
  clients pinned to v0.2.x.
- **CI scope — `--py` / `--cli` / `--mcp` / `--post`.** Only `--fast`
  runs in `phase-verify.yml`. The full pytest + lint + wheel +
  MCP-extra matrix runs in `tests.yml` and `release.yml`; the
  in-script modes are exposed for local pre-release sweeps.
