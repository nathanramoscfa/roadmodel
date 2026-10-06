<!-- docs/cost-ceilings.md -->
# AI cost ceilings

This is the public-facing summary of what roadmodel.ai can spend on AI
inference, who pays for each kind of request, and the layers that hold the
bill down. It is a derivative of the internal "Provider cost ceilings" table in
the maintainer's infrastructure runbook — that table is the single source of
truth for the provider-side numbers; if the numbers here disagree with the
runbook, the runbook wins.

Three layers, innermost first:

1. **The funding lanes** decide who pays before any provider is called, and a
   request nobody funds is refused with `402`.
2. **The daily operator cap** ($2 a day) stops the operator's own spend in
   real time.
3. **The provider caps** are the disaster-recovery floor: independent monthly
   limits in each provider's console that hold even if the application layers
   fail.

## The three lanes

Every request to a paid route (`POST /api/recommend`, `POST /api/roadmap`) is
assigned to exactly one lane by `web/lib/funding-lane.ts`. The decision fails
closed: any error in it refuses the request.

| Lane | Who pays | Who gets it | Limits (per IP + user agent unless noted) |
| ---- | -------- | ----------- | ----------------------------------------- |
| **Operator** | roadmodel's own provider keys | The founder, the invite list, and the latency-sweep bypass header | Founder and bypass: none. Invited: 20 a day per account, plus a 10-a-minute burst. The $2/day cap applies to all three. |
| **Visitor** | The visitor's own key (OpenAI, Google, Anthropic or an OpenRouter connection), for that one request | Anyone who sends a key | 10 a minute and 50 a day, plus 5 declined keys a day. Never checks or moves the operator cap. |
| **Keyless** | Nobody: the picks are computed in code from the bundled catalog (`POST /v1/score`), with no model call | Anyone, signed in or not | 20 a minute and 200 a day. Never checks or moves the operator cap. |

A request that fits none of them is answered `402 funding_required` with the
ways forward, before any upstream call is made. The key a visitor sends travels
as one request header, is used for that request, and is not stored, logged or
copied into the audit row.

Each `audit_log` row records the lane in `funded_by` (`operator`, `visitor` or
`keyless`; empty on a refused request). Only `operator` rows count toward the
cap.

## The daily operator cap

`ROADMODEL_DAILY_COST_CAP_USD` is **$2**. The running total for the UTC day
lives in a counter (`spend:<UTC day>`) that every operator-funded call adds its
metered cost to, so the check is one read at any volume. When a day's counter
is missing it is seeded from the operator rows in `audit_log`, page by page.
Once the total reaches the cap, the operator lane answers `503 daily_cost_cap`
with a `Retry-After` until UTC midnight — the founder and the bypass header
included. The visitor and keyless lanes keep working, because they cost the
operator nothing.

The guard fails open on purpose: with no cap set, or when every read errors, it
never trips. A metering hiccup must not take the app down; the provider caps
below are the backstop for that case.

### The arithmetic

The default engine is GPT-6 Luna at $0.10 per million input tokens and $0.50
per million output tokens. A ladder call reads about 61,000 input tokens and
may write up to 6,144.

| Quantity | Figure |
| -------- | ------ |
| Measured cost of one call (92% of the input served from cache) | about $0.0015 |
| Worst case for one call (every input token uncached, output at its cap): 60,925 × $0.10/M + 6,144 × $0.50/M | **$0.0092** |
| One worst-case recommendation (a failed ladder plus a three-call fan-out, four calls) | about $0.037 |
| Worst-case recommendations the cap allows in a day ($2 ÷ $0.037) | about 54 |
| Expected operator volume (the invite list plus the daily soak run) at the measured cost | about $0.25 a day |
| **Worst month**: $2 × 30 days | **$60** |

The cap, not the expected volume, sets the ceiling: even if every operator call
were a worst-case call, a month cannot pass $60 of operator spend through this
layer.

## The provider caps

The operator's provider keys also carry independent monthly spend caps plus a
50% / 75% / 90% email alert ladder, so the maintainer sees a breach trajectory
days before a cap fires. They are the backstop for everything the application
layers cannot see: a leaked key, a bug in the guard, a fail-open read.

