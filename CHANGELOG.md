# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.9] — 2026-06-15

### Added

- **Runtime availability hook.** `recommend`, `recommend_structured`, and
  `build_prompt` gain an optional `unavailable_models: list[str] | None` keyword.
  When supplied, the listed model ids are injected as a **runtime Step 0a
  override** layered on top of the bundled `<availability-context>` defaults —
  the recommender never returns them as MODEL or BACKUP. This lets an embedding
  caller (the roadmodel.ai service) bench or un-bench a model from a runtime
  source — e.g. a provider-availability probe — **without a package release**.
  `None`/empty (the default, and every CLI/MCP call) is a no-op, so behavior is
  unchanged unless a caller opts in.

## [0.2.8] — 2026-06-14

### Changed

- **The recommender no longer recommends unavailable models.** The bundled
  `model-selector.txt` gains an editorial `<availability-context>` block and a
  `<selection-algorithm>` **Step 0a** pre-filter (mirroring the jurisdiction
  filter) that drops listed model ids from the candidate set before quality
  ranking. **`claude-fable-5` (Claude Fable 5) is marked unavailable** —
  Anthropic suspended access on 2026-06-12 under a US export-control directive —
  so the recommender returns the next-best available model instead. The model's
  catalog entry and tier ratings are retained for reference; it is excluded only
  at selection time, so re-enabling is a one-line edit (#276).

### Added

- **Optional `BACKUP` recommendation field.** The bundled selector's
  `<output-format>` now emits a `BACKUP` line (**Step 7** of the selection
  algorithm) naming the next-best *available* model — preferably a different
  provider/family — to fall back to when the primary is unavailable to the user.
  `parse_response` captures it as an OPTIONAL field (kept out of
  `_REQUIRED_KEYS`, mirroring `ORCHESTRATION`), so a provider that omits it or
  emits `None` still parses with no error; `recommend_structured` surfaces it
  when present (#277).

  Like all bundled-selector changes, both of the above reach the recommendation
  LLM only via this release.

## [0.2.7] — 2026-06-13

### Changed

- The bundled `model-selector.txt` now carries the **bias-not-gate**
  funding-aware `<access-selection>` prose (Phase 4.8 T2b). The recommender
  builds its prompt from the package-bundled selector, so this prose only
  reaches the recommendation LLM via a release — `0.2.6` still shipped the
  prior hard-gating prose. The softened algorithm:
  - **Step B** tags each access method funded/unfunded and **never drops**
    an unfunded one (it is a valid platform that simply costs real money);
    funding never changes the chosen MODEL.
  - **Step C** picks the cheapest path and, when no funded method reaches
    the chosen model, **still recommends that model** via its cheapest
    access method and discloses the pay-per-token spend in the rationale.
  - **Guardrails** prefer a funded surface only to break an exact quality
    tie and never downgrade the model to avoid spend. Jurisdiction remains
    the one hard filter (a compliance constraint, not a cost one).

  No engine, model, cost, or API change — only the bundled selector text
  (and the regenerated `model-selector.md` / `catalog.json`, whose diff is
  limited to the source hash). Pairs with the service-side per-user funding
  context (`user_context_text`, added in `0.2.6`) so model SELECTION honors
  each user's declared funding without excluding the best model (#163).

## [0.2.6] — 2026-06-13

### Added

- Optional `user_context_text: str | None` keyword on
  `roadmodel.recommend.recommend` and
  `roadmodel.recommend.recommend_structured`. When provided, the supplied
  text is used verbatim as the user-context section of the system prompt and
  the `config.user_context_path` file read is **skipped**; when `None` (the
  default, and every CLI/MCP call) behavior is unchanged — the on-disk
  user-context file is read exactly as before. This lets an embedding caller
  (the roadmodel.ai SaaS service) inject a **per-request, per-user** funding
  context — the user's held subscriptions and enabled API providers — so the
  selector can prefer a model the user already funds at $0 on a quality tie,
  instead of always seeing one static bundled user-context. No engine, model,
  cost, or prompt-template change; purely an additive, backward-compatible
  API surface.

## [0.2.5] — 2026-06-06

### Changed

- `roadmodel.recommend.build_prompt` hardens the SaaS recommender system
  prompt so the recommender follows the selector spec instead of performing
  the user's task:
  - **Strips the bundled `model-selector.txt` `<instruction>`/`<usage>`
    blocks** from the assembled system prompt. Those blocks frame the file's
    IDE roadmap-*annotation* mode ("Execute the requested task in full … the
    AI performs the task"), which pushed the recommender to write the user's
    study plan / poem / proof inside the `RATIONALE`. The bundled file is left
    untouched, so the IDE / Claude Code path keeps the full framing (#187).
  - **Front-loads a hardened header** restating the rules the recommender
    model most often violates against the deep spec: quality-over-cost (no
    cost-demotion below the top reachable tier, #185), the funded-platform
    preference order (#186), `THINKING: N/A` on surfaces that expose no
    thinking dial (#188), and strict PRIMARY-category classification (#189).
  - **Wraps the user prompt** in `<task-to-classify>` so the model reads it
    as delimited input rather than an instruction to execute.

  No engine, model, or cost change — the free-tier recommender still runs the
  same provider; only the prompt text changes. Validated against Gemini 2.5
  Flash (prod params, repeated runs): task-execution leak eliminated,
  quality-undershoots corrected to the top reachable tier, platform routing
  moved to the $0-funded surfaces, and run-to-run pick determinism improved.

## [0.2.4] — 2026-06-04

### Added

- Optional `temperature: float | None` keyword on
  `roadmodel.recommend.recommend` and
  `roadmodel.recommend.recommend_structured`, plumbed through the
  `ProviderAdapter` Protocol (mirrors the `0.2.3` `thinking_budget`
  work). When set, `providers.google` forwards it to the Gemini SDK as
  `config.temperature`; the guard uses `is not None`, so `temperature=0.0`
  (greedy/deterministic) is honored rather than dropped.
  `providers.anthropic` and `providers.openai` accept the keyword for
  Protocol parity but do not forward it. When unset, every provider keeps
  its prior behavior exactly, so this is a no-op until a caller opts in.

  Motivation: the free-tier recommender ran Gemini at its default sampling
  temperature (~1.0), so the same `task_description` returned different
  model picks run-to-run (a production dogfooding sweep saw ~25% of
  identical requests flip to a different model). Callers can now pin a low
  or zero temperature for consistent recommendations (#176).

- `roadmodel.cost.canonical_model_name` and
  `roadmodel.cost.canonical_platform_name`: resolve a model or
  access-method **id-or-name** to its catalog display name, returning the
  input unchanged on any catalog miss (never raise) (#174).

### Changed

- `recommend_structured` now canonicalizes the recommended model and
  platform to their catalog display names before building the payload (and
  reuses them for the cost estimate + comparison-table calls). The selector
  LLM emits either the catalog id/slug or the display name freely, which
  made the response header (raw) disagree with the cost/comparison table
  (catalog-canonical) within one response and risked silently dropping the
  cost panel on an unrecognized label. Falls back to the raw value on a
  catalog miss (#174).

## [0.2.3] — 2026-06-01

### Added

- Optional `thinking_budget: int | None` keyword on
  `roadmodel.recommend.recommend` and
  `roadmodel.recommend.recommend_structured`, plumbed through the
  `ProviderAdapter` Protocol. When set, `providers.google` forwards it
  to the Gemini SDK as `config.thinking_config.thinking_budget`
  (`0` disables Gemini's default reasoning entirely; a small value
  bounds it). The guard uses `is not None`, so `thinking_budget=0` is
  honored rather than dropped. `providers.anthropic` and
  `providers.openai` accept the keyword for Protocol parity but do not
  forward it — Anthropic extended-thinking has different semantics
  (and the recommender response shape does not tolerate small caps on
  Anthropic), and OpenAI uses `reasoning.effort`; wiring those is
  out of scope here. When unset, every provider keeps its prior
  behavior exactly, so this release is a no-op until a caller opts in.

  Motivation: Gemini 2.5 Flash reasons by default, and those reasoning
  tokens are decoded before — and counted against the budget of — the
  visible answer. That is the dominant term in the recommender's
  warm-path latency (a clean production baseline measured a P50 of
  ~13 s, with the Gemini call accounting for ~99.7 % of total time).
  `thinking_budget` is the lever to bring that down; it also explains
  why the 0.2.1 `max_output_tokens` cap alone could not fix the
  latency without truncating the response.

## [0.2.2] — 2026-05-31

### Fixed

- **Production hotfix:** `roadmodel.recommend.parse_response` now
  accepts responses that include the optional `ORCHESTRATION` row
  introduced by the selector's Ultracode dimension (added to the
  bundled `model-selector.txt` via the SaaS-facing PR that
  documents Claude Code's Ultracode effort level). Without this
  fix, both Gemini 2.5 Flash and Anthropic Haiku 4.5 emit
  responses matching the new schema (a six-field block plus an
  ORCHESTRATION line between THINKING and CONVERSATION), and the
  parser rejected every one as `MalformedResponseError`. Every
  `/api/recommend` call from `roadmodel-service` returned 500.
  The fix wraps the new line in a non-capturing optional regex
  group so both old (no ORCHESTRATION) and new (with
  ORCHESTRATION) responses parse. The captured value is consumed
  silently — surfacing it via `recommend_structured` is a
  separate change.

## [0.2.1] — 2026-05-31

### Added

- Optional `max_output_tokens: int | None` keyword on
  `roadmodel.recommend.recommend` and
  `roadmodel.recommend.recommend_structured`, threaded through every
  bundled provider adapter (`providers.google`,
  `providers.anthropic`, `providers.openai`) and the
  `ProviderAdapter` Protocol. When unset, each provider keeps its
  prior default (Google: SDK default 8192, Anthropic: 4096, OpenAI:
  SDK default). When set, it is forwarded as
  `config.max_output_tokens` to Gemini, `max_tokens` to Anthropic,
  and `max_output_tokens` to the OpenAI Responses API. Caller
  motivation: Phase 4 Step 7 warm-path latency profiling against
  `/api/recommend` showed `service_provider_ms` P50 = 17,014 ms
  (5.7× over the ≤ 3000 ms budget); capping the Gemini Flash output
  at 1,024 tokens cuts decode-time without truncating the
  recommender's six-field response. The service-side uptake (passing
  `max_output_tokens=1024` from `roadmodel-service` plus bumping the
  package pin) ships in a follow-up PR after this 0.2.1 PyPI publish
  lands (chicken-and-egg: Vercel deploys can't install a pre-PyPI
  version). See `docs/phase04-latency-findings.md`.

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
