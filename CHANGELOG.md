# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-05-17

### Added

- Structured output schema on `roadmodel recommend` (model, platform,
  per-surface `settings`, rationale, conversation, and optional cost
  fields). Use `--legacy` to keep the v0.1.x six-field block; use
  `--output json` (or `--json`) for JSON with 2-space indent.
- `roadmodel cost` subcommand for ad-hoc session cost estimates from
  the bundled catalog (`--model`, `--platform`, token counts,
  optional `--max-mode`, `--output text|json`).
- Bundled `catalog.json` with machine-readable per-model pricing,
  tier ratings, access methods, Max Mode rules, and subscription tiers
  (see Step 1 of the phase roadmap).
- `roadmodel-mcp` MCP server entry point and `roadmodel[mcp]` install
  extra (see Step 4 of the phase roadmap).
- `docs/mcp-setup.md`, `docs/mcp-tools.md`, and `docs/catalog-refresh.md`
  (see Steps 1 and 5 of the phase roadmap).

## [0.1.2] — 2026-05-15

### Fixed

- `roadmodel recommend --file <path>` now validates that the file
  exists at argument-parse time and exits 2 with
  `Invalid value for '--file': File '<path>' does not exist.` —
  consistent with the other Click-validated usage errors. Previously
  a missing path surfaced the raw `FileNotFoundError` as
  `Unexpected error: [Errno 2] No such file or directory: '<path>'`
  with exit 1.
- `roadmodel recommend --provider <X>` with no matching
  `<X>_API_KEY` now reports the specific provider and env var:
  `Provider '<X>' selected but <X>_API_KEY is not set. Try: export <X>_API_KEY=...`.
  Previously the CLI emitted the generic three-key message even when
  the user had explicitly selected a single provider, which obscured
  the actual problem. The implicit-fallback path (no `--provider`
  and no `ROADMODEL_PROVIDER`) still emits the original three-key
  message.

## [0.1.1] — 2026-05-15

### Security

- Drop the implicit repo-walk fallback in `user_context.resolve()`. The
  prior behavior walked up to the nearest `.git` and treated
  `docs/user-context.md` from that repo as a fallback candidate, which
  meant a user running `roadmodel` inside an attacker-controlled repo
  before bootstrapping their own user-context could have had that
  repo's file sent to their provider. The supported overrides
  (`--user-context`, `ROADMODEL_USER_CONTEXT`, the XDG default path)
  are unchanged.
- Mask `api_key` in `Config.__repr__` so traceback formatters that
  render local variables cannot inadvertently expose the key.
- Bootstrap `user-context.md` atomically with `0o600` via `os.open`
  (no write-then-chmod race window) and tighten the parent directory
  to `0o700` when newly created.
- Replace `f"... failed: {exc}"` with `f"... failed ({type(exc).__name__})."`
  in the provider bare-`except` fallbacks so future SDK exception
  messages cannot accidentally leak request metadata via error
  strings.

## [0.1.0] — 2026-05-15

### Added

- Initial open-source release of the roadmodel CLI.
- `roadmodel recommend` with `--file`, `--json`, `--provider`,
  `--model`, and `--user-context` flags.
- `roadmodel catalog show` and `roadmodel catalog path` (with
  `--doc tier-cost-scale` to target the per-token price doc instead
  of the default `model-selector.txt`).
- `roadmodel context show`, `roadmodel context path`, and
  `roadmodel context init` for managing the user-specific
  `user-context.md`.
- Six-field response parser (`MODEL` / `PLATFORM` / `MAX MODE` /
  `THINKING` / `CONVERSATION` / `RATIONALE`) matching the
  `model-selector.txt` `<output-format>` specification.
- First-run bootstrap of `~/.config/roadmodel/user-context.md` (or
  `$XDG_CONFIG_HOME/roadmodel/user-context.md` when `XDG_CONFIG_HOME`
  is set) from a bundled template.
- Provider adapters for Anthropic, OpenAI, and Google.
- Bundled `model-selector.txt`, `model-tier-cost-scale.md`, and
  `user-context.example.md` as package data.

### Changed

- Project renamed from `model-selector` to `roadmodel`.

[0.1.0]: https://github.com/nathanramoscfa/roadmodel/releases/tag/v0.1.0