| Provider  | Monthly cap (USD) | Alert thresholds (50% / 75% / 90%) | Console URL                                                                  |
| --------- | ----------------- | ---------------------------------- | ---------------------------------------------------------------------------- |
| Anthropic | $200              | $100 / $150 / $180                 | <https://platform.claude.com/settings/limits>                                |
| OpenAI    | $200              | $100 / $150 / $180                 | <https://platform.openai.com/settings/organization/limits>                   |
| Google    | $50               | $25 / $37.50 / $45                 | <https://console.cloud.google.com/billing> (project `roadmodel-saas`)        |

The Google budget is scoped to the Generative Language API service so non-AI
GCP usage on the same billing account does not count toward the cap.

The aggregate provider-side ceiling is $450 a month across the three. A
coordinated attack cannot drive operator spend past it without the maintainer
first taking deliberate action to raise a cap.

## The funding-invariant alarm

A daily check (`scripts/check_funding_invariant.py`, run by the
`cron-health.yml` workflow) reads the last 25 hours of `audit_log` and fails
when an operator-funded row that spent money breaks either rule:

- its `cache_stats.funding_reason` is anything but `founder`, `invited` or
  `bypass`;
- it has no `user_id` and a reason other than `bypass` (the founder and invite
  lanes are signed-in lanes).

A failure opens, or adds to, the single `cron-health` tracking issue, and the
issue closes itself when the next daily run is clean. The check prints counts
and row ids only.

## Cap-breach response runbook

When a provider sends a threshold alert (50% / 75% / 90%), the cap fires
outright, or the daily operator cap trips unexpectedly, the maintainer follows
these steps in order. The 50% and 75% alerts are early-warning signals —
investigate but do not necessarily rotate. The 90% alert, a hard cap-fire and
an unexplained `daily_cost_cap` are the action-required signals.

1. **Confirm the breach.** For a provider alert, open the console URL from the
   table above and confirm the live spend matches. For the daily cap, read the
   day's operator rows in `audit_log` (`funded_by = 'operator'`) and check
   their `funding_reason`. False positives are rare but possible; rotating keys
   against a stale alert burns time and adds churn.
2. **Rotate the compromised API key.** In the provider's console, revoke the
   existing key and create a fresh one. Save the new value to Google Password
   Manager under the entry `roadmodel <PROVIDER>_API_KEY` (e.g.,
   `roadmodel OPENAI_API_KEY`).
3. **Update the Vercel env var.** From a clone of the repo with the new key on
   the clipboard:

   ```bash
   cd service && pbpaste | tr -d '\r\n' \
     | vercel env add OPENAI_API_KEY production --force --yes
   ```

   Repeat for the `preview` scope. The service redeploys automatically on an
   env var change; allow about 30 seconds for the new deployment to go live.
4. **Verify the new key works.** From the maintainer's Mac, run the live lane
   probe, which makes one founder call on the operator lane and checks that it
   is the only call that moved the spend counter:

   ```bash
   NODE_PATH="$(pwd)/web/node_modules" scripts/with-prod-secrets.sh \
     node web/node_modules/.bin/tsx scripts/probe-funding-lanes.ts
   ```

   Expected: every line `PASS`. A founder call that fails means the new key
   did not propagate — wait 30 seconds and retry, then re-check the env var in
   the Vercel dashboard.
5. **Post-mortem.** Capture the incident in
   `private/incidents/<UTC-date>-<provider>.md`. Cover: alert trigger time,
   traffic shape that caused the breach, rotated key fingerprint, total spend
   at rotation, and whether a cap value itself should change.

If the spend is **organic** — legitimate traffic growth rather than abuse — the
rotation step is unnecessary. Instead, raise the cap deliberately (the daily
cap through `ROADMODEL_DAILY_COST_CAP_USD`, a provider cap in its console),
update the "Provider cost ceilings" table in the internal infrastructure
runbook, and re-sync this public derivative.

## What this page does not cover

Stored, encrypted bring-your-own keys, paid tiers, and per-account dollar caps
arrive in later phases. A paid subscription will become one more way into the
operator lane above, under the same $2/day layer and provider caps. Until then,
a visitor's spend is capped by their own provider account, not by roadmodel.
