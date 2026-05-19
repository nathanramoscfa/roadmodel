<!-- infra/README.md -->
# Infrastructure runbook

> **Audience:** the maintainer (and any future maintainer with full
> repo access). This file is the single source of truth for the
> managed-service projects roadmodel runs on from Phase 3 onward:
> their IDs, dashboard URLs, env var schema, DNS records, TLS
> posture, provider-side cost ceilings, uptime monitors, the
> seven-step re-provisioning runbook, and the disaster-recovery
> floor those caps establish for Phase 7. Vendor names are spelled
> out verbatim here because this file is **private to the repo's
> trusted operators** — the public-facing `ROADMAP.md` at the repo
> root describes the same stack in provider-agnostic terms and is
> lint-protected by [tests.yml](../.github/workflows/tests.yml)'s
> `roadmap-sync` job against vendor leakage.

**Status:** Schema, decisions, env vars, and cost ceilings are
locked in by this commit. The project IDs, dashboard slugs, and
UptimeRobot monitor ID get filled in by the maintainer immediately
after walking the [Provisioning sequence](#provisioning-sequence)
in the three vendor consoles; until those values land here, the
fields read `TBD (fill in after step N)`. The post-provisioning
edit is committed as a follow-up `docs(infra)` PR, not amended
into the Step 2 squash.

---

## Cloud projects

The three vendors Phase 3 stands up. Stripe (Phase 5) and the
Cloudflare / secrets-store / observability stack (Phase 7+) are
deliberately out of scope here — they're additive layers on top of
this baseline.

| Project           | Vendor   | Project ID                     | Dashboard URL                                                    | Staging URL                              | Production URL          | Provisioned    |
| ----------------- | -------- | ------------------------------ | ---------------------------------------------------------------- | ---------------------------------------- | ----------------------- | -------------- |
| `roadmodel-web`   | Vercel   | `prj_1emPjG8EamGB5G942ipNjjeqh8NX` (team `team_5uU81P0Gl4i22rBjMSwDRsLR`, slug `roadmodel`) — GitHub preview deployments paused 2026-05-19; resume in Phase 3 Step 4 when Next.js scaffold lands | `https://vercel.com/roadmodel/roadmodel-web` | `https://staging.roadmodel.ai` | TBD (cut in Step 7) | 2026-05-17 |
| `roadmodel-service` | Railway | `09b49af8-35b0-4cbd-8c6b-803960ebfe6a` (service `75adcf42-a1ee-44d4-8c8e-b2c576fc6515`, env-prod `651137a1-2331-4991-bf66-c0456163a48d`, env-staging `d79822c4-9676-4910-8606-ea5e98099ed3`) | `https://railway.com/project/09b49af8-35b0-4cbd-8c6b-803960ebfe6a` | Railway-issued default domain (generated in Phase 3 Step 3 when FastAPI ships) | TBD (cut in Step 7) | 2026-05-17 |
| `roadmodel-data`  | Supabase | `nbxzpqnmafcayeqnfvcv` (org `mkvjpvgvuhhzkzfyhvsp`, region `us-east-1`) | `https://supabase.com/dashboard/project/nbxzpqnmafcayeqnfvcv` | Same dashboard, `staging` schema | Same dashboard, `prod` | 2026-05-17 |

Vendor rationale (frozen by Step 2; revisit only on a documented
incident):

- **Vercel for the Next.js 15 web tier.** Auto-issued
  Let's Encrypt TLS, preview deployments per PR, edge-cached SSR
  out of the box, and the App-Router toolchain is first-party
  there. Cost at pilot scale (`Pro` plan) is the bottom of the
  range projected in `private/ROADMAP.md` §5.

  > **Status (2026-05-19):** GitHub preview deployments are
  > **paused**. Vercel is configured to watch
  > `nathanramoscfa/roadmodel` per the Step 1 provisioning recipe
  > below, but no Next.js code lands until Phase 3 Step 4, so
  > every PR before Step 4 triggers a doomed-to-fail build (the
  > repo has no `package.json`, `next.config.*`, or `tsconfig.json`
  > for Vercel's framework auto-detection to pick up). This is
  > the same "provisioned but muted" pattern used for the
  > [UptimeRobot monitor](#uptimerobot-monitors) at the end of
  > Step 2 — the integration is correct, just ahead of its
  > consumer. Resume previews from the Vercel dashboard
  > (Settings → Git → "Deploy Hooks" / "Ignored Build Step"
  > toggles, or just disconnect and reconnect the GitHub repo)
  > the moment the Phase 3 Step 4 Next.js scaffold lands. The
  > [Vercel preview check failure on PR #71+](https://github.com/nathanramoscfa/roadmodel/pull/71)
  > is the canonical example of what this avoids.
- **Railway for the Python FastAPI recommender service.** A managed
  Python runtime with deploy-on-push, per-PR ephemeral services,
  and zero-config TLS on the Railway-issued domain. Fly.io was
  considered and rejected: Fly's stronger primitives (multi-region,
  Machines API) aren't needed at pilot scale, and Railway's
  GitHub-native deploy flow halves the per-step glue at this stage.
- **Supabase Pro for Postgres + Auth + Storage.** Pro tier — not
  Free — because Phase 4's audit log needs the row-count headroom
  and Phase 7's disaster-recovery posture relies on Supabase Pro's
  daily backups. Self-hosted Postgres was considered and rejected:
  Auth + Storage would have to be glued back together separately,
  and the maintainer's bandwidth doesn't cover ops at this stage.

## Environment variables

The full env var schema both tiers read. Step 3 wires the FastAPI
consumers, Step 4 wires the Next.js consumers, Step 5 sends the
`ROADMODEL_INTERNAL_TOKEN` from Next.js → FastAPI, Step 6 consumes
the Upstash pair for the rate limiter. Documenting them all here
is deliberate — Step 6 should not relitigate the Upstash decision.

> **Status (2026-05-18):** None of the application env vars below
> are set on Railway staging or production yet — verify with
> `railway variables --environment <staging|production>` before
> assuming. The Phase 3 Step 3 deploy verification surfaced that
> Step 2's claim of "set on both envs" was wrong. The first
> staging deploy that needs them ([Step 3 healthz](#)) requires
> at minimum `ROADMODEL_INTERNAL_TOKEN`, `ANTHROPIC_API_KEY`,
> `OPENAI_API_KEY`, and `GOOGLE_API_KEY` to be set via Railway
> dashboard → Variables tab on each environment (sourced from
> Google Password Manager entries `roadmodel <VAR_NAME>`).

| Variable                       | Value source                | Consumed by                       | Must be set in    |
| ------------------------------ | --------------------------- | --------------------------------- | ----------------- |
| `ANTHROPIC_API_KEY`            | Railway env vars            | FastAPI service (Step 3)          | staging + prod    |
| `OPENAI_API_KEY`               | Railway env vars            | FastAPI service (Step 3)          | staging + prod    |
| `GOOGLE_API_KEY`               | Railway env vars            | FastAPI service (Step 3)          | staging + prod    |
| `ROADMODEL_INTERNAL_TOKEN`     | Vercel env vars + Railway env vars | Next.js routes (Step 5 send), FastAPI middleware (Step 3 verify) | staging + prod    |
| `SUPABASE_URL`                 | Vercel env vars + Railway env vars | Next.js (Step 4) + FastAPI (Step 3) | staging + prod    |
| `SUPABASE_SERVICE_ROLE_KEY`    | Supabase dashboard → Railway env vars | FastAPI service only (never browser-exposed) | staging + prod    |
| `UPSTASH_REDIS_URL`            | Railway env vars            | FastAPI rate limiter (Step 6)     | staging + prod    |
| `UPSTASH_REDIS_TOKEN`          | Railway env vars            | FastAPI rate limiter (Step 6)     | staging + prod    |

Rules:

- The `SUPABASE_SERVICE_ROLE_KEY` is sensitive enough to bypass
  RLS; it lives ONLY in the Railway service env (and the Supabase
  dashboard itself). Never expose it to the Vercel web tier — the
  browser-facing public `anon` key handles client-side reads.
- The `ROADMODEL_INTERNAL_TOKEN` is a shared secret between the
  Next.js API routes and the FastAPI service so the FastAPI tier
  can reject calls that didn't transit Next.js. Rotate it on
  every Vercel ↔ Railway connectivity incident.
- `*_API_KEY` values are committed to Railway env vars and the
  local shell ONLY. They never appear in Vercel env vars — the
  browser must never see provider keys, per
  [private/ROADMAP.md](../private/ROADMAP.md) §3.
- Local development reads the same schema from a gitignored
  `.env` at the repo root; [infra/.env.example](.env.example) is
  the template.

## DNS records

The registrar of record for `roadmodel.ai` is the maintainer's
Namecheap account (confirmed by the maintainer during step 4 of
the [Provisioning sequence](#provisioning-sequence)).

| Host                      | Type   | Value                                       | TTL   | Notes                                                  |
| ------------------------- | ------ | ------------------------------------------- | ----- | ------------------------------------------------------ |
| `staging.roadmodel.ai`    | CNAME  | `6414f72d9e02a5d3.vercel-dns-016.com`       | Auto  | Cut 2026-05-17. Project-scoped Vercel target; `cname.vercel-dns.com` is the documented universal fallback per Vercel's IP-range migration banner. |
| `roadmodel.ai` (apex)     | ALIAS  | TBD (Vercel-issued apex target)             | 300   | **Not cut until Step 7** — public launch only. Namecheap currently has a parked-page `URL Redirect Record` for the apex → `http://www.roadmodel.ai/`; leave it until Step 7. |
| `www.roadmodel.ai`        | CNAME  | TBD (Vercel-issued `www` target)            | 300   | **Not cut until Step 7**.                              |

Step 2 cuts only the `staging` row. The apex + `www` rows stay
TBD until Step 7 — cutting them earlier would expose an
unfinished site to the open web.

## TLS posture

Vercel auto-issues Let's Encrypt certificates on every custom
domain it serves and auto-renews them ~30 days before expiry. No
manual intervention is required unless the auto-renew fails.

Failure modes the maintainer should watch for:

- **DNS misconfigured during issuance.** Vercel surfaces this in
  the project's `Domains` tab with a red badge; fix the registrar
  record and Vercel retries automatically within an hour.
- **CAA records blocking Let's Encrypt.** `roadmodel.ai` should
  have no CAA records at registrar level for Step 2; if added
  later (a Phase 7 hardening option), include `letsencrypt.org`
  explicitly.
- **Renewal failure.** Vercel emails the project owner; the
  manual fix is to re-issue from `Domains → Refresh certificate`.

For the Railway and Supabase tiers the same auto-issue posture
applies: Railway issues per-service certificates on its `*.up.railway.app`
domain and on any custom domain configured; Supabase fronts all
project URLs with its own managed TLS. No manual cert handling
is required at this stage.

## Provider cost ceilings

These are the day-one cost-ceiling floor the Phase 7 application
ledger strengthens but does NOT replace (see
[Disaster recovery](#disaster-recovery)). The cap values below
are the single source of truth — Step 6 mirrors them into
`docs/cost-ceilings.md` as the public-doc derivative; if a cap
changes here, Step 6's doc must be re-synced.

| Provider   | Monthly cap (USD) | Alert thresholds       | Console URL                                                                       |
| ---------- | ----------------- | ---------------------- | --------------------------------------------------------------------------------- |
| Anthropic  | $200              | 50% / 75% / 90% email ($100 / $150 / $180) | `https://platform.claude.com/settings/limits` (was `console.anthropic.com`; Anthropic rebranded the console late 2025) |
| OpenAI     | $200 (org budget; hard cap) | 50% / 75% / 90% email ($100 / $150 / $180) | `https://platform.openai.com/settings/organization/limits` (was `/account/limits`; OpenAI 2025 redesign collapsed the legacy soft/hard distinction into a single budget + percentage alerts — the 75% alert is the functional successor to the old "soft limit") |
| Google     | $50               | 50% / 75% / 90% email ($25 / $37.50 / $45) | `https://console.cloud.google.com/billing/010548-2423B0-E0B624/budgets` (project `roadmodel-saas`, budget `roadmodel Gemini API monthly`, scoped to Generative Language API service) |

Cap-sizing rationale (frozen here so Phase 7 doesn't relitigate):

- `private/ROADMAP.md` §5 sizes AI inference at $200-$800/mo at
  pilot scale assuming ≤100 paid users. Phase 3 has zero paid
  users and only an anonymous IP-rate-limited recommender — the
  Step 2 caps sit at the bottom of that range with a ~3x safety
  margin against the expected anonymous-traffic volume.
- The Anthropic + OpenAI caps are equal ($200 each) because the
  Phase 3 free-tier model could be served from either provider
  depending on the cheap-model availability at the time of each
  call (Haiku 4.5 vs Flash); the routing decision is finalized
  in Step 5.
- Google's cap is the smallest ($50) — but see
  [Model routing](#model-routing-phase-3) below; in Phase 3 the
  Gemini API is actually the **primary** free-tier provider, not
  the fallback. The $50 cap is sized small not because Gemini
  carries the least load, but because Gemini 2.5 Flash is so
  cheap per call that $50 covers ~500,000 recommend calls — well
  past any realistic pilot-scale traffic.
- All three alert ladders (50% / 75% / 90%) match by design so
  the maintainer sees a consistent breach signal across vendors.

### Model routing (Phase 3)

Frozen decision for the free-tier cheap-model selection. Phase 3
Step 5 (the FastAPI service) implements this; Step 5 should NOT
relitigate the choice unless one of the trigger conditions below
fires.

| Tier                 | Primary model       | Fallback (on cap or outage) | Why                                                  |
| -------------------- | ------------------- | --------------------------- | ---------------------------------------------------- |
| Anonymous web        | Gemini 2.5 Flash    | Claude Haiku 4.5            | Flash is ~15× cheaper per call than Haiku, US-based provider, comparable quality at this complexity tier. |
| Free signed-in (rec) | Gemini 2.5 Flash    | Claude Haiku 4.5            | Same call profile as anonymous.                      |
| Free signed-in (roadmap) | Claude Haiku 4.5 (long-form) | Gemini 2.5 Flash | Roadmap synthesis benefits from Claude's longer-context coherence; Flash falls back if cap fires. |

Rationale (frozen):

- **Cost.** Gemini 2.5 Flash at ~$0.0001/call vs Haiku 4.5 at
  ~$0.0015/call. The $50 Google cap covers ~500,000 calls/month;
  Anthropic's $200 cap covers ~133,000 calls/month of Haiku at
  the same call profile. Flash is the strictly cheaper primary.
- **Geopolitics + brand.** DeepSeek considered and rejected:
  cheaper than Haiku but more expensive than Flash, plus
  China-jurisdiction privacy exposure, US-China API-restriction
  risk, and brand mismatch with roadmodel's positioning (we
  recommend Claude/Cursor/Codex; running our own surface on a
  model we don't recommend undermines us). Not worth $15-30/mo
  expected savings vs Haiku for solo-maintainer ops tax of a 4th
  provider.
- **Fallback design.** When Gemini's $50 cap fires (or Gemini
  has an outage), traffic flips to Haiku on Anthropic. Anthropic's
  $200 cap easily absorbs this — at Haiku rates it covers another
  ~133K calls of overflow. OpenAI's $200 is the third-tier
  fallback if both Google and Anthropic are unavailable.

Trigger conditions to revisit this routing:

- Phase 5 monetization ships and paid-tier revenue funds AI cost
  — at that point, default frontier (Sonnet 4.6) takes over for
  paid surfaces and this cheap-tier discussion becomes academic
  for paying users.
- Google deprecates Flash or raises Flash pricing by >5×.
- Anthropic drops Haiku pricing below Flash.
- A non-trivial cohort of users complains about Flash quality
  for recommend-tier prompts.

## UptimeRobot monitors

Free-tier UptimeRobot account; one monitor in Step 2, more added
in Step 7 when the production URL is cut.

| Monitor ID                                                                     | Target URL                          | Interval   | Alert channel                |
| ------------------------------------------------------------------------------ | ----------------------------------- | ---------- | ---------------------------- |
| `803092893` (paused 2026-05-17; resume in Phase 3 Step 4 when staging returns 2xx) | `https://staging.roadmodel.ai`      | 5 minutes  | maintainer's email on file   |

UptimeRobot's free tier allows 50 monitors at a 5-minute floor.
That's the right granularity for Step 2 — finer-grained polling
adds no signal at this stage and burns the free-tier quota faster
than necessary.

**Note on the paused state.** UptimeRobot's free tier treats HTTP
4xx as Down (the "Up HTTP status codes" override that would let
404 count as Up is gated behind the Solo plan, $7/mo). Until
Phase 3 Step 4 lands the Next.js scaffold and staging starts
responding 2xx, the monitor would page-spam the maintainer on
every 5-minute probe. The monitor is therefore **paused** at the
end of Step 2 — provisioned, configured correctly, but not
actively probing. Resume it from the UptimeRobot dashboard the
moment the Phase 3 Step 4 staging deploy goes green; V2.5
acceptance ("monitor reports `up`") gates on that resumption,
not on Step 2 alone.

## Provisioning sequence

The seven-step recipe a future maintainer follows to re-provision
this stack from scratch. Each step blocks on the verifying check
named in it; do not move to step N+1 until step N's check passes.

1. **Vercel.** Create the `roadmodel-web` project under the
   maintainer's Vercel team. Add `staging` and `production`
   environments under it (Settings → Environments → Add). Connect
   the GitHub repo (Settings → Git → Connect GitHub) with Preview
   Deployments enabled. Record the project ID and team ID into
   the [Cloud projects](#cloud-projects) table.

2. **Railway.** Create the `roadmodel-service` project under the
   maintainer's Railway workspace on the **Hobby plan** ($5/mo —
   the Trial credit auto-suspends after 30 days otherwise). When
   you import `nathanramoscfa/roadmodel` as the project source,
   Railway auto-creates one service inside a default `production`
   environment. Railway models staging/production as **two
   environments around a single service**, NOT as two separate
   services — confirmed against Railway's UX 2026-05. Add the
   second environment: top breadcrumb → environment dropdown →
   **+ New Environment** → name `staging`, copy from
   `production` so the service config carries over. Inside the
   new `staging` environment, switch the service's source branch
   from `main` to `staging`. The `staging` branch must exist on
   origin first — if it doesn't, run `git push origin
   main:refs/heads/staging` from a local clone (no commits to
   `main` required; this just creates a remote pointer at main's
   tip). Optionally enable "PR Deploys" (Railway moves this
   toggle around — not blocking; revisit in Phase 3 Step 4 if
   not exposed). Record the project ID, service ID, and **both**
   environment IDs into the [Cloud projects](#cloud-projects)
   table.

3. **Supabase.** Create the `roadmodel-data` project on the
   **Pro** plan — not Free; Free's row caps and lack of daily
   backups are disqualifying for the Phase 4 audit log. Record
   the project URL and the dashboard path to the service-role
   key (Settings → API → service_role) into the
   [Cloud projects](#cloud-projects) table. **Do NOT commit the
   service-role key value itself anywhere** — it lives only in
   Railway env vars and the Supabase dashboard.

4. **DNS.** At the registrar (Namecheap), add a CNAME record
   for `staging.roadmodel.ai` pointing at Vercel's
   `cname.vercel-dns.com` target. Do not touch the apex or `www`
   rows — those wait for Step 7. Verify with:

   ```bash
   dig CNAME staging.roadmodel.ai +short
   ```

   Expected: a line containing `vercel-dns.com.` Block on this
   before moving to step 5.

5. **TLS.** Wait up to 5 minutes for Vercel to auto-issue a
   Let's Encrypt certificate against the new CNAME. Verify with:

   ```bash
   curl -sSI https://staging.roadmodel.ai | head -1
   ```

   Expected: `HTTP/2 200` or `HTTP/2 404` — either response
   means the TLS handshake completed. A connection error
   (`SSL_ERROR`, `Could not resolve host`) means re-check step 4.

6. **UptimeRobot.** In the maintainer's UptimeRobot dashboard,
   create a free-tier HTTP(s) monitor against
   `https://staging.roadmodel.ai` at the 5-minute interval. Set
   the maintainer's email as the notification channel. Record
   the monitor ID into the
   [UptimeRobot monitors](#uptimerobot-monitors) table.

7. **Provider caps.** In each provider console, configure the
   cap and alert thresholds documented in
   [Provider cost ceilings](#provider-cost-ceilings):

   - **Anthropic.** `console.anthropic.com` → Settings → Limits
     → set monthly spend cap $200 with email alerts at 50%,
     75%, 90%.
   - **OpenAI.** `platform.openai.com` → Billing → Usage
     limits → set hard limit $200, soft limit $150, alerts at
     50%, 75%, 90%.
   - **Google.** Create a new GCP project (`roadmodel-saas`),
     link the existing billing account, enable the
     **Generative Language API** (Gemini). For the API key,
     **use Google AI Studio (https://aistudio.google.com), NOT
     Cloud Console → Credentials.** AI Studio creates a plain
     API key (no service account binding required) and lets you
     pick `roadmodel-saas` as the billing project so usage hits
     the GCP budget. The Cloud Console "Create credentials → API
     key" flow now (2025+ policy) demands service-account binding
     and a Vertex-scoped role, which is overkill for a simple
     `x-goog-api-key`-header use case and surfaces a chain of
     IAM/role obstacles. Then `console.cloud.google.com` →
     Billing → Budgets & alerts → create a $50/mo budget scoped
     to the `roadmodel-saas` project + filtered to the
     Generative Language API service, alerts at 50%, 75%, 90%.
     Google budgets are **email-only**, not hard cutoffs —
     Phase 7 application ledger adds the hard stop layer.

   Record the Google billing-account-specific console URL into
   the [Provider cost ceilings](#provider-cost-ceilings) table
   (it's the only one that varies per billing account).

After step 7, the maintainer runs `scripts/verify-infra.sh`
locally; expected output is `PASS` on every check.

## Disaster recovery

The provider-side cost ceilings configured above are the
**disaster-recovery floor** for AI-inference spend. Phase 7
adds an application-side ledger that tracks token spend in real
time per provider and refuses calls before they breach a daily
ceiling (see [private/ROADMAP.md](../private/ROADMAP.md) §4
Phase 7.1). That ledger **strengthens but does not replace**
this floor — if the application ledger ever fails open (a bug, a
bad deploy, a stale cache), the provider-side caps still hold
and the bill cannot exceed $450/mo across the three providers
under Step 2's settings.

Recovery steps the maintainer follows when a cap fires:

1. The provider emails the maintainer at the configured
   threshold (50% / 75% / 90%).
2. The maintainer triages: is the spend organic (legitimate
   traffic growth — raise the cap deliberately) or anomalous
   (abuse, leaked key, runaway loop — kill the offending
   surface)?
3. For anomalous spend, the maintainer revokes the affected
   provider API key in the provider console, rotates a fresh
   key into Railway env vars, redeploys the FastAPI service,
   and files an incident note under
   `private/incidents/<UTC-date>-<provider>.md` for the
   post-mortem trail.
4. For organic spend, the maintainer raises the cap **only
   after** updating the cap value in
   [Provider cost ceilings](#provider-cost-ceilings) AND
   re-running `update/sync_public_roadmap.py --check` to
   confirm the public derivative still lints clean. The cap
   value is the source of truth here; the public doc trails.

The Phase 7 ledger never assumes the provider caps will hold —
it is a defense-in-depth layer, not a replacement. Equally, the
provider caps don't assume the application ledger will hold —
they are the deterministic floor regardless of application
state.
