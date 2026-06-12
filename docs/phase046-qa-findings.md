# Phase 4.6 — Catalog-source federation: QA findings

Verification rollup for Phase 4.6 (de-Cursor the catalog SSOT; federate the model
registry across per-provider official sources). Static + lane checks are codified
in [`scripts/verify-phase046.sh`](../scripts/verify-phase046.sh) and run on every PR
via the `046` entry in `.github/workflows/phase-verify.yml`.

## What the phase delivered

`price = f(model, platform)`. Cursor is demoted from the single source of truth to
one availability source; each provider's own page (or, where none is
machine-readable, a manually-maintained snapshot) is authoritative for that
provider's prices, enforced in CI.

| Step | Outcome | PR(s) |
| --- | --- | --- |
| **T1** | 7 design decisions ratified (provider-direct, not an aggregator SSOT). | — |
| **T2** | Federation chassis: `merge_catalog.py` (compose + precedence + de-clobber overlay), `validate_catalog_conformance.py` (G1-G3), and DeepSeek as the first provider-direct source; then DeepSeek made recommendable. | #239, #240 |
| **T3** | Anthropic / OpenAI / Google / xAI migrated to provider-direct price sources behind a **G4 price-provenance gate** (selector price MUST equal the provider snapshot). | #241, #242, #243 |
| **T3 follow-ups** | codex + gemini-3-pro recorded as intentional Cursor-sourced exceptions (no provider-direct source); DeepSeek V4 tier ratings benchmark-confirmed from Artificial Analysis. | #244, #245 |
| **T4** | Cursor cron made federation-aware (prompt preserves provider-direct prices, never re-derives them) + a **deterministic price overlay** so the gate is green by construction and provider price changes auto-flow (selector + cost-scale). | #246, #247 |
| **T5** | **Mistral** onboarded — first brand-new provider through the chassis (zero `merge_catalog` change) — closing the **EU-jurisdiction gap** (an `[eu]`-only filter now returns ≥1 rec); reasoning dial documented in `<thinking-context>`. | #248, #249 |
| **T6** | This verification script + QA doc + the `046` CI-matrix entry. | (this PR) |

The registry now spans **us / cn / eu** across **6 provider snapshots** (anthropic,
openai, google, xai, deepseek, mistral).

## Per-step notes

- **Provider-direct sources are heterogeneous by necessity.** DeepSeek (HTML table),
  Anthropic (Markdown table), OpenAI (JS array), Google (HTML section-walk), xAI
  (Markdown + browser headers). Each extractor is deterministic, fail-loud on a
  restructure, and hashes extracted *facts* (not raw HTML).
- **Two overlay modes.** `whole-element` (off-Cursor models the Opus pass would drop —
  DeepSeek, Mistral: re-added from the committed selector) vs `price-only` (on-Cursor
  models whose benchmark tier ratings stay Cursor-maintained — only the price is
  gated). `merge_catalog --write` reconciles both against the snapshots post-Opus.
- **Cost-scale exemption.** Models kept out of `build_catalog.SELECTOR_TO_COST_SCALE_NAME`
  (DeepSeek, Mistral) are exempt from the cost-scale cross-doc tests, so onboarding
  them never required cost-scale surgery.

## Deliberate scope decisions (not gaps)

- **codex (`gpt-5.3-codex`, `gpt-5.1-codex`)** stay Cursor-sourced: OpenAI publishes no
  clean per-token USD price for these SKUs (the Codex pages price the product in
  credits against base models; aggregator USD figures are rejected).
- **`gemini-3-pro`** stays Cursor-sourced: Google delisted the standalone text SKU
  (only "Gemini 3 Pro Image" remains).
- **Mistral has no machine-readable price source** (both its pricing and reasoning docs
  are JS SPAs). Catalog prices are a **manually-maintained snapshot** + a drift-checker
  (`extract_mistral_catalog.py` confirms model-name presence; it does not parse prices);
  the reasoning dial is **documented** in `<thinking-context>` rather than pinned by a
  conformance check (the `reasoning_effort` enum is ambiguous: `none`/`high` surfaced,
  `low`/`medium` may also be accepted). Both promote to real auto-trackers if Mistral
  ships a machine-readable source.
- **No check G.** Unlike the four reasoning-dial trackers (CC/Codex/Gemini/DeepSeek),
  Mistral's dial is not gated — see the Mistral reasoning note above.

## Post-T6 follow-ups (resolved)

- **Model-list federation — DONE (flag-only).** The last SSOT residue was *model
  discovery* (a model had to appear on Cursor's page to auto-flow into the registry).
  `merge_catalog.py --check-additions` now emits any provider-direct snapshot model not
  yet in `<model-options>`, and the catalog cron opens a **deduped** `catalog-unfederated-model`
  issue for an editorial add (with tier ratings — the DeepSeek/Mistral path). Discovery
  is de-Cursored; a model is **never auto-added** (no unrated model surfaces), so there is
  zero behavior change. No-op today (`proposed_additions == []`).
- **`web/lib/model-routing.ts::inferProvider` — DONE.** Now recognizes `deepseek-` /
  `mistral-` / `codestral` (was `"unknown"`).

## Standing maintenance note

- **Mistral prices are manually verified** (2026-06-12 from the rendered pricing page);
  re-verify by eye when the page changes — `extract_mistral_catalog.py` only catches a
  delisting/rename (model-name presence), not a silent price change. Promote it to a real
  extractor if Mistral ships a machine-readable source.

## How to run

```sh
scripts/verify-phase046.sh --fast   # static deliverable checks (CI; Ubuntu-safe)
scripts/verify-phase046.sh          # static + pytest (federation)
scripts/verify-phase046.sh --post   # static + conformance gate + pytest (CI post job)
scripts/verify-phase046.sh --all    # static + ruff + format --check + mypy + pytest
```
