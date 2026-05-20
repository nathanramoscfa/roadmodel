<!-- docs/cost-ceilings.md -->
# AI provider cost ceilings

This is the public-facing summary of the day-one provider-side
spend ceilings roadmodel runs under during Phase 3. It is a
derivative of the internal "Provider cost ceilings" table in the
maintainer's infrastructure runbook — that table is the single
source of truth; if numbers on this page disagree with the
runbook, the runbook wins.

The caps documented here are the **disaster-recovery floor** for
AI-inference spend. Phase 7 will add an application-side ledger
that strengthens but does not replace these caps (see
["Forward reference — Phase 7 application ledger"](#forward-reference--phase-7-application-ledger)
below).

## Day-one provider caps

Three providers carry the free-tier recommender's traffic during
Phase 3. Each carries an independent monthly spend cap plus a
50% / 75% / 90% email alert ladder so the maintainer sees a
breach trajectory days before the cap actually fires.

| Provider  | Monthly cap (USD) | Alert thresholds (50% / 75% / 90%) | Console URL                                                                  |
| --------- | ----------------- | ---------------------------------- | ---------------------------------------------------------------------------- |
| Anthropic | $200              | $100 / $150 / $180                 | <https://platform.claude.com/settings/limits>                                |
| OpenAI    | $200              | $100 / $150 / $180                 | <https://platform.openai.com/settings/organization/limits>                   |
| Google    | $50               | $25 / $37.50 / $45                 | <https://console.cloud.google.com/billing> (project `roadmodel-saas`)        |

The Google budget is scoped to the Generative Language API
service so non-AI GCP usage on the same billing account does not
count toward the cap.

The aggregate ceiling under Phase 3 settings is $450/mo across
the three providers. A coordinated bot attack cannot drive spend
past that floor without the maintainer first taking deliberate
action to raise a cap. Phase 7's application ledger pushes the
realistic ceiling well below this number for non-incident
operation.

## Cap-breach response runbook

When a provider sends a threshold alert (50% / 75% / 90%) or the
cap fires outright, the maintainer follows these steps in order.
The 50% and 75% alerts are early-warning signals — investigate
but do not necessarily rotate. The 90% alert and a hard cap-fire
are the action-required signals.

1. **Confirm the breach via the provider console.** Open the
   console URL for the affected provider from the table above
   and confirm the live spend matches the alert. False
   positives are rare but possible; rotating keys against a
   stale alert burns time and adds churn.
2. **Rotate the compromised API key.** In the provider's console,
   revoke the existing key and create a fresh one. Save the new
   value to Google Password Manager under the entry
   `roadmodel <PROVIDER>_API_KEY` (e.g., `roadmodel ANTHROPIC_API_KEY`).
3. **Update the Vercel env var.** From a clone of the repo with
   the new key on the clipboard:
   ```bash
   cd service && pbpaste | tr -d '\r\n' \
     | vercel env add ANTHROPIC_API_KEY production --force --yes
   ```
   Repeat for the `preview` scope. The FastAPI service redeploys
   automatically on env var change; allow ~30 seconds for the
   new deployment to become live. (Until Step 5.5b the Railway
   tier needed a parallel update; Railway has since been retired
   so only Vercel env vars matter.)
4. **Verify the new key works via the health-check endpoint.**
   Issue a curl against the recommender:
   ```bash
   curl -sS https://staging.roadmodel.ai/api/recommend \
     -H 'Content-Type: application/json' \
     -d '{"task_description":"smoke test post-rotation","context":{"budget_priority":"cheap"}}'
   ```
   Expected: HTTP 200 with a JSON `model` + `platform` payload.
   A 5xx response indicates the new key did not propagate — wait
   30 seconds and retry; if still failing, re-check the env var
   value in the Vercel dashboard.
5. **Post-mortem.** Capture the incident in
   `private/incidents/<UTC-date>-<provider>.md` (template lives
   in `docs/phase03-qa-findings.md` once the Step 8 close-out
   doc lands). Cover: alert trigger time, traffic shape that
   caused the breach, rotated key fingerprint, total spend at
   rotation, and whether the cap value itself should change.

If the spend is **organic** — legitimate traffic growth rather
than abuse — the rotation step is unnecessary. Instead, raise the
cap deliberately in the provider console, update the
"Provider cost ceilings" table in the internal infrastructure
runbook, and re-sync this public derivative.

## Forward reference — Phase 7 application ledger

The caps documented above are intentionally crude: they
deterministically prevent the bill from running unbounded, but
they cannot prevent a single bad actor from spending the cap
amount on garbage requests in a few hours. Phase 7 of the
roadmap adds an **application-side hard ledger** that tracks
token spend per-request and per-account in real time and can
refuse a call before it ever reaches the provider. That ledger
strengthens this floor in three ways:

- **Per-account caps.** Heavy users hit a dollar/token ceiling
  long before they could move the per-provider cap.
- **Anomaly cutoff.** A burst of expensive requests trips a
  60-second kill-switch at the application tier; the
  provider-side cap is the slow-burn backstop, not the first
  line of defense.
- **Real-time visibility.** The ledger surfaces live spend at a
  per-route + per-provider grain; the provider consoles report
  hours behind real time.

Until that ledger ships, the provider caps documented here are
roadmodel's only hard limit on AI-inference cost. Phase 7's
landing **strengthens but does not replace** them — if the
ledger ever fails open (a bug, a stale cache, a misconfigured
deploy), the provider caps still hold and the bill still cannot
exceed the documented monthly floor.
