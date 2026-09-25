# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **A step commits the AGENTS.md the updater created.** `roadmodel-update`
  writes `AGENTS.md` once in every project and never commits it, so each
  project's next `/roadmap-step` stopped on a dirty tree and asked what to
  do. `/roadmap-step` and `/roadmap-refresh` now commit it first, on its
  own, in their own PR, recognising it by the updater's marker comment. An
  `AGENTS.md` without the marker is the operator's own and stays untracked.

- **The recommender soak fails loudly when production stops answering.**
  From 2026-09-21 to 2026-09-24 every production recommendation failed while
  `recommend-soak.yml` stayed green. Its quality bar is report-only, and its
  tracking issue already fails daily on known residuals.
  - `scripts/soak-health.ts` marks the service DOWN when half or more of the
    soak's requests fail, and the script exits 3.
  - The workflow then fails the run and opens an `incident` issue. The issue
    gets a comment on every failing run and closes itself when requests
    succeed again.
  - `cron-health.yml` now posts its alarm with the workflow's own token. The
    cron bot's App token had every comment refused, so the alarm never
    posted.

## [0.2.42] — 2026-09-24

### Added

- **The catalog retires models that a newer sibling beats on every count.**
  A model is superseded when another model from the same maker meets all of
  these:
  - it costs the same or less (blended price);
  - it scores higher on the AA Intelligence Index;
  - it rates at least as high in all seven categories;
  - it runs on every platform that offers the older model.

  What happens:
  - `update/supersede.py` tags a superseded model with `superseded-by` and
    `superseded-on`. The benchmarks cron and the catalog cron run it daily.
  - The recommender leaves the model out of its candidates while its
    successor is available.
  - /models shows "Superseded by X · leaves <date>".
  - 30 days on it is retired. It leaves `docs/catalog.json`, and with it the
    website and the MCP catalog, but stays in `model-selector.txt` as the
    record.

  Today 21 of 50 models are superseded, including Opus 4.7, 4.8 and 5 (by
  Opus 5.5), and ten GPT-5.x models (by GPT-5.6 Sol, Terra and Luna). The
  scenario tests that name specific models run against a frozen catalog
  (`tests/fixtures/catalog-frozen.json`), so retirements cannot strand the
  cron's PR.

- **/models draws the cost/quality frontier across every model.** A new
  chart sits below the per-tier Score charts. It plots every model with an
  AA Index at its blended price and score. The frontier models are green and
  joined by a dotted green line that steps up at each one, so the line's
  height at any price is the top AA Index that price buys. Behind it, the
  Score's four tier lines appear in grey for comparison. Hovering a dot
  shows the top score at that model's price; hovering the line shows the
  top score at that price.
- **Every explanation of the frontier says what it is.** A green ring marks
  a model that scores higher on the AA Index than every other model at its
  price or less. The cards name the top score at a model's price, and group
  headers name the top score at the group's prices.

- **/models can group by quality as well as by cost tier.** A new Group by
  switch sits beside the filters. Cost tier stays the default and answers
  "what's the best buy at my budget?". Quality groups the table into
  ten-point AA Index bands, cheapest first, and answers "what's the
  cheapest way to reach this level?". Either way, a group with nothing on
  the cost/quality frontier says so in its header, and a cost tier says it
  in its chart too, naming the model that beats it. For example: "None on
  the frontier: all 6 are beaten by Opus 5.5 (High cost)". Every tier's
  Scores average zero however overpriced the whole tier is, so the page now
  states outright what the Score cannot show.

### Changed

- **The roadmap-writing commands set their own effort.** `/roadmap-phase`
  runs at `xhigh` and `/roadmap-project` at `max` in Claude Code, from an
  `effort:` line in each command's frontmatter, so writing a roadmap no
  longer depends on the operator typing `/effort` first. A roadmap is
  written once per phase and shapes every step in it; the extra rung costs
  little. The ports for Codex, Gemini, Antigravity, Cursor and OpenCode
  carry only the description, as before.

- **/models leads with the catalog, and says what its frontier mark and its
  prices mean.** The table now comes first, then the per-tier Score charts,
  then the full key, which the table links to. The cost/quality frontier is
  now priced on the blended price, like the Score and the charts. It is drawn
  as a green ring beside the AA Index instead of a dot on the within-tier
  Score, and every AA Index, Score and chart card names the model from any
  tier that beats it. Each cost-tier header gives both its output and its
  blended price range, and a key above the table defines the frontier and
  the blended price, (3 × input + 1 × output) ÷ 4.

### Fixed

- **The catalog cron adds the models it discovers on providers' own pricing
  pages.** The extractors have flagged models that Cursor never lists
  (`unexpected_slugs`) since #650, and the curation prompt told the model to
  add or decline each one. But the model's input never included the snapshots,
  so GPT-6 Astra, Sol and Luna, Claude Mythos 5 and 5.1, and seven others
  stayed flagged while every run reported the catalog complete. Now:
  - `update/discovery.py` hands the curation model a `<provider_discovery>`
    block with each such model and its provider-page price.
  - A decline is a line in the new "Declined Models (discovery lane)" section
    of `docs/model-tier-cost-scale.md`, which the cron restores if the
    regenerated file drops it.
  - A model the run neither adds nor declines gets a tracking issue.
  - The OpenAI and Anthropic extractors record each flagged model's price
    (`discovered`), and the conformance gate checks it.

## [0.2.41] — 2026-09-23

### Changed

- **Every Settings table names its backup.** A phase roadmap step's
  Settings table gains a `Backup` row directly under `Model`: the model to
  run when the primary is unavailable, from a different provider family,
  with its own platform and dial in one cell (`GPT-5.6 Terra — Codex ·
  Intelligence Medium`). The backup used to appear only at the end of the
  Model rationale and in the Model selection blocks at the foot of the
  file. `/roadmap-refresh` adds the row to existing roadmaps from the backup
  each step already names, as a layout fix rather than a new pick, and
  `/roadmap-step` lets a step run on its backup when the operator has
  switched to it.

## [0.2.40] — 2026-09-23

### Changed

