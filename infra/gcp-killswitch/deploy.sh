#!/usr/bin/env bash
# infra/gcp-killswitch/deploy.sh
#
# Provisions the Gemini budget kill-switch (audit follow-up). Idempotent-ish:
# safe to re-run; existing resources are skipped or updated. Deploys in DRY_RUN
# mode — it will NOT disable anything until you explicitly arm it (see ARM step
# printed at the end). Run from the repo root with an authenticated gcloud
# (`gcloud auth login`).
#
#   bash infra/gcp-killswitch/deploy.sh
#
# Blast radius once ARMED: when month-to-date spend on the scoped budget hits
# the budget amount, the Generative Language (Gemini) API is DISABLED on
# $PROJECT. Reverse with:
#   gcloud services enable generativelanguage.googleapis.com --project=$PROJECT

set -euo pipefail

PROJECT="roadmodel-saas"
PROJECT_NUMBER="175144441645"
BILLING_ACCOUNT="010548-2423B0-E0B624"
REGION="us-central1"
TOPIC="roadmodel-budget-killswitch"
FUNCTION="roadmodel-gemini-killswitch"
SA="rm-killswitch"
SA_EMAIL="${SA}@${PROJECT}.iam.gserviceaccount.com"
BUDGET_NAME="roadmodel-saas Gemini killswitch"
BUDGET_AMOUNT="50"   # USD; should match (or sit just above) your alert budget
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Enabling required APIs on ${PROJECT}"
gcloud services enable \
  cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  eventarc.googleapis.com pubsub.googleapis.com serviceusage.googleapis.com \
  billingbudgets.googleapis.com \
  --project="${PROJECT}"

echo "==> Pub/Sub topic ${TOPIC}"
gcloud pubsub topics create "${TOPIC}" --project="${PROJECT}" 2>/dev/null \
  || echo "    topic exists"

echo "==> Service account ${SA_EMAIL} (least privilege: serviceusage admin only)"
gcloud iam service-accounts create "${SA}" --project="${PROJECT}" \
  --display-name="roadmodel Gemini kill-switch" 2>/dev/null || echo "    SA exists"
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/serviceusage.serviceUsageAdmin" --condition=None >/dev/null
echo "    granted roles/serviceusage.serviceUsageAdmin"

echo "==> Let the Cloud Billing budgets service agent publish to the topic"
# The budget notification is published by Google's billing-budgets service
# agent; it needs pubsub.publisher on the topic.
BUDGETS_SA="cloud-billing-budget-notification@system.gserviceaccount.com"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" --project="${PROJECT}" \
  --member="serviceAccount:${BUDGETS_SA}" \
  --role="roles/pubsub.publisher" >/dev/null 2>&1 \
  || echo "    NOTE: could not grant publisher to ${BUDGETS_SA} — verify in console (Pub/Sub > topic > permissions)"

echo "==> Deploying Cloud Function ${FUNCTION} (DRY_RUN=true — inert)"
gcloud functions deploy "${FUNCTION}" \
  --gen2 --project="${PROJECT}" --region="${REGION}" \
  --runtime=python312 --source="${SOURCE_DIR}" --entry-point=handle_budget \
  --trigger-topic="${TOPIC}" \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="TARGET_PROJECT=${PROJECT},TARGET_SERVICE=generativelanguage.googleapis.com,DRY_RUN=true"

echo "==> Project-scoped budget wired to the topic"
# Scoped to roadmodel-saas ONLY (not account-wide), so other projects' spend
# can't trip the Gemini kill-switch. 100% threshold drives the Pub/Sub notify.
if ! gcloud billing budgets list --billing-account="${BILLING_ACCOUNT}" \
     --format="value(displayName)" 2>/dev/null | grep -qF "${BUDGET_NAME}"; then
  gcloud billing budgets create --billing-account="${BILLING_ACCOUNT}" \
    --display-name="${BUDGET_NAME}" \
    --budget-amount="${BUDGET_AMOUNT}USD" \
    --filter-projects="projects/${PROJECT_NUMBER}" \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 \
    --all-updates-rule-pubsub-topic="projects/${PROJECT}/topics/${TOPIC}"
else
  echo "    budget '${BUDGET_NAME}' exists — skipping create"
fi

cat <<EOF

==> DONE (deployed in DRY_RUN mode — nothing will be disabled yet).

TEST (publish a fake over-budget event; with DRY_RUN it only logs):
  gcloud pubsub topics publish ${TOPIC} --project=${PROJECT} \\
    --message='{"costAmount":999,"budgetAmount":50,"budgetDisplayName":"test"}'
  gcloud functions logs read ${FUNCTION} --gen2 --region=${REGION} --project=${PROJECT} --limit=20

ARM (flip to live — after you've seen a clean DRY_RUN log):
  gcloud functions deploy ${FUNCTION} --gen2 --project=${PROJECT} --region=${REGION} \\
    --runtime=python312 --source=${SOURCE_DIR} --entry-point=handle_budget \\
    --trigger-topic=${TOPIC} --service-account=${SA_EMAIL} \\
    --set-env-vars=TARGET_PROJECT=${PROJECT},TARGET_SERVICE=generativelanguage.googleapis.com,DRY_RUN=false

REVERSE (if it ever fires and you want Gemini back):
  gcloud services enable generativelanguage.googleapis.com --project=${PROJECT}
EOF
