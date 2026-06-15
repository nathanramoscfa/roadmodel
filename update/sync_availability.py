"""Reconcile infra/model-availability.json into the Supabase model_availability table.

Phase 4.9 B3. The JSON is the human-auditable source of truth (edited by the
availability probe's auto-PR, or by hand); this script makes the table MATCH it on
merge to main, so the web recommend path reads an up-to-date unavailable-list:

  - every id in ``unavailable``      -> upsert available=false (with reason/source)
  - every table row NOT in the list  -> DELETE (the model is re-enabled)

Idempotent. Needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in the environment.
``--dry-run`` prints the plan without writing (and without needing creds for the
diff, though it still reads the table when creds are present).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AVAILABILITY_JSON = REPO_ROOT / "infra" / "model-availability.json"
TABLE = "model_availability"


def load_unavailable(path: Path) -> dict[str, dict[str, str]]:
    """Return ``{model_id: {"reason", "source"}}`` from the source-of-truth JSON.

    Entries without a non-empty string id are skipped; this is the same defensive
    posture as the service-side reader (a garbled entry never benches nothing).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    entries = data.get("unavailable", []) if isinstance(data, dict) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id", "")).strip()
        if not model_id:
            continue
        out[model_id] = {
            "reason": str(entry.get("reason", "")).strip(),
            "source": str(entry.get("source", "manual")).strip() or "manual",
        }
    return out


def plan(desired: dict[str, dict[str, str]], current: set[str]) -> tuple[list[str], list[str]]:
    """Diff desired (JSON) vs current (table) into (to_upsert, to_delete) id lists."""
    to_upsert = sorted(desired)
    to_delete = sorted(current - set(desired))
    return to_upsert, to_delete


def _request(method: str, url: str, token: str, body: Any | None = None) -> bytes:
    headers = {
        "apikey": token,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return bytes(resp.read())


def fetch_current_ids(base: str, token: str) -> set[str]:
    raw = _request("GET", f"{base}/rest/v1/{TABLE}?select=model_id", token)
    rows = json.loads(raw or b"[]")
    return {str(r["model_id"]) for r in rows if isinstance(r, dict) and r.get("model_id")}


def sync(path: Path, base: str, token: str, *, dry_run: bool) -> int:
    desired = load_unavailable(path)
    current = fetch_current_ids(base, token) if (base and token) else set()
    to_upsert, to_delete = plan(desired, current)

    print(f"source-of-truth unavailable: {to_upsert or '(none)'}")
    print(f"table currently holds:       {sorted(current) or '(none)'}")
    print(f"-> upsert (available=false): {to_upsert or '(none)'}")
    print(f"-> delete (re-enable):       {to_delete or '(none)'}")
    if dry_run:
        print("DRY RUN — no writes.")
        return 0

    if to_upsert:
        rows = [
            {
                "model_id": model_id,
                "available": False,
                "reason": desired[model_id]["reason"],
                "source": desired[model_id]["source"],
            }
            for model_id in to_upsert
        ]
        _request("POST", f"{base}/rest/v1/{TABLE}", token, rows)
        print(f"upserted {len(rows)} row(s).")
    for model_id in to_delete:
        _request("DELETE", f"{base}/rest/v1/{TABLE}?model_id=eq.{model_id}", token)
    if to_delete:
        print(f"deleted {len(to_delete)} row(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync model-availability.json -> Supabase.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; do not write.")
    parser.add_argument("--json", type=Path, default=AVAILABILITY_JSON)
    args = parser.parse_args(argv)

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    token = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not args.dry_run and (not base or not token):
        print(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required (or use --dry-run).",
            file=sys.stderr,
        )
        return 2
    return sync(args.json, base, token, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