- **Step completion shows at the step heading (#699).** In a phase roadmap,
  each step's `**Status:**` line now sits directly under its `## Step N — …`
  heading, before the Goal, instead of below Goal, Branch and Deploys. A
  step's own PR appends ` ✅` to its heading when it marks the step
  `Complete`, so progress shows in the rendered preview, the outline and the
  table of contents. The phase roadmap gains its own `**Status:**` line
  under the title (`Not started` → `In progress` → `Complete`, set by the
  first and final steps' PRs) and a Status column in its Summary Table.
  `/roadmap-refresh` migrates existing roadmaps to this layout without
  changing any status; `/roadmap-step` does the same in its own PR if it
  meets the old layout first. The template's Step 2 skeleton, which had no
  Status line at all, now has one.
- **Codex's six effort levels (#693).** Codex's config reference now lists
  `low`, `medium`, `high`, `xhigh`, `max` and `ultra` (`minimal` is gone);
  the selector's OpenAI/Codex vocabulary and its effort mapping follow it.
  The Codex tracker now commits the exact docs span it parsed beside its
  snapshot and re-derives the snapshot from it, so a Codex docs change no
  longer strands its refresh PR on a hand-cut fixture.
- **Claude Code 2.1.280 (#692).** Opus 5.5 joins the models that reach
  `Max` effort, with `medium` as its default.
- **Opus 5.5 and Grok 4.7 carry Artificial Analysis data (#694, #695).**
  Both were added to the catalog unmapped; mapped to AA's own entries
  (Opus 5.5: AA Index 57.6, HLE 61.4%, AA-LCR 84.7%), their measurable
  letters are now derived instead of inherited. Opus 5.5's HLE is the new
  Knowledge leader, so 13 models moved down one Knowledge band (Fable 5
  and Opus 5 S→A), and Opus 5.5's Long-context letter is S.
- **Catalog (#691):** Claude Opus 5 is hidden by default in Cursor now
  that Opus 5.5 is its default Opus.

### Fixed

- **LLM-written attribute values can no longer truncate themselves
  (#697).** The daily trackers escape a raw quote inside a one-attribute
  line before saving the selector, so prose like `configurable under
  "Project instructions"` no longer cuts a value off mid-sentence (#663,
  #692).
- **A new catalog model links itself to Artificial Analysis (#698).** The
  nightly benchmark job maps an unmapped catalog id to the AA entry whose
  slug matches it exactly, and lists each one in its PR.

## [0.2.39] — 2026-09-23

### Changed

- **The updater keeps itself current (#689).** `scripts/update_projects.py` now
  also ships in the package as `roadmodel.update_projects`. The copy each
  machine's schedule runs (`~/.config/roadmodel/update_projects.py`)
  upgrades roadmodel in a venv of its own (`~/.config/roadmodel/venv`),
  replaces itself with the copy in that release, and hands the run over to
  it. An updater fix now reaches every machine with the next release, with
  no re-fetch. It only runs published releases, never `main`, and falls
  back to the local copy (saying why) if any step fails. This replaces the
  stale-copy warning from 0.2.38.

### Fixed

- **The first run after a release picks it up (#689).** The per-project upgrade
  bypasses pip's HTTP cache, which could serve an index page from before
  the release and report `0.2.37 -> 0.2.37 ok`.
- **The Windows task catches up (#689)** after a start it missed because the PC
  was off, and on macOS each run is recorded once in `update.log`, not
  twice.

## [0.2.38] — 2026-09-23

### Added

- **`/roadmap-refresh` — bring roadmaps current without running a step
  (#686).** Marks every step whose own Branch has a merged PR as `Complete`,
  then re-runs the model selector for the current step and every step after
  it. Completed steps are never touched, no task block runs, and it delivers
  one docs-only PR. `/roadmap-step` executes a step; this one does none.
- **One user-context across machines (#685).** A source machine publishes
  its file to a PRIVATE repo and every other machine pulls it before
  refreshing its planning kits: `--context-sync OWNER/REPO` (replica), plus
  `--context-source PATH` (source). Markdown data, written never executed; a
  replica keeps the copy it replaced as `user-context.md.prev`.
- **Antigravity is a first-class agent (#670, #678).** It shares `~/.gemini`
  with the retired Gemini CLI but reads its own layout: the `/roadmap-*`
  commands install as skills under `~/.gemini/config/skills/` (a skill there
  IS a `/name` command), the roadmodel MCP server into
  `~/.gemini/config/mcp_config.json`, and every registered project is trusted
  in `trustedWorkspaces`.
- **The updater says when it is stale (#681).** It is deliberately not
  self-updating; it now compares itself to `main` after a run and prints the
  exact re-fetch command. The fetched copy is compared, never written or run.

### Changed

- **Every agent runs on its provider's own default model and effort (#679).**
  The runtime sync removes pinned defaults instead of writing roadmodel's
  opinion, so each client resolves its provider's live default — Codex
  documents none as a value, only its client knows it. Ceilings
  (`maxEffortLevel`) are kept. `--keep-pins` opts out (`--no-calibrate` still
  works).
- **`/roadmap-step` reads a Settings table as intent (#684).** A newer version
  in the same line (Opus 5 → Opus 5.5) passes the gate, a top-rung effort
  written before a `capped` posture is treated as stale, and the step's own PR
  records what actually ran. A different line still stops.
- **Catalog: Claude Opus 5.5 (#687) and Grok 4.7 (#658).** Opus 5.5 is
  Anthropic's Opus 5 successor at $4 / $20 (20% cheaper), in the High cost
  tier, and the default Opus in Claude Code from 2.1.280; it tops the
  Artificial Analysis Intelligence Index at 57.6 (max effort). Its price is
  verified against Anthropic's own pricing page. Its letter ratings are
  placeholders inherited from Opus 5 until measured.
- **A declined model stays declined (#687).** xAI's page moved from display
  names to slug-form rows, which silently disarmed every entry in the xAI
  extractor's DECLINED map; the lookup now compares slugs.

### Fixed

- **A Usage-pool row now expires at its own reset time (#683).** A stale
  `exhausted` row was routing coding work off a pool that had already reset.
  Only a certainly-past DATED reset expires a row: wrongly unlocking a live
  exhausted pool bills overflow at list price.
- **A raw quote inside a selector attribute truncated it (#663, #672).** The
  claude-code `best_for` shipped cut at "configurable under ", losing its
  Ultracode tail; a general structural test now catches any such attribute.
- **grok-4.6 had no access method after a refresh (#658).** The refresh
  replaced the grok list instead of inserting into it.
- **LMArena's WebDev leaderboard shipped empty (#673).** One latest date per
  subset discarded every `overall` row when a narrower board published later;
  each board now keeps its own date.
- **The Groq price check read a page with no models on it (#675).** It now
  reads `console.groq.com/docs/models`, and reports gpt-oss models the catalog
  lacks.
- **The Codex reasoning tracker wrote `["string"]` as the vocabulary (#680).**
  OpenAI moved the values into the description; the extractor now reads them
  (`low` … `ultra`).
- **An invalid escape in the updater (#682).** A SyntaxWarning on every run
  and a future SyntaxError; `W605` is now linted.
- **A local Playwright run now matches CI (#676).** One committed placeholder
  env (`web/.env.ci`), and the test server is never adopted from a stranger on
  the port.

### Changed

- **The recommender engine moves to GPT-5.6 Luna.** A 12-probe differential
  eval (`scripts/eval_recommend_engines.py`, anon path) against the incumbent
  gpt-5-mini and the tier above it: all three parse 12/12 with every
  structured field and rationale section present and no task leak, but
  gpt-5-mini demotes the Quality pick on cost grounds on the `cost-bulk` probe
  (no-demote 0.92) where Luna and Terra do not (1.00) — and Luna is ~40%
  cheaper per output token ($0.20/$1.20 vs $0.25/$2.00 per Mtok) while Terra
  costs 1.8× the latency for no adherence gain. Anon and signed-in frontier
  both cut to `gpt-5.6-luna`; the gpt-5-mini provider hint stays registered so
  rollback is a one-line change. The OpenAI adapter now picks each model's
  reasoning FLOOR rather than assuming `minimal`: the GPT-5.6 generation
  rejects `minimal` outright, which is what the first eval run discovered.
- **`/models` Score: a cost-adjusted number for every model, grouped by cost
  tier.** The column (formerly "Value") used to mark five rows "Best value"
  (the cost/quality Pareto frontier) and leave the rest blank. It is now a
  score for every AA-measured model: the AA Intelligence Index minus the index
  its price predicts *among its own cost tier*. The prediction is one
  least-squares fit of index against log10(blended price, 3 input : 1 output)
  over all measured models with a single pooled price slope (a slope per tier
  would rest on a handful of points) and a separate baseline per cost tier —
  so the cost weight is estimated from the market (today ≈ 16 index points per
  10× price) rather than picked, and residuals sum to zero within every tier.
  Positive means more intelligence than a same-tier model at that price
  usually delivers. Sorting by Score groups the table under one header row per
  tier (count, measured, blended price range); the header tooltip and legend
  carry the fit's n, R² and residual σ, and a gap under σ is a tie (cells
  beyond ±σ are tinted). The frontier survives as a dot beside the score.
  Also fixed: a glossary tooltip inside a table header inherited the header's
  `whitespace-nowrap` / `uppercase`, so its text ran off the right edge of the
  box in one line.
- **Effort and tier now calibrate to the task when a usage cap can bind
  (quota-aware effort).** The selector's FLAT-FUNDING GATE — which holds the
  frontier tier and defaults EFFORT to the top rung on every posture — used to
  open whenever a subscription was "not reported exhausted", and the service
  derived the `uncapped` consumption-headroom posture from any funded tier at
  or above $200/mo. Both rested on the premise that a top-tier plan's cap
  never binds. It does: a claude.ai Max ($200) operator running eight
  projects concurrently with Fable 5.1 / Opus 5 at `Max` effort exhausted the
  weekly pool with a day and a half left and fell onto pay-per-token usage
  credits (2026-09-21), and Anthropic meters plan usage by model **and** by
  effort level. Now:
  - Gate condition (c) is the declared `Consumption headroom`: only
    `uncapped` ("I never hit my limits") opens the gate; `capped`, no
    declaration (the default), or a `Usage-pool status` of `tight` /
    `exhausted` closes it. The `<thinking-context>` complexity ladder is then
    the **final** EFFORT value, not a floor — the "raise to the top useful
    rung" override fires only under `uncapped`. The `<objective>` worked
    examples no longer anchor Claude Code at `EFFORT: Max`.
  - The service's `auto` headroom resolves to `capped` on every tier;
    `uncapped` is an explicit opt-in. Settings / docs copy describes the
    control as task calibration, and the "Always maximum effort" hint says
    it burns a weekly limit fastest.
  - The front-loaded gate rules in `roadmodel.recommend` (single and ladder
    modes) and the MCP roadmap header carry the `uncapped` condition inline,
    and the roadmap header gains a CAPPED HEADROOM bullet so a phase roadmap
    written for a capped operator no longer lands every step at `Max`.
  - The four daily tracker crons' anti-revert clauses protect the new wording
    (and would otherwise have reverted it).
- **`Usage-pool status` — a new user-context section.** One row per
  subscription pool (e.g. the claude.ai weekly pool, its 5-hour session pool,
  the Fable 50% sub-cap, Codex) with `headroom` / `tight` / `exhausted` and
  the reset time. `<access-selection>` Step C reads it: a `tight` pool is
  kept for High-complexity work and routine tasks go to another funded pool
  that reaches an adequate model; an `exhausted` pool's platforms rank as
  pay-per-token (usage credits bill at list price) until the reset, or as
  unfunded when the row says `overflow off`. This is the hook that turns a
  second coding-agent subscription (Codex on ChatGPT, Antigravity on Google
  AI) into an automatic fallback when the primary pool runs dry. The bundled
  `user-context.example.md` and `docs/user-context-setup.md` document both
  the posture and the table; `docs/model-selector.md` is regenerated.

### Fixed

- **The catalog offered Codex models a ChatGPT subscription cannot run.** The
  single `codex-cli` method listed the `-codex` variants (`gpt-5.3-codex`, the
  `gpt-5.1-codex` family) among its supported models, but a ChatGPT-account
  sign-in answers `400 … "not supported when using Codex with a ChatGPT
  account"` for every one of them — they need an OpenAI API key. The method is
  now split: `codex-cli` (subscription-included, ChatGPT sign-in, GPT-5.x /
  5.6 line only) and `codex-api` (per-token, API key, the `-codex` variants
  included), so the selector can no longer recommend a model the operator's
  funding cannot reach. The Codex tracker cron's anti-revert list protects the
  split.
- **Google joins the model-discovery lane (#652).** `extract_google_catalog`
  now reports Gemini TEXT models the pricing page prices that the catalog
  neither maps nor declines, filtering page furniture ("Gemini Developer API
  pricing") and non-text models (image / video / transcribe / embedding) so the
  flag stays signal. Today it surfaces `Gemini 3.1 Flash-Lite`,
  `Gemini 3.5 Flash-Lite` and `Gemini 2.5 Computer Use`. Groq is now the only
  lane without discovery — its snapshot is a static model list rather than a
  scrape, so it needs its own pass; #652 stays open for that alone.

- **A Codex config pinned to a `*-codex` model is dead on a ChatGPT account.**
  Codex answers `400 … "The 'gpt-5.3-codex' model is not supported when using
  Codex with a ChatGPT account"`, which nothing surfaces until someone actually
  runs it. `roadmodel-update` now repairs that pin to a model the account can
  run (`gpt-5.6-terra`) when `~/.codex/auth.json` exists and no
  `OPENAI_API_KEY` is set, and leaves an API-key setup — where the variants
  still work — alone.

- **The `/recommend` jurisdiction filter had stopped filtering.** The edge's
  cn-jurisdiction guard was a hardcoded pair naming `kimi-k2.5` — a model
  retired in favour of K2.7 / K3 — so for a user who excludes `cn`, every
  current Chinese-jurisdiction model (DeepSeek, GLM, Kimi) passed the edge
  untouched. It is now derived from the catalog (`modelsInJurisdiction`), ids
  and display names both, and the E2E mock and its tests derive the model they
  assert on the same way, so a catalog refresh can never strand them again.
- **xAI joins the model-discovery lane.** `extract_xai_catalog` reports priced
  rows the catalog neither maps nor declines, skipping any whose slug the
  catalog already carries (grok-4.5 rides the aggregator mirror without being
  in the name map, and flagging it every run would train the reader to ignore
  the flag). Today it surfaces `grok-4.7` and the grok-4.20 / grok-build rows.

- **A new OpenAI model could not reach the catalog (`gpt-6-astra`).** Model
  DISCOVERY had exactly one lane — the Cursor pricing page — and the
  provider-direct snapshots were price-only overlays keyed by a hand-written
  name map that dropped every unmapped row in silence. OpenAI has priced
  `gpt-6-astra` ($10/$50) and the GPT-5.6 family on its own page since early
  September; Cursor never listed Astra, so roadmodel never learned it exists.
  Two fixes: (a) the OpenAI and Anthropic extractors now report every priced
  row they neither map nor explicitly decline in `unexpected_slugs` (the field
  the G1 conformance contract already required), each extractor carrying a
  documented `DECLINED` map so the flag list stays signal — today that
  surfaces `gpt-6-astra` on the OpenAI page and `Claude Mythos 5 / 5.1` on
  Anthropic's; (b) `update/prompt.md` makes those flags a first-class
  discovery lane for the daily catalog cron, which must now add each flagged
  model or record why it declines.
- **The OpenAI price lane was silently broken by a docs migration.**
  `platform.openai.com/docs/pricing.md` now redirects to
  `developers.openai.com/api/docs/pricing.md`, which replaced the JS
  `rows={[…]}` arrays with Markdown tables; the extractor's anchors no longer
  matched, so OpenAI prices had frozen at whatever the last successful run
  wrote. The parser reads the `### Standard pricing data` table (short-context
  columns, `$`-formatted, `-` for "not offered"), and the GPT-5.6 family is
  now price-federated from OpenAI instead of riding on Cursor's mirror.
- **`update/render_md.py` matched inline tag mentions.** `_section()` took
  the first `<tag>…</tag>` match anywhere in the file, so a backticked
  reference such as `` `<access-selection>` `` in the `<usage>` prose started
  a section thousands of lines early; the committed `docs/model-selector.md`
  had a "Selection Algorithm" section that began mid-sentence and was ~4x the
  size of the real content. Tags are now anchored to the start of their own
  line (as `validate_effort_conformance.py` already did); the regenerated
  Markdown carries the same 49 model and 17 method cards in a quarter of the
  lines.

### Added

- **`/models` explains its own Score.** A new collapsible panel draws the fit:
  for one cost tier at a time, every measured model as a point (blended price
  on a log axis against the AA Intelligence Index), the tier's fitted price
  line, and each model's Score as the vertical distance from its point to that
  line — so "+6.7" reads as "6.7 index points more than this price usually
  buys" rather than as a rank. The shaded band is ±1 residual σ and the caption
  says how many of the tier's models sit inside it (today: all six Very High
  models — those scores are a tie, not a ranking), which is the honest answer
  to "why is Fable 5.1 +4.6 and Opus 5 +6.7?". The frontier ● is explained in
  the same place as a catalog-wide statement, not a within-tier one. Everything
  is computed from the same rows and fit the table uses.
  `scripts/plot_score_model.py` renders the same figure offline with matplotlib
  for docs and review.
- **The same slash commands on every agent, and runtime parity with them.**
  `roadmodel-update` already generated the four roadmap commands for Claude
  Code, Gemini CLI, Cursor and OpenCode; it now also writes **Codex prompt
  files** (`~/.codex/prompts/<name>.md`, invoked `/prompts:roadmap-phase 1`,
  keeping the `$ARGUMENTS` placeholder Codex expands) and **VS Code prompt
  files** (`<user profile>/prompts/<name>.prompt.md`, invoked
  `/roadmap-phase 1` in the native chat panel). Beyond commands it now syncs
  the **runtime**: the roadmodel MCP server is mirrored from the Claude
  registration into Codex's `config.toml`, Gemini's `settings.json` and
  OpenCode's config — launched exactly as Claude launches it, wrapper script
  and all — and a **reasoning-effort default pinned to the top rung**
  (`effortLevel: max`, `model_reasoning_effort: xhigh`) is stepped down to the
  calibrated default, because that pin is a standing cost on every provider
  that meters a usage pool. Ceilings and deliberate lower values are left
  alone; `--no-calibrate` opts out.
- **`docs/agent-parity.md`** replaces `docs/codex-parity.md` and covers every
  direction, not just Claude → Codex: a symmetric surface map across Claude,
  Codex, Gemini (Antigravity) and open-source clients, and one parameterised
  prompt ("You are TARGET, bring yourself to parity with SOURCE") instead of
  one file per pair.
- **A scoring core in code: `roadmodel score` and the `score_candidates` MCP
  tool.** `roadmodel.scoring` ranks every (model, platform, effort) candidate
  deterministically — no engine call — as
  `quality − requirement_penalty − λ · K · decades(effective cost)`: quality
  from the Artificial Analysis evidence for the task's category (blended with
  the editorial letter; unmeasured letters discounted), a soft penalty for
  missing the complexity's requirement, and a cost term whose exchange rate
  `K` is fitted from the market in the score's own quality units (category
  quality vs. log price) and scaled by budget posture and by the stakes
  (under `balanced` ≈ 30 / 18 / 10 / 5 points per decade of spend for Low /
  Medium / High / novel tasks). Funding,
  `Consumption headroom` and the `Usage-pool status` table are read from the
  user-context, so a subscription pool with headroom, a tight pool, an
  exhausted pool (list price) and a pay-per-token key all price into one
  formula; unfunded paths never win while a funded one exists. The BACKUP is
  the best *funded* other-provider candidate, and a single-provider
  user-context yields an explicit `backup_warning` instead of an unreachable
  name (#642). Every term is returned so a pick can be audited line by line;
  every constant is a named prior for a future usage ledger to calibrate.
  `docs/benchmarks.json` is now bundled in the wheel. Design and integration
  path: `docs/scoring-model.md`. Tier-name matching in `roadmodel.cost` now
  ignores any trailing parenthetical (`(5x)` as well as `($100)`).
- **Numbers next to the letters on `/models`.** The catalog table gains an
  **AA Index** column (the Artificial Analysis Intelligence Index — the one
  published composite number, sortable, `—` where AA has not measured the
  model) and shows each category's headline benchmark figure under its S→D
  letter, labelled as cited (`89.1 TB 2.1` vs `62.9 TB Hard`, `1465 Elo`,
  `~500 tok/s`) because versions and subsets differ. Figures are read from the
  curated `headline_benchmarks` text by `web/lib/benchmark-scores.ts` (pure,
  tested against every prose shape the cron writes; `%` only where the prose
  has it) using the same benchmark→category mapping the cron's tier-update
  rule uses. Sorting a category now orders by letter, then by like-for-like
  figure, then by AA Index, so the eleven S-tier coders no longer sit in
  catalog order.

### Changed

- **DeepSeek V4.1-Flash succeeds V4-Flash (#583, #606).** DeepSeek retired
  `deepseek-v4-flash` (and `-vision-exp`) from its pricing page on
  2026-09-17; the legacy API names are still accepted but served by
  DeepSeek-V4.1-Flash under the new name `deepseek-flash`. The catalog now
  carries `deepseek-flash` in V4-Flash's place — $0.15/$0.60 off-peak, 1M
  context, native image input, AA Intelligence Index 39.5 (v4.3) — with tier
  ratings inherited from V4-Flash except multimodal D→C (image input is now
  native; MMMU-Pro 56.5 is DeepSeek-reported). `deepseek-api`, `ollama` and
  `openrouter` list it; the DeepSeek extractors know the new slug, so the
  successor is federated provider-direct instead of flagged.
- **DeepSeek price basis is explicit.** DeepSeek's page now splits every
  rate into OFF-PEAK / PEAK (peak = 2×, only 01:00–04:00 and 06:00–10:00 UTC
  Mon–Fri). The catalog lists the OFF-PEAK rate — ~79% of the week and all
  US/EU working hours — chosen by its tag in `extract_deepseek_catalog.py`
  rather than by table-row order, recorded in the snapshot as `price_basis`
  with the peak figures kept in `peak_*` fields, and stated in both DeepSeek
  models' pricing notes. Aggregators such as OpenRouter list the PEAK rate,
  so the two are not directly comparable. V4-Pro's stale `$0.87/M` and
  cache-hit figures are refreshed to the current $1.98/M and $0.022/M.
- **S is defined honestly.** The rating scale's single source
  (`web/lib/glossary.ts`, mirrored in `docs/model-selector.txt`,
  `docs/benchmarks-and-ratings.md` and `update/prompt.md`) defined S as
  "top-1 or top-2 globally" while 11 coding, 12 agentic and 13 speed models
  carried it. S now reads "frontier-class: at or within reach of the best in
  this category on the cited benchmarks — a class several models can share";
  the selector's S-tier floors and the letters themselves are unchanged. The
  catalog cron gains a tier-inflation guard: a promotion into S needs a result
  within 5 points of the category's current best on the same benchmark, and a
  category with more than 8 S-tier models emits a
  `tier inflation` warning for editorial review (never an automated demotion).

- **`ollama` and `openrouter` access methods.** The catalog can now
  recommend two access classes it could not express: `Ollama (local)` —
  open-weight models pulled onto the operator's own hardware — and the
  `OpenRouter` per-token aggregator. `docs/model-selector.txt` gains a fifth
  billing type, `local` ($0 per token, throughput bounded by the hardware,
  quality bounded by the quantization pulled, which the tier ratings do not
  describe) and a `local` provider-jurisdiction valid on methods only. The
  `ollama` method lists only catalogued models whose weights are downloadable
  under a licence that permits local use (Apache-2.0 gpt-oss / Mistral; MIT
  DeepSeek V4 / GLM; Modified-MIT Kimi K2.7 Code; Kimi K3 License), verified
  per model; the `openrouter` method lists the catalogued models OpenRouter
  served on 2026-09-20 as a point-in-time snapshot, with its fee-inclusive
  price floor and cross-host routing disclosed. `<access-selection>` changes:
  Step A0 passes a `local` method under every allowed-jurisdictions list;
  Step B **drops** an unfunded `local` method outright (hardware the operator
  does not have is not money they might spend — same precedence and
  disclosure as the Step A00 operator list) while still keeping an unfunded
  `openrouter`; Step C ranks a funded `local` method in the $0 tier; and every
  local pick's RATIONALE must carry the verbatim caveat "local quantized
  weights run below the catalog tier ratings; treat coding and reasoning as
  one tier lower than listed". The `<objective>` FLAT-FUNDING GATE treats a
  funded local candidate as a separate funding class (no usage pool behind
  it), so a Cost-priority prompt can reach a local pick. `cost.py`:
  `_AGGREGATOR_PROVIDERS` gains `openrouter` and `ollama` (neither is ever a
  model's maker; aggregator-only models keep resolving to `cursor`),
  `_resolve_funding` returns `local` / `unfunded-local` from the new
  `_local_runtime_present` / `_parse_local_models` user-context parsers, the
  cost panel renders a funded local platform as `$0 — local hardware` with no
  per-token estimate and omits an unfunded one, and the cross-provider backup
  substitution skips local-only candidates. `docs/user-context.example.md`
  gains an `OpenRouter` key row and a "Local models (Ollama)" section
  (presence row + pulled-models table, shipped empty); the catalog cron treats
  both methods' `supports-models` as hand-maintained; `tests/test_doc_schema.py`
  admits `local` for methods only. Hosted service behaviour is unchanged by
  design (its funding context never funds `local`; `openrouter` becomes a
  valid API-provider declaration automatically).

- **OpenAI-compatible recommender engines.** `roadmodel recommend` / the MCP
  server / `recommend_structured*` can now run on DeepSeek, xAI, Groq,
  Mistral, Z.ai, OpenRouter, Together, a local Ollama server, or any
  `custom` OpenAI-compatible endpoint — one Chat-Completions adapter
  (`providers/openai_compatible.py`, reusing the `openai` SDK from the
  `recommend` extra; no new dependency) bound to a provider table
  (`providers/registry.py`: base URL, key env, default model, and which
  reasoning dial the provider documents). `--provider` / `ROADMODEL_PROVIDER`
  accept the new names; each hosted provider auto-selects from its
  `<PROVIDER>_API_KEY` after the native three; `ollama` (no key) and
  `custom` (`ROADMODEL_BASE_URL` + `ROADMODEL_API_KEY`) are explicit-only.
  `ROADMODEL_MODEL` is the env form of `--model` for every provider and is
  required where there is no default (ollama, custom, aggregators).
  `--thinking-budget` maps onto DeepSeek/Z.ai `thinking` + `reasoning_effort`,
  Groq/Mistral/Ollama `reasoning_effort`, and nothing where undocumented; a
  thinking model that spends its whole output budget reasoning is reported by
  name, and `ollama` / `custom` calls get a 30-minute no-retry timeout instead
  of the SDK's 10 minutes + 2 silent retries. The three native adapters are
  untouched. `docs/byo-key-setup.md`
  gains per-provider setup, the doc-cited base-URL table, and a "Verified
  engines" table from `scripts/eval_recommend_engines.py` (which now takes
  any provider plus `--extra provider:model[:budget]`); the README key table
  lists every env var.

- **`/roadmap-*` for Cursor and OpenCode.** Cursor reads `~/.agents/skills/`
  directly, so the skills the updater already installs for Codex are Cursor's
  `/roadmap-step` etc. — the updater now detects `~/.cursor/` and labels the
  install for both. OpenCode gets generated Markdown commands
  (`~/.config/opencode/commands/<name>.md`, `$ARGUMENTS` native; its
  `` !`cmd` `` and `@path` syntaxes refused). Five agents total: Claude
  Code, Gemini CLI, Codex, Cursor, OpenCode.
- **User-context template lists every federated provider.** The "Active API
  keys" table in `user-context.example.md` (what `roadmodel context init`
  bootstraps) now carries DeepSeek, Mistral, Groq and Z.ai rows alongside
  Anthropic / OpenAI / Google / xAI, each `No` by default with the method it
  unlocks and the jurisdiction it needs — so the `deepseek-api`, `mistral-api`,
  `groq-api` and `zai-api` methods the selector already knows are reachable
  without reading the selector source. `docs/user-context-setup.md` says the
  same in prose.

- **`/roadmap-*` and `/roadmodel-update` for Gemini CLI and Codex.** The
  updater now generates the four commands from `docs/claude-commands/*.md`
  at refresh time — Gemini CLI custom commands (`~/.gemini/commands/
  <name>.toml`, `$ARGUMENTS` → `{{args}}`, literal TOML string so Windows
  paths survive, injection syntax refused) and Codex skills
  (`~/.agents/skills/<name>/SKILL.md`, invoked as `$roadmap-step 1 3`; Codex
  custom prompts are deprecated upstream) — and installs them wherever the
  tool's config dir exists (`--agents` to force, `--commands-only` to refresh
  commands without a project registry). `/roadmap-step`'s settings gate is
  now surface-agnostic: it compares the step's Platform to the surface it is
  running on and names that surface's model/effort controls.
  `docs/planning-workflow.md` "Other agents" documents it. Codex skills go to
  `~/.agents/skills/` only: current Codex (verified on 0.155) reads that AND
  `~/.codex/skills/` as skill roots, so a second copy lists every skill
  twice — the updater removes its own legacy copies (content-checked; a
  hand-written skill of the same name is left alone).

- **`/roadmodel-update` + `scripts/update_projects.py` — upgrade roadmodel in
  every project at once.** The script (stdlib only, Python 3.9+, fetched fresh
  from the repo by the command) reads `~/.config/roadmodel/projects.txt`,
  detects each project's conda env or venv (venv dir → `environment.yml`
  name → conda env named like the folder → conda env inside the project, with
  `| conda:<name>` / `| venv:<dir>` overrides), upgrades `roadmodel` in all of
  them concurrently, re-exports `planning/` where a kit exists, and
  re-downloads the four user-scope command files (mirroring any skills
  copies). Undetectable envs are reported, never guessed into `base`.
  `docs/planning-workflow.md` §5 documents it; `tests/test_update_projects.py`
  covers registry parsing, detection, and the `--dry-run` CLI. Not part of the
  PyPI package — no release needed.
- **`/roadmodel-update --install-schedule [HH:MM]`** registers a daily
  unattended run of the updater for the current user — a launchd agent on
  macOS, a Task Scheduler task on Windows, a crontab entry on Linux — logging
  to `~/.config/roadmodel/update.log` (`--log`, auto-rotated), so every
  registered project follows each release within a day. `--uninstall-schedule`
  removes it. Flags after the command name pass straight through to the script.
- **README** rewritten to the current state: the three surfaces (CLI, MCP
  server, planning kit), a "Staying current" section that leads with
  `/roadmodel-update` for multi-project machines, a plain-language MCP
  paragraph, the `/roadmap-step` + Status-rule workflow, and a Phase 1–3
  shipped / Phase 4 in progress status (was still "Phase 1").

### Fixed

- **`update_projects.py` on Windows conda envs.** Only `Scripts\python.exe`
  (the venv layout) was probed, so every conda project on Windows — where the
  interpreter sits at the env root as `python.exe` — was reported as "not
  created" and skipped, and a `| conda:<name>` override failed the same way.
  `_python_path()` now tries both layouts (and `bin/python3` on POSIX).
  Regression test `test_windows_conda_env_root_python`.
- **Phase template no longer plants a PEM-looking token.** The final QA step's
  secret-scan requirement listed the private-key header pattern literally, so
  every `export-kit` re-introduced a string that projects' own secret scanners
  flag. It now describes the pattern ("the five-dash BEGIN line") instead.

## [0.2.37] — 2026-09-20

### Added

- **Roadmap templates: the roadmap on `main` is the ledger (Status rule).**
  Both templates now give every step (phase template) and every phase
  (project template) a `**Status:**` line — `Not started` when the roadmap
  is written — and Stage 3 of the step lifecycle becomes "Open the PR, then
  mark the step": right after `gh pr create` returns the number, the agent
  flips the line to `Complete — PR #n (date)`, commits it on the step branch,
  and pushes, so the roadmap on `main` marks a step complete exactly when its
  PR merges — never before, and never by a later chat reconstructing history
  from `git log`. A phase's final QA step marks the phase the same way in the
  parent roadmap (its `**Status:**` line, a new Status column in the §8
  summary table, the header status line). Stage 6's completion line now
  presupposes the mark. This retires the "update ROADMAP.md and the phase
  roadmaps so completed steps are marked complete" reconciliation ask.
- **`/roadmap-step` Status gate + legacy backfill.** The command refuses to
  start a step that already reads `Complete`, and refuses to start Step M
  while Step M-1 does not (unless the Execution Order draws them in
  parallel) — reporting whether the previous PR is unmerged or its mark was
  skipped via `gh pr list --state merged --head <branch>`. Roadmaps written
  before this release (no Status lines) are backfilled once, in the current
  step's PR, from the same deterministic lookup. `docs/planning-workflow.md`
  documents the gate, the mark, and the backfill.

### Changed

- **Paste-prompts' kit-currency check** (Step 0) now also requires the
  template's Stage 3 to read "OPEN THE PR, THEN MARK THE STEP", so a
  pre-0.2.37 kit fails loudly instead of producing roadmaps without Status
  lines. `tests/test_roadmap_templates.py` guards the new wording across both
  templates, both prompts, and the command.

## [0.2.36] — 2026-09-20

### Fixed

- **`export-kit --force` could replace a real kit `user-context.md` with the
  blank template.** On a machine without the curated
  `~/.config/roadmodel/user-context.md` (a second PC, CI), `--force` fell
  through to "seed the template" and clobbered the project's real file. Now
  `--force` means "refresh from my curated file" only: with nothing to copy
  from, the kit's existing user-context is kept and the output says so. The
  kit prompts' Step 0 runs `export-kit . --force` on every machine, so this
  path is hit routinely. Regression test
  `test_export_kit_force_never_clobbers_with_template`.

### Added

- **`/roadmap-step P M`** (`docs/claude-commands/roadmap-step.md`): executes
  step M of phase P straight from the phase roadmap — finds `## Step M`, reads
  its Branch line, Settings table, `<task>` block and acceptance criteria,
  gates on the session model / platform (prints the required Effort and
  Thinking as the operator's cue), applies the current Stage 6 even to
  pre-0.2.34 roadmaps, then runs the task from Stage 1. No more copying the
  XML block by hand. `docs/planning-workflow.md` §4 documents it.

## [0.2.35] — 2026-09-17

### Added

- **Planning kit: fill-in paste-prompts.** `roadmodel export-kit` and
  `scripts/export-planning-kit.sh` now ship `planning/prompts/project-roadmap.md`
  and `planning/prompts/phase-roadmap.md` — copy one, fill the `{{placeholders}}`
  table, paste into a new chat, submit — instead of retyping "use roadmodel to
  write the Phase N roadmap" each phase. Each prompt opens with a Step 0 that
  refreshes the kit (`pip install -U roadmodel && roadmodel export-kit .
  --force`) and checks the template's Stage 6 is current before writing, so a
  stale kit fails loudly rather than baking an old step lifecycle into every
  step. HOW-TO-USE.md and both exporters' "Next:" hints point at the prompts.
- **`docs/planning-workflow.md` + `docs/claude-commands/`.** The reference for
  the whole planning workflow, and the two user-scope Claude Code commands
  (`/roadmap-project`, `/roadmap-phase N`) that execute the kit's prompts —
  copy them to `~/.claude/commands/` once per machine.

## [0.2.34] — 2026-09-17

### Changed

- **Bundled Claude Code notes refreshed through 2.1.273** (#594, #595,
  #596): version notes only; the `/effort` vocabulary and extended-thinking
  controls are unchanged.

### Fixed

- **Roadmap templates: "done" means done — no more "Follow-ups" trailer.**
  0.2.32's step-completion signal told the agent to put caveats and newly
  found issues in a "Follow-ups (non-blocking)" note *after* the "Step N is
  complete" line. In practice every completion arrived with a paragraph of
  undisposed findings, which reads as "not actually done". Stage 6 in both
  templates (STYLE RULES, the Overview lifecycle, and the per-step XML
  `<lifecycle>` block) is now dispose-before-declare: every finding reaches
  its Triage destination first — a note for a later step is edited into
  that step's `<task>` block, a judgement call goes in the PR body, a bug is
  fixed or is an issue number — and a finding that is only described counts
  as an unmet criterion. The completion line is the last line of the
  response; nothing follows it. The final QA step gains a "Phase closed,
  nothing carried" criterion and the phase-level line "Phase N is complete.
  You can now move on to Phase N+1." `tests/test_roadmap_templates.py`
  guards the wording in both templates.

## [0.2.33] — 2026-09-12

### Fixed

- **The cost scale still priced Claude Sonnet 5 at $3/$15 (High).** 0.2.31
  corrected the selector to Anthropic's $2/$10, but the bundled
  `model-tier-cost-scale.md` — which the recommender prompt also carries —
  kept the stale row and a "launch promotion through August 31, 2026" note,
  so the engine was reading two contradictory prices for the same model. The
  row now reads $2/$10 (Medium), the promotion clause is retired, and the
  selector's `pricing-notes` are re-synced byte-for-byte with the Notes
  column.

### Added

- **Muse Spark 1.3 and GPT-5.1 Codex Mini enter the catalog** (49 models).
  Muse Spark 1.3 is the first Meta model — a new "API Pool — Meta"
  cost-scale section and a `us` row in the provider-jurisdiction table come
  with it — at $1.25/$4.25 (low tier) with placeholder B ratings pending
  editorial review. GPT-5.1 Codex Mini lands at $0.25/$2.00 (low tier, hidden by
  default on the aggregator) with placeholder ratings set one tier below
  `gpt-5.1-codex` on coding and two below on planning/agentic per the
  catalog's Mini-variant convention, speed S. It is deliberately NOT an
  S-tier coder: the refresh had inherited the parent's S rating and made the
  Mini the cost tie-breaker favourite for S-tier coding picks, which the
  audit reverted until a head-to-head says otherwise.

### Changed

- **Subscription-tier descriptions refreshed (reviewed 2026-09-10):** Claude
  Pro names Opus 5 / Sonnet 5 / Fable 5.1; ChatGPT Plus and Pro name the
  GPT-5.6 family. The classification audit adds Fable 5.1, Grok 4.6, and
  Gemini 3.7/3.8 Flash and marks the GPT-5.6 Sol/Terra tier moves resolved.
- **Held back:** DeepSeek's page replaced `deepseek-v4-flash` with a new
  `deepseek-flash` (V4.1-Flash, $0.15/$0.60) slug. The provider snapshot is
  kept at its previous state until the successor is added and V4 Flash is
  retired together (#583); `deepseek-v4-flash` stays priced from the
  aggregator mirror meanwhile.

## [0.2.32] — 2026-09-12

### Added

- **The roadmap templates gain worktree, release & deployment, defect-triage,
  and operations strategies.** The bundled project template's §5
  Cross-Cutting Concerns previously carried a branch strategy and a per-step
  security gate but stopped at squash-merge. It now adds a "Worktree
  strategy" (one working tree by default; `git worktree add` is sanctioned
  for exactly three cases — a hotfix interrupting a step, steps the
  sequencing diagram draws in parallel, and worktree-isolated subagents —
  with location, bootstrap, and retirement rules; `git branch -D` refuses a
  branch still checked out in a worktree, so Stage 5 removes the worktree
  first), a "Release & deployment strategy" (merged is not deployed and
  deployed is not released: a deployable-surfaces table, staged rollout, a
  readiness gate before irreversible cutovers, secrets proven by an
  authenticated round-trip, migrations on the deploy path, post-deploy
  verification, rollback, and version floors), a "Defect handling & triage"
  section (spec rot, upstream gap, implementation bug, architectural
  question, process improvement, security finding — one destination each,
  plus scope discipline, track-before-defer, verify-the-close, and
  prevent-the-class), and an "Operations & observability strategy" (health
  signals, a heartbeat for scheduled automation, a ledger and cap for metered
  dependencies, runbooks, and an alarm-must-fire acceptance rule). The
  per-step security gate gains rule 5: the CI/CD pipeline is a trust
  boundary (SHA-pinned actions, least-privilege permissions, OIDC publish,
  protected environments, no secrets on untrusted triggers). The phase
  template mirrors all of it: "Worktree rule", "Deploy-and-verify rule", and
  "Triage rule" paragraphs in the Overview, a `**Deploys:**` line on every
  step, Stage 1/4/5 hooks in both the prose lifecycle and the per-step XML
  `<lifecycle>` block, a "Deployed & verified" acceptance bullet whenever a
  step's merge reaches a deployed surface, and an operations bullet on the
  final QA step.
- **Phase template: an explicit step-completion signal.** Stage 6 of the
  step lifecycle now requires the agent to end its final response with the
  verbatim line "Step N is complete. You can now move on to Step N+1." — and
  only once the PR is merged and every acceptance criterion is affirmatively
  met. Caveats and newly found issues go in a "Follow-ups (non-blocking)"
  note after that line, never around it; an unmet criterion means the agent
  says the step is NOT complete and withholds the line. Operators running a
  roadmap one step per conversation get a clean stopping point instead of
  an "are we done?" round-trip.

### Changed

- **Claude Code surface parameters catch up through 2.1.269.** 2.1.263 to
  2.1.266 change nothing on the effort/thinking surface. 2.1.267 adds a
  `maxEffortLevel` setting (top-level or per model under `modelSettings`)
  that caps the reachable effort level on every provider, including Bedrock,
  Vertex, and Foundry; the selector documents it as an admin upper bound on
  the existing `/effort` vocabulary, not a new dial. It also fixes `effort:`
  frontmatter on custom commands, skills, and subagents being ignored on
  models whose default effort is still pinned. 2.1.269 adds
  `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (1–256) to raise the Workflow
  tool's per-run concurrent-agent cap; it does not change the `/effort`
  vocabulary or the `ORCHESTRATION` mapping.
- **Fable 5 and Fable 5.1 may now map to `THINKING: Off`.** The selector
  previously said both models could not disable extended thinking and
  forbade emitting `Off` for them; Anthropic's model-config docs list no
  model under `cannot_disable_on`, so the tracker reconciled the rule to
  match the docs. Flagged for editorial confirmation against Anthropic's own
  model pages.
- **Gemini 3.7 Flash and 3.8 Flash thinking levels** are recorded as
  low/medium/high without `minimal`, and the Flash-line models that do expose
  `minimal` are now listed by name.
- **DeepSeek `reasoning_effort` gains `low`** alongside `high` and `max` on
  the deepseek-api method.
- **Catalog refresh retires superseded models automatically.** The removal
  rule the catalog cron follows moved from MAY to MUST: when a same-series
  successor is available at equal or lower output price, the predecessor is
  retired in the same refresh, with `flash` and `fable` added to the
  variant-tier list so those lines stop reading as ambiguous series. Two
  guards land with it: retirement is deferred when the successor is benched
  in `infra/model-availability.json`, and a new gate check (G6) makes it
  fatal to retire a model that is itself benched, since the runtime override
  references ids by name and would silently become a no-op. No model left
  the catalog between 0.2.31 and 0.2.32.

## [0.2.31] — 2026-09-05

### Fixed

- **Claude Sonnet 5 was priced 50% too high.** The catalog carried $3/$15 per
  Mtok from the aggregator mirror; Anthropic's own pricing page lists $2/$10,
  and has since the launch promotion became the standard rate. The model moves
  from the high cost tier to medium as a result. Two silent failures hid it:
  `update/extract_anthropic_catalog.py` had been raising on every run since
  Anthropic restyled a table header (`Base Input Tokens` -> `Base input
  tokens`) against a case-sensitive anchor check, and the catalog cron's
  per-provider fail-open swallowed the error; and `claude-opus-5`,
  `claude-sonnet-5` and `claude-fable-5.1` were never added to that
  extractor's name map, so no Anthropic price the selector quotes for them was
  ever reconciled against Anthropic's own page.
- **The refresh crons were failing daily and nothing said so.** The catalog
  cron had failed 15 days running and the Claude Code cron 24, both because
  their shared output ceiling (`max_tokens = 64000`) had grown too small for
  the payloads they emit — measured at 66,690 and 64,099 output tokens. The
  staleness guard that should have caught it ran as a per-PR test, so it
  turned every pull request red, including the ones that would fix the crons.
- **A `>` in provider prose deleted catalog entries.** Six modules each
  carried their own element regex that could not span a `>`. Cursor's
  "long context (>272k)" note dropped `gpt-5.6-sol`, `gpt-5.6-terra` and
  `gpt-5.6-luna` from `catalog.json`; Anthropic's `/advisor <model>` dropped
  the entire Claude Code platform. Element matching is now shared, quote-aware,
  and fatal when a parse loses an entry.

### Added

- **Claude Fable 5.1, Grok 4.6, Gemini 3.7 Flash and Gemini 3.8 Flash enter the
  catalog**, which now carries 47 models across
  15 access methods. Tier ratings are inherited from
  each model's series predecessor and flagged for editorial review.
- **`.github/workflows/cron-health.yml`**: a daily alarm that checks every
  scheduled cron's last completed run *and* whether an automated refresh has
  landed recently, files one deduplicated tracking issue, and closes it on
  recovery.

### Changed

- **GPT-5.6 price cuts flow through to tiers**: Sol $5/$30 -> $4/$20 (very
  high -> high), Terra $2.50/$15 -> $2/$12 (high -> medium), Luna $1/$6 ->
  $0.20/$1.20.
- **Claude Code surface parameters catch up on 24 days of releases**
  (2.1.235 - 2.1.261), including Fable 5.1 as the new default Fable.

## [0.2.30] — 2026-08-11

### Added

- **Claude Opus 5, Gemini 3.6 Flash, and Kimi K3 enter the catalog.** Opus 5
  lands in the very-high cost tier ($5/$25 per Mtok) rated S for coding,
  planning, agentic, long-context, and knowledge, grounded in AA Intelligence
  Index 60.7 (max), HLE 52.6%, and Terminal-Bench 2.1 89.1; it is reachable via
  `anthropic-api`, `claude-code`, `claude-web`, and `cursor`. Gemini 3.6 Flash
  joins the low-cost tier ($1.50/$7.50) and Kimi K3 the high-cost tier ($3/$15).
  The catalog now carries 43 models.

### Changed

- **Output contract version 2: every setting field is now PLATFORM-CONDITIONAL,
  and the reasoning LEVEL moved out of `THINKING` into a new `EFFORT` field.**
  `<output-format>` in the bundled selector now opens with
  `OUTPUT CONTRACT VERSION: 2`. A block always emits `MODEL`, `BACKUP`,
  `PLATFORM`, `CONVERSATION`, and `RATIONALE`; the runtime dials are emitted
  only where the chosen platform actually has them:
  - `MAX MODE` iff the access method's `exposes-max-mode="yes"` — today Cursor
    alone. v1 emitted the line on every block and pinned it `Off` off-Cursor,
    which is how the README's own front-page example ended up advertising
    "MAX MODE: On" under "PLATFORM: Claude Code" — a setting no Claude Code user
    can apply.
  - `EFFORT` and `THINKING` iff `exposes-thinking="yes"`. `EFFORT` carries the
    level (`Low/Medium/High/XHigh/Max/Ultracode`); `THINKING` is now a
    two-position toggle (`On`/`Off`) and never carries an effort word. v1's
    single `THINKING` field carried both meanings.
  - `ORCHESTRATION` iff `exposes-orchestration="yes"` — today Claude Code alone
    — and its value set narrows to `None`/`PerPrompt`.
  A dial the surface lacks means **the line is absent**: never `Off`, never
  `N/A`, never an em-dash. Every line a block emits must be a control the
  operator can literally set on the named platform.
- **Supersedes the 0.2.14–0.2.17 settings narrative.** Those entries describe the
  v1 axes as the intended design and now read as contradictory, so read them as
  history:
  - 0.2.15 introduced `ORCHESTRATION` with `Ultracode` among its values and
    `N/A` off Claude Code. In v2 `Ultracode` is not an orchestration value at
    all (it is the top rung of `EFFORT`), and a platform without orchestration
    omits the line instead of emitting `N/A`.
  - 0.2.16 folded `ORCHESTRATION: Ultracode` into the effort value **at the
    display layer only**, explicitly leaving the selector's vocabulary
    unchanged. v2 promotes that fold into the contract itself: `Ultracode` is an
    `EFFORT` value emitted by the selector, not a presentation-time rewrite.
  - 0.2.17 reframed a Cursor pick as `thinking: "On"` so it would not render as
    "Thinking: N/A". v2 removes the question: Cursor exposes no reasoning dial,
    so a Cursor block emits `MAX MODE` and carries no `EFFORT` or `THINKING`
    line to reframe.
  - 0.2.26's "OpenAI API renders Intelligence, not a spurious Max Mode" fix is
    now the general rule rather than a per-surface patch — no non-Cursor surface
    emits `MAX MODE` under v2.
- **Downstream parsers keyed on field names must dual-accept.** Cached engine
  responses, older `roadmodel` releases running in production, and previously
  exported offline planning kits all still emit v1 blocks. A v1-only consumer
  will not find `MAX MODE` on most v2 blocks and will mis-read a v2 `THINKING`
  value as an effort level. Treat every setting field as optional, and when
  `EFFORT` is absent but `THINKING` carries an effort word, read that as the v1
  level.
- **Platform allowlist / denylist (`<access-selection>` Step A00).**
  `user-context.md` may declare `platforms.allowed` / `platforms.excluded` —
  access-method ids applied as HARD filters before scoring, outranking the
  "never hard-exclude an unfunded access method" guardrail (an operator opting
  out of a surface is not the same as that surface being unfunded). Both keys
  are optional and an absent or empty section means "no opt-out declared", never
  "allow nothing", so existing hand-edited context files are unaffected. See
  `docs/user-context.example.md`.
- **Flat-funding gate (`<objective>`).** When the platform is
  subscription-funded, the family is covered, and the budget is not exhausted,
  the selector HOLDS the capability tier and defaults `EFFORT` to the top useful
  rung on every posture including Cost, differentiating Cost/Balanced/Quality on
  latency, context, and blast radius instead — and saying so in the RATIONALE
  when they converge rather than manufacturing a spread. Per-token paths keep
  the previous tier-down behavior.
- **User-facing docs, templates, and the planning kit follow the contract.** The
  README example, `docs/mcp-tools.md`, `docs/byo-key-setup.md`, and the roadmap
  templates now describe "`MODEL` / `BACKUP` / `PLATFORM` / `CONVERSATION` /
  `RATIONALE` plus the setting fields the chosen platform exposes" instead of a
  fixed six-field list; the phase-roadmap template's Settings-table variants
  drop Max Mode everywhere except Cursor. `scripts/export-planning-kit.sh` also
  now ships `settings-display.md`, which `roadmodel export-kit` already
  included — shell-exported kits previously carried the selector without its
  display contract.

## [0.2.29] — 2026-07-22

### Fixed

- **Rationale no longer calls the recommended model "unavailable / outside your
  access."** The `<availability-context>` substitution example literally used
  "Fable 5" as its unavailable-model example, so when the engine picked Fable 5
  it parroted the example verbatim — producing a self-contradictory rationale
  ("Fable 5 is the strongest fit … Fable 5 was outside your access and was not
  recommendable"). The example is now model-neutral, and both SAAS headers +
  the selector carry a hard guard: the RATIONALE must NEVER describe the model
  it is RETURNING (MODEL or BACKUP) as unavailable, outside access, or not
  recommendable — an availability/jurisdiction/access disclosure may name only a
  DIFFERENT, dropped model. Verified with gpt-5-mini (3/3 clean rationales on the
  Fable-5 trigger prompt).

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
