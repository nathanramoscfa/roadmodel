# GCP Gemini budget kill-switch

Last-resort circuit breaker on Gemini (Generative Language API) spend for the
`roadmodel-saas` GCP project. A Cloud Billing **budget** publishes to a
**Pub/Sub** topic; a 2nd-gen **Cloud Function** (`main.py`) reacts and, when
month-to-date spend reaches the budget, **disables the Generative Language API**
on the project.

## Design choices

- **Disables one API, not billing.** Disabling project billing is the GCP
  nuclear option — it kills every service in the project and can't auto-recover.
  This disables only `generativelanguage.googleapis.com`, the exact spend
  source, and re-enabling is a single command.
- **Project-scoped trigger.** The budget filters to `roadmodel-saas` only, so
  spend in your other ~20 billing-account projects can't trip it.
- **Default-safe.** Deploys with `DRY_RUN=true` — it logs what it *would* do and
  disables nothing until you explicitly arm it.

## ⚠️ This is a DELAYED backstop, not a real-time cap

GCP billing data updates only a few times per day, so a budget notification can
lag real overspend by **hours**. The real-time spend controls already in place
are the line of defense:

- per-call `max_output_tokens` caps (bounds each Gemini call's cost),
- the app rate limiter (3/day + 10/min per IP+UA) and the per-user roadmap cap,
- the Vercel WAF rate-limit rules on `/api/*` and the bearer gate on the service.

This kill-switch catches a sustained leak that somehow survives all of the
above. For a *real-time* per-account spend cap, see "App-side complement" below.

## Deploy

```bash
gcloud auth login              # if not already authed
bash infra/gcp-killswitch/deploy.sh
```

Creates: the Pub/Sub topic, a least-privilege service account (Service Usage
Admin only), the Cloud Function (DRY_RUN), and a project-scoped budget wired to
the topic. The script prints TEST / ARM / REVERSE commands at the end.

## Test (safe — DRY_RUN logs only)

```bash
gcloud pubsub topics publish roadmodel-budget-killswitch --project=roadmodel-saas \
  --message='{"costAmount":999,"budgetAmount":50,"budgetDisplayName":"test"}'
gcloud functions logs read roadmodel-gemini-killswitch --gen2 \
  --region=us-central1 --project=roadmodel-saas --limit=20
```

Expect a `DRY_RUN — WOULD disable …` line. Nothing is disabled.

## Arm / reverse

- **Arm:** re-deploy with `DRY_RUN=false` (exact command printed by `deploy.sh`).
- **Reverse** (after it fires): `gcloud services enable generativelanguage.googleapis.com --project=roadmodel-saas`

## App-side complement (real-time)

The faster, in-app version of this is a spend circuit breaker that sums recent
`audit_log.cost_usd` and refuses new `/api/recommend` calls past a daily
threshold (env-tunable). That's the "enforcing per-account ledger" the cost
docs defer to Phase 7 — it reacts in seconds, not hours. Build it if you want a
real-time cap; this GCP function remains the independent provider-side backstop.
