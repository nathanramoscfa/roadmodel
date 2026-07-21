# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.28] — 2026-07-21

### Changed

- **Rationale's third segment is now `EFFORT:` (was `RUN:`).** The recommender
  answers WHAT to run and with which settings, not HOW to run it. The third
  labelled RATIONALE segment now justifies the chosen **effort/thinking level**
  for the task ("Why this effort") instead of narrating funding/how-to-invoke.
  The parser accepts the legacy `RUN:` label (mapping it to the `effort` key) so
  responses cached across the rename still parse; the web "Why {model}?" panel
  renders **The task / Why this pick / Why this effort**.

### Fixed

- **Frontier anchor: the flagship is no longer skipped for a tied sibling.** When
  the top capability tier holds two same-provider peers tied for the task (e.g.
  Anthropic's Opus 4.8 and Fable 5), the ladder now anchors QUALITY on the
  established flagship (for Anthropic, Opus 4.8) and never drops it from the
  result for a tied sibling; Fable 5 is used only when the task specifically
  favors its strengths. Fixes the case where a Quality-default hard task
  collapsed the Cost rung to a low tier and pushed Opus 4.8 out of the ladder
  entirely.

## [0.2.27] — 2026-07-19

### Fixed

- **OpenAI reasoning models (`gpt-5*`) now return output.** These models count
  reasoning tokens against `max_output_tokens`, so without a reasoning cap the
  reasoning consumed the entire budget and the recommend call returned NO visible
  text (observed: `gpt-5-mini` ~32s, empty). The OpenAI provider now forwards
  `thinking_budget` as `reasoning.effort` for `gpt-5*` models (0 → minimal, else
  low), so `gpt-5-mini` runs in ~7s and emits a valid recommendation — enabling
  GPT-5 mini as a recommender engine (best instruction-adherence + ~3× cheaper
  with OpenAI automatic prefix caching, per the differential engine eval).

## [0.2.26] — 2026-07-19

### Fixed

- **Backup resilience: a cross-provider fallback that is benched or outside the
  user's jurisdiction is now deterministically rejected** (substituted, else
  dropped) in `_base_to_payload`, closing the gap where an anonymous caller — with
  no service-side access guard — could be handed a benched or region-blocked
  backup. Adds the fail-safe `cost.model_jurisdiction` and `cost.model_id_of`
  catalog primitives.
- **A model reached via the direct OpenAI API renders its reasoning-effort dial
  (Intelligence), not a spurious "Max Mode".** OpenAI's reasoning surfaces (Codex
  and the OpenAI API) share the effort dial and expose no Max Mode, so the settings
  display no longer falls through to the Cursor-only Max Mode mapping.

### Changed

- **Consumption-headroom effort axis reaches the offline CLI + planning kit.** The
  bundled selector's objective gains a CONSUMPTION-HEADROOM override so reasoning
  effort is an axis SEPARATE from capability tier: a user whose flat subscription
  has ample usage headroom keeps effort maxed across all picks, which then differ
  by model tier alone. (The recommender service already applies this per user; this
  release carries the rule to offline consumers.)

## [0.2.25] — 2026-07-16

### Changed

- **Bundled catalog refreshed to 40 models.** The 2026-07-15 Cursor pricing-page
  refresh (the first to land after a week-long cron outage) adds Claude Sonnet 5,
  GPT-5.6 Sol / Terra / Luna, GPT-5.2 Codex, GPT-5.1 Codex Max, Kimi K2.7 Code,
  and Grok 4.5; and drops Composer 2, Composer 1.5, Grok 4.20, Grok Build 0.1,
  and Kimi K2.5, which Cursor delisted. Because the selector and `catalog.json`
  ship inside the wheel, this release is what carries those models to the CLI,
  the MCP `read_catalog`, and the recommender service.

### Fixed

