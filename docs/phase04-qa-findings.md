# Phase 4 — QA findings

Verification rollup for Phase 4 (auth, profiles/onboarding, `/roadmap`
builder, history + export, model tiering + provider-side caching, warm-path
latency, app-shell). Produced alongside `scripts/verify-phase04.sh`
(Step 9). Public launch (Step 8) is **deferred to the end of the phase** by
maintainer decision — the site stays password-gated + `noindex` until a
deliberate gate-lift, so launch acceptance is reported `[PEND]`, not failed.

## Verification surface

`scripts/verify-phase04.sh` mirrors the Phase 1–3 verify scripts (same flag
set + `record_pass`/`record_fail` format):

| Mode | What it runs |
| --- | --- |
| `--fast` (CI) | 35 static deliverable checks + a V1–V9 structural rollup (no network) |
| `--api` | root `pytest` (deselect live-net + PG migration test) + service `pytest` |
| `--web` | `npm ci` + lint + typecheck + build |
| `--ui` | Playwright (`web/tests/`) |
| `--all` | `--api` + `--web` + `--ui` |
| `--post` | V-rollup + live `/healthz` (gated) + Step 8 launch checks (`[PEND]`) |

`.github/workflows/phase-verify.yml` runs `--fast` per phase in the `verify`
matrix (now `["01","02","03","04"]`).

## Status by step

| Step | Deliverable | Status |
| --- | --- | --- |
| 1 | Supabase Auth (magic-link + GitHub OAuth, middleware session, `/callback`) | ✅ shipped; GitHub OAuth verified live |
| 2 | `profiles` + onboarding + `/api/profile` | ✅ shipped |
| 3 | `/roadmap` shell (Chat/Preview panels) | ✅ shipped |
| 4 | Roadmap AI (Gemini 2.5 Flash) + engine decision | ✅ shipped; works end-to-end in prod |
| 5 | History + Markdown export | ✅ shipped; export verified (18 KB md) |
| 6 | Tiering resolver + Gemini `cachedContent` | ✅ shipped |
| 7 | Warm-path latency | ✅ P50 ≤3s met; P95 tail closed (`max_output_tokens=512`) |
| 8 | Public Readiness Gate lift / launch | ⏸ **deferred** (gate intentionally active) |
| 9 | `verify-phase04.sh` + this doc + CI matrix | ✅ shipped |

## Dogfooding bug chain (found + fixed pre-launch)

Driving the gated app surfaced a chain of defects in the roadmap builder,
each masking the next — all fixed + verified in prod:

| # | Severity | Finding |
| --- | --- | --- |
| #155 | P0 | `/roadmap` returned the Phase-5 stub for everyone (`z.coerce.boolean("false")===true` forced `FRONTIER_ROADMAP_ENABLED` on). Drift guard: static check 21. |
| #161 | P0 | prod-only Gemini 400 — `cachedContent` + `systemInstruction` sent together. |
| #157 | bug | roadmap monthly cap charged failed attempts + was too low (3/30d). |
| #158 | bug | preview panel never populated — draft parser rejected numbered headings. |

## Recommend surface

- #164 ✅ — `/recommend` now populates `session_cost_estimate` + the funding-ranked
  comparison table (best-effort; degrades to an empty panel rather than 500ing
  on an unresolvable platform).
- #163 ⏸ — personalizing the cost tie-break by each signed-in user's *own*
  subscriptions needs a `roadmodel` 0.2.4 release (per-request user-context
  through the cost API); deferred (low present value — the bundled context
  already matches the founder).

## App-shell (dogfood UX cluster)

- #154 ✅ `/settings` page · #153 ✅ global nav · #152 ✅ catalog-derived
  subscription picker (all 14 tiers, provider-grouped).

## Known deferrals / follow-ups

- **Step 8 launch** — the deliberate gate-lift PR (remove `web/app/gate/`,
  robots launch-mode, purge `SITE_PASSWORD`, submit sitemap) + ≥3 external
  beta testers, when the maintainer crosses the launch gate.
- **#5** — recommender parser fenced-JSON bug (package → 0.2.4).
- **#148** — paid-tier large-input ingestion (Phase 5).
