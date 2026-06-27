"""GCP budget kill-switch (audit follow-up).

A 2nd-gen Cloud Function, triggered by a Cloud Billing budget's Pub/Sub
notification. When the month-to-date cost for the scoped budget reaches the
budget amount, it DISABLES the Generative Language (Gemini) API on the target
project — a surgical, one-command-reversible hard stop on Gemini spend.

It deliberately does NOT disable project billing (the GCP "nuclear" option that
kills every service in the project and can't easily auto-recover). It only
disables one API.

IMPORTANT — this is a DELAYED backstop. GCP billing data updates only a few
times per day, so a budget notification can lag real overspend by hours. The
REAL-TIME spend controls are the app-side per-call token caps + the rate
limiters (app + Vercel WAF). This function is the last-resort circuit breaker.

Env vars:
  TARGET_PROJECT  project whose API to disable (default: roadmodel-saas)
  TARGET_SERVICE  service to disable (default: generativelanguage.googleapis.com)
  DRY_RUN         "true" (default) → only log what it WOULD do; "false" → act
"""

from __future__ import annotations

import base64
import json
import os

import functions_framework
from googleapiclient import discovery

TARGET_PROJECT = os.environ.get("TARGET_PROJECT", "roadmodel-saas")
TARGET_SERVICE = os.environ.get("TARGET_SERVICE", "generativelanguage.googleapis.com")
# Default-SAFE: the function refuses to actually disable anything unless
# DRY_RUN is explicitly set to "false"/"0" (the "arm" step).
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() not in ("false", "0")


def _disable_service() -> None:
    su = discovery.build("serviceusage", "v1", cache_discovery=False)
    name = f"projects/{TARGET_PROJECT}/services/{TARGET_SERVICE}"
    print(f"[killswitch] DISABLING {name}")
    op = (
        su.services()
        .disable(name=name, body={"disableDependentServices": False})
        .execute()
    )
    print(f"[killswitch] disable submitted: {op.get('name', 'ok')}")


@functions_framework.cloud_event
def handle_budget(cloud_event) -> None:
    message = (cloud_event.data or {}).get("message", {})
    encoded = message.get("data", "")
    raw = base64.b64decode(encoded).decode("utf-8") if encoded else "{}"
    budget = json.loads(raw)

    # Cloud Billing budget notification schema.
    cost = float(budget.get("costAmount") or 0)
    limit = float(budget.get("budgetAmount") or 0)
    display = budget.get("budgetDisplayName", "?")
    print(
        f"[killswitch] budget={display!r} cost={cost} limit={limit} "
        f"target={TARGET_SERVICE}@{TARGET_PROJECT} dry_run={DRY_RUN}"
    )

    if limit <= 0 or cost < limit:
        print("[killswitch] under budget — no action")
        return

    if DRY_RUN:
        print(
            f"[killswitch] DRY_RUN — WOULD disable {TARGET_SERVICE} on "
            f"{TARGET_PROJECT}. Set DRY_RUN=false to arm."
        )
        return

    _disable_service()