- **A Cursor delisting no longer discontinues a still-available provider-direct
  model.** Cursor removed its xAI section on 2026-07-14, so the refresh applied
  the "discontinued by Cursor" rule and dropped **grok-4.3** entirely — even
  though xAI still serves it on its own API ($1.25/$2.50), i.e. it had merely
  become provider-direct-only, exactly like DeepSeek. grok-4.3 is restored and
  reachable via the `xai-api` method.

  The root cause was `catalog-xai.json` carrying `overlay_mode: price-only`
  (correct only while Grok was *on* Cursor's page), which excluded it from the
  federation overlay that re-adds DeepSeek/Mistral when the Cursor-driven
  rewrite drops them. xAI is now `overlay_mode: whole-element`, so the overlay
  owns its `<model>` element, and the refresh prompt gained an explicit
  provider-direct **exception** to the removal rule — so this cannot recur for
  any federated provider Cursor drops.

## [0.2.24] — 2026-07-16

### Added

- **`settings-display.md` — the per-surface settings contract, now shipped to
  offline consumers.** The selector emits platform-neutral axes (`MAX MODE` /
  `THINKING` / `ORCHESTRATION`); turning those into a surface's real controls
  lives in `recommend._structured_settings` and is deliberately NOT in the
  selector (the daily effort/thinking conformance tracker pins the selector's
  vocabulary and would revert it). So anything reasoning from the selector alone
  — `read_catalog` via MCP, or an exported planning kit — had no way to know the
  rules, and emitted raw selector vocabulary: e.g. `Effort: Extra High /
  Thinking: XHigh` for Claude Code, which actually folds `ORCHESTRATION:
  Ultracode` into `Effort: Ultracode` and has a Thinking **toggle** (`On`/`Off`).

  The rules are now a bundled doc:
  - `read_catalog` returns it as `settings_display_md`.
  - `roadmodel export-kit` writes `planning/settings-display.md`.
  - A conformance table in the doc is **machine-checked against
    `_structured_settings`** every test run, so the doc cannot rot.

  Covers Claude Code (Effort + Thinking, Ultracode fold, no Max Mode), Codex
  (Intelligence), Cursor (Max Mode + Thinking `On`), and every other surface
  (Max Mode + Thinking).

## [0.2.23] — 2026-07-16

### Added

- **`roadmodel setup-mcp` — one command to make roadmodel available in every
  project on a machine.** Registers this environment's `roadmodel-mcp` with
  Claude Code at `user` scope, resolving the launcher's **absolute path** from
  the interpreter's own scripts dir. That is the fix for the "term not
  recognized" failure: inside a conda env / venv the launcher is not on PATH, so
  a bare-name registration resolves to nothing from other projects.

  ```bash
  pip install -U "roadmodel[mcp]"
  roadmodel setup-mcp
  ```

  Afterwards every project — current and future — can call `read_catalog` (the
  whole selector + tier-cost scale + catalog, **offline and keyless**) with no
  per-project install and no `planning/` folder to export or refresh.
  `pip install -U "roadmodel[mcp]"` becomes the entire update story.

  Options: `--scope user|project|local` (default `user`), `--name`, `--force`
  (re-point an existing registration here), `--dry-run` (print the command).
  If the `claude` CLI isn't on PATH, it prints the exact command to run.

## [0.2.22] — 2026-07-16

### Changed

- **Provider SDKs are now an opt-in `recommend` extra, not hard dependencies.**
  `anthropic`, `openai`, and `google-genai` moved from `dependencies` to
  `optional-dependencies.recommend`; the only hard runtime dependency is now
  `click`. The offline planning-kit workflow (`export-kit`, `catalog`,
  `context`, `version`) imports none of the SDKs, so `pip install roadmodel`
  is now lightweight and does not conflict with other packages in a shared
  environment (e.g. a project pinning an older `openai`).
  - **Action required for `roadmodel recommend` users:** install the engine
    extra — `pip install "roadmodel[recommend]"`. Running `recommend` without
    it now fails with a message telling you exactly that. The `mcp` extra and
    the FastAPI service pull `recommend` in automatically.
  - Each provider already imported its SDK lazily at call time, so this is a
    packaging change only — no import-time behavior changed for offline use.

## [0.2.21] — 2026-07-16

### Fixed

- **Fable 5 is no longer benched in the bundled static availability fallback.**
  The runtime availability layer autonomously un-benched Fable 5 on 2026-07-02
  (its 2026-06-12 export-control restriction was lifted, confirmed by grounded
  AI web-search verification), so the production recommender already offers it.
  But the offline paths — the `roadmodel recommend` CLI and the exported
  planning kit (`export-kit`) — read the bundled `<availability-context>`
  cold-start fallback, which still hardcoded the bench. That fallback list is
  now empty, matching the confirmed-live runtime state, so offline
  recommendations can select Fable 5 again. (Selector data change only; the
  runtime/authoritative path was already correct.)

## [0.2.20] — 2026-07-05

### Changed

- **The same-provider BACKUP guard now SUBSTITUTES a cross-provider fallback
  instead of dropping it (0.2.17 "option A").** 0.2.19 dropped a same-maker backup
  (e.g. Fable 5 → Opus 4.8, both Anthropic) because the package couldn't see the
  user's jurisdiction. `recommend_structured` / `recommend_structured_ladder` now
  take an optional `allowed_jurisdictions`; when supplied, a flagged backup is
  replaced by `cost.suggest_cross_provider_backup(...)` — the highest pricing tier
  at or below the primary's, from a DIFFERENT maker, valid in the user's region,
  and not benched (Fable 5 → GPT-5.5; an EU-only user → a EU cross-provider model;
  a CN-only user → a CN one). It still DROPS (as in 0.2.19) when no jurisdiction is
  supplied (a region-invalid substitute is worse than none) or when no
  cross-provider candidate qualifies. The `backup_guard` payload records the
  action (`substituted` / `dropped`) + the original backup for observability.
- New `cost.suggest_cross_provider_backup(primary, *, allowed_jurisdictions,
  unavailable_models=None)`.

## [0.2.19] — 2026-07-04

### Added

- **Deterministic same-provider BACKUP guard.** 0.2.17 made the Step 7 backup a
  HARD cross-provider requirement, but only in prompt prose — and the recommender
  model's instruction-adherence isn't perfect, so it could still emit a backup
  from the SAME maker as the primary (observed: Fable 5 primary → Opus 4.8 backup,
  both Anthropic), which provides zero resilience since one provider outage takes
  out both. New `cost.model_provider(model)` resolves a model's maker from the
  catalog access methods (excluding the Cursor pool aggregator, so an Anthropic
  model reachable via Cursor still resolves to `anthropic`); `cost.same_provider`
  compares two makers, failing safe on unknowns. `recommend_structured` /
  `recommend_structured_ladder` now DROP a same-maker backup (recording the
  decision under `backup_guard`) rather than surface a misleading fallback —
  deterministic enforcement of what the prompt can only ask for. Unknown makers
  fail safe (backup kept). Mirrors the tier-ladder tier-distinctness guard.

## [0.2.18] — 2026-07-04

### Added

- **Single-call tier-ladder recommender (`recommend_ladder` /
  `recommend_structured_ladder`).** A new selector "ladder mode" emits the whole
  Cost/Balanced/Quality ladder in ONE response — the Quality pick is chosen first
  with no budget cap, then Balanced and Cost are derived as strictly-lower rungs
  (a lower pricing tier and/or effort) — instead of three independent calls that
  could collapse onto the same model. `parse_ladder_response` splits the three
  `TIER:`-labelled blocks (each parsed by the existing single-block parser, so it
  can't reintroduce parser drift), and a deterministic tier-distinctness guard
  (`_ladder_tier_guard`, backed by the new `cost.pricing_tier`) reports whether
  the ladder is healthy (no duplicate models, no rank inversion) so an embedding
  caller can fall back to the per-priority path on a collapse. Additive: the
  single-prompt and roadmap-annotation modes are unchanged.
- **`cost.pricing_tier` / `cost.pricing_tier_rank`** — resolve a model to its
  pricing tier (low / medium / high / very-high) by bucketing its catalog output
  price per `docs/model-tier-cost-scale.md`.

## [0.2.17] — 2026-07-04

### Changed

- **The BACKUP model is now a HARD cross-provider requirement.** Step 7 of the
  selection algorithm previously only *preferred* a backup from a different
  provider/family, which let same-family backups through (e.g. a Fable 5 primary
  with an Opus 4.8 backup — both Anthropic, so a single Anthropic outage takes out
  both picks). The rule is now mandatory: the BACKUP must be from a different
  provider/family than the primary, and if no different-provider model meets the
  primary's required tier the selector DROPS the tier floor to keep the backup
  cross-provider (a slightly weaker cross-provider fallback still preserves the
  resilience guarantee). `None` is emitted only when the candidate set has no
  other-provider model at all. A doc-schema prose-check guards the hard language.
- **Cursor picks now read Thinking = On with Max Mode as the dial, not
  Thinking = N/A.** Cursor's frontier models always reason, but the IDE exposes no
  thinking-level dial, so the selector emits `THINKING: N/A` for Cursor — which
  surfaced as a confusing "Thinking: N/A" beside an em-dash Effort, implying Cursor
  had no controllable settings. `_structured_settings` now reframes a Cursor pick
  as `thinking: "On"` (reasoning happens, just not user-dialable) and keeps Max
  Mode (On/Off) as its real dial. Done at the display layer, not the selector
  vocabulary, so the daily effort/thinking conformance cron can't revert it.

## [0.2.16] — 2026-07-04

### Changed

- **Ultracode is now presented as the top of Claude Code's single Effort ladder,
  not a separate "Orchestration" row.** Claude Code's UI exposes ONE effort dial —
  `Low / Medium / High / XHigh / Max / Ultracode` (Ultracode = xhigh + Dynamic
  Workflows) — plus a separate Thinking toggle; it has no standalone orchestration
  control. The 0.2.15 change surfaced `ORCHESTRATION` as its own settings row,
  which didn't match that UI and produced incoherent combos like
  "Effort: High + Orchestration: Ultracode". `_structured_settings` now FOLDS an
  `ORCHESTRATION: Ultracode` into the Claude Code **effort** value (`Effort:
  Ultracode`) and no longer emits a separate `orchestration` settings key. The
  selector's internal THINKING+ORCHESTRATION model is unchanged (it still drives
  the effort-conformance tracker, which requires Ultracode to read as a session
  setting = xhigh + workflows), so this is purely a presentation reconciliation.
- **The orchestration decision rule is budget-aware.** The selector now never
  recommends Ultracode under a Cost posture, reserves it for genuinely
  orchestration-requiring work under Balanced, and prefers it for the Quality
  posture on the most demanding tasks — so the Cost/Balanced/Quality effort tiers
  stay distinct once Ultracode is folded into the effort ladder.

## [0.2.15] — 2026-07-04

### Changed

- **The recommender now surfaces the Claude Code `ORCHESTRATION` dial as a
  settings dimension.** `ORCHESTRATION` (the Dynamic-Workflows lever —
  `None` / `PerPrompt` / `Ultracode`) was captured by the parser but silently
  dropped; it is now an optional key on the parsed response and, on the Claude
  Code path, `_structured_settings` emits an `orchestration` value (an absent /
  `None` value renders as `Standard`) so a consuming UI can show an
  Orchestration row in the comparison matrix — matching the approved
  `/recommend` mockup. It stays `N/A` (and is omitted) on non-Claude-Code
  surfaces, and remains an OPTIONAL key kept out of `_REQUIRED_KEYS`, so a
  provider that omits the line still parses.

## [0.2.14] — 2026-07-03

### Changed

- **Budget priority now steers the Cost pick by capability tier + effort, not
  just out-of-pocket price.** When a user funds a whole model family at $0 (e.g.
  claude.ai Max), list price is flat across every candidate, so the old
  "keep the $0 model, lower effort" rule let the selector hold the *frontier*
  model for all three priorities — Cost, Balanced, and Quality collapsed onto
  the same top model at max effort. The `<objective>` BUDGET-PRIORITY OVERRIDE
  and the SaaS header now instruct the `cheap` posture to pick the smallest /
  lowest-tier model that is still adequate at the lowest effort that clears the
  task — landing clearly below the Quality pick in both tier and effort — while
  Quality holds the frontier and Balanced sits between. The three picks are once
  again distinct and sensibly ordered.
- **The `RATIONALE` segments are terser.** Each of `TASK:` / `PICK:` / `RUN:`
  is now capped at one crisp sentence (~15–25 words) in the `<output-format>`
  template and the SaaS header, so the "Why this model?" panel renders compactly
  instead of a 12–15 line wall of text. The three-segment labelled format,
  `parse_response` regex, `_REQUIRED_KEYS`, and the drift guard are unchanged.

## [0.2.13] — 2026-07-03

### Changed

- **The selector emits its `RATIONALE` as three labelled segments** — `TASK:` /
  `PICK:` / `RUN:` — so a consuming UI can render sub-headed sections ("The task
  / Why this pick / How to run it") instead of one prose blob. `recommend_structured`
  parses them best-effort into a new `rationale_sections` payload field. The
  single `RATIONALE` field stays required and its `parse_response` regex,
  `_REQUIRED_KEYS`, and the parser-drift guard are unchanged, so a model that
  ignores the labelled format still returns a valid recommendation — purely
  additive, with no new failure path (the Gemini instruction-adherence safety
  net). The FastAPI wrapper carries `rationale_sections` across the service
  boundary on `RecommendResponse` (absent → `None`).

## [0.2.12] — 2026-07-02

### Changed

- **Runtime model availability can now be authoritative.** `build_prompt`,
  `recommend`, and `recommend_structured` gain an `availability_authoritative`
  keyword. When an embedding caller (the SaaS service) passes it `True` — meaning
  it read the live availability source successfully — the supplied
  `unavailable_models` list is treated as the COMPLETE current unavailable set and
  SUPERSEDES the bundled `<availability-context>` defaults: a catalogued model
  absent from the list is available even if the static block names it. This lets a
  model whose provider access is RESTORED become recommendable again without a
  package release. The default (`False`) preserves the prior additive behavior —
  the runtime list can only ADD exclusions on top of the static defaults — so
  every CLI/MCP/direct caller is unchanged, and a caller whose availability read
  fails stays fail-closed on the static defaults.
- **`<availability-context>` reworded as a fail-closed cold-start fallback.** The
  bundled unavailable list (e.g. an export-controlled model) is now documented as
  the default that applies only when no authoritative runtime override is supplied,
  rather than a hardcode that must be hand-edited to lift. When the runtime override
  is authoritative it wins; the static list is the safety net for when the
  availability service is unreachable.

## [0.2.11] — 2026-06-29

### Changed

- **The recommender can now recommend `Max` reasoning effort.** The selector's
  structured `THINKING` output field gains a `Max` state above `XHigh`
  (`Off / Low / Medium / High / XHigh / Max / N/A`), so it can surface Claude
  Code's top `/effort` level on models that expose a `max` step above `xhigh`
  (Opus 4.7, Opus 4.8, Fable 5). The selection algorithm reaches `Max` on those
  models for the most demanding tasks or under a Quality budget posture, and
  never under a Cost posture (where effort is held to the lowest level that
  clears the task). Faithful normalization: a model whose top is `max` with no
  `xhigh` step (Opus 4.6, Sonnet 4.6) and DeepSeek (no `xhigh` step) keep
  `max → XHigh`; providers that top out at `xhigh` (OpenAI) or `high` (Gemini,
  Mistral) are unchanged. Tracker prompts were updated so a daily refresh does
  not revert the new state. (Ultracode remains a separate `ORCHESTRATION` axis —
  a follow-up.)

## [0.2.10] — 2026-06-28

### Added

- **`roadmodel export-kit`.** New CLI command that exports the bundled planning
  kit — phase/project roadmap templates and the how-to — to a target directory
  for cross-platform use (`--force` to overwrite, optional user-context
  override) (#295).

### Changed

- **Budget-priority steering in the selector prompt.** The `<objective>` now
  honors a per-request "Budget priority and speed posture" declared in the
  appended user-context — `cheap` (Cost), `balanced` (Balanced), `best`
  (Quality) — each applying a distinct quality-vs-cost rule that overrides the
  default quality-first posture. **Cost is funding-aware:** when the
  user-context's held subscriptions fund a capable model at $0, Cost keeps that
  model and lowers reasoning effort/thinking rather than switching to a
  cheaper-tier model the user pays per-token for (the one scoped exception to
  "funding changes only the platform, never the model"); reasoning effort
  becomes the cost-vs-quality axis when the model is held. No-op when no posture
  is declared, so every CLI/MCP call is unchanged.
- **BACKUP model in the `recommend` text output.** The CLI now renders the
  fallback model when the selector emits one (#293).
- Refreshed the bundled catalog (models, pricing, availability).

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
