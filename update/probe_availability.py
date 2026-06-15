"""Daily Anthropic availability probe (Phase 4.9 B4).

Invokes each Anthropic model in roadmodel's catalog with a 1-token request and
classifies whether it is still callable. A model the API reports as
**not-found** is added to ``infra/model-availability.json`` (so the recommender
stops picking it WITHOUT a package release); a benched model that becomes callable
again is removed (self-healing). The daily cron runs this and, when the JSON
changes, opens an auto-PR for a human glance before it auto-merges + syncs to the
table that the web recommend path reads.

Why invocation, not the model list: when Anthropic suspended Fable 5 (2026-06-12)
the public model LIST still showed it — only an actual call was definitive.

FAIL-SAFE: only an explicit not-found classifies a model unavailable. Auth /
rate-limit / 5xx / network errors classify as **ambiguous** and never bench a
model, so a transient blip can't take a model offline. The auto-PR's human glance
is the second backstop.

Scope (v1): Anthropic only (its key is already a cron secret). The WATCH map below
is the explicit roadmodel-id -> Anthropic-API-id list; a new Anthropic catalog
model must be added here (a test asserts every WATCH id is a real catalog id).
The probe runs from a US-based key, so an export-control suspension that is merely
foreign-national-gated could read as available here — which is why Fable 5 also
stays baked in <availability-context> as a belt-and-suspenders default.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AVAILABILITY_JSON = REPO_ROOT / "infra" / "model-availability.json"

# roadmodel catalog id -> Anthropic API model id. Keep in sync with the Anthropic
# models in <model-options> (test_probe_availability asserts the ids are valid).
WATCH: dict[str, str] = {
    "claude-fable-5": "claude-fable-5",
    "opus-4.8": "claude-opus-4-8",
    "opus-4.7": "claude-opus-4-7",
    "sonnet-4.6": "claude-sonnet-4-6",
    "claude-4.5-haiku": "claude-haiku-4-5",
}

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def classify_probe(status: int, body: str) -> str:
    """Map an Anthropic /v1/messages response to available|unavailable|ambiguous.

    Only an explicit not-found is 'unavailable'. Anything else non-200 (auth,
    rate-limit, 5xx, malformed) is 'ambiguous' — never bench on uncertainty.
    """
    if status == 200:
        return "available"
    low = body.lower()
    if (
        status == 404
        or "not_found_error" in low
        or "not found" in low
        or "does not exist" in low
        or "is not available" in low
    ):
        return "unavailable"
    return "ambiguous"


def probe_model(api_id: str, key: str) -> str:
    """Invoke a model with a 1-token request; return its availability class."""
    payload = json.dumps(
        {"model": api_id, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    ).encode()
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    req = urllib.request.Request(_ANTHROPIC_URL, data=payload, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return classify_probe(resp.status, "")
    except urllib.error.HTTPError as exc:
        return classify_probe(exc.code, exc.read().decode(errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError):
        return "ambiguous"  # transient / network -> fail-safe


def reconcile(
    results: dict[str, str], current: list[Any], today: str
) -> tuple[list[Any], list[str], list[str]]:
    """Apply probe results to the current ``unavailable`` entries.

    - a WATCH id that probed 'unavailable' and isn't listed -> ADD (source=probe)
    - a WATCH id that probed 'available' and IS listed       -> REMOVE (self-heal)
    - 'ambiguous', and any non-WATCH entry, are left untouched
    Returns (new_unavailable_list, added_ids, removed_ids).
    """
    listed = {e["id"] for e in current if isinstance(e, dict) and e.get("id")}
    removed: list[str] = []
    new_list: list[Any] = []
    for entry in current:
        mid = entry.get("id") if isinstance(entry, dict) else None
        if mid in WATCH and results.get(mid) == "available":
            removed.append(mid)
            continue  # re-enabled
        new_list.append(entry)
    added: list[str] = []
    for mid in WATCH:
        if results.get(mid) == "unavailable" and mid not in listed:
            new_list.append(
                {
                    "id": mid,
                    "reason": (
                        f"Auto-detected unavailable by the daily Anthropic probe on "
                        f"{today} (the API returned model-not-found)."
                    ),
                    "since": today,
                    "source": "probe",
                }
            )
            added.append(mid)
    return new_list, sorted(added), sorted(removed)


def run(path: Path, key: str, today: str, *, dry_run: bool) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    results = {rm_id: probe_model(api_id, key) for rm_id, api_id in WATCH.items()}
    for rm_id, cls in sorted(results.items()):
        print(f"  probe {rm_id:18} -> {cls}")

    new_list, added, removed = reconcile(results, data.get("unavailable", []), today)
    print(f"add (now unavailable): {added or '(none)'}")
    print(f"remove (re-enabled):   {removed or '(none)'}")
    if not added and not removed:
        print("No availability changes.")
        return 0
    if dry_run:
        print("DRY RUN — model-availability.json not written.")
        return 0
    data["unavailable"] = new_list
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path.name}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Anthropic model availability.")
    parser.add_argument("--dry-run", action="store_true", help="Probe + print plan; do not write.")
    parser.add_argument("--json", type=Path, default=AVAILABILITY_JSON)
    args = parser.parse_args(argv)

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ANTHROPIC_API_KEY required.", file=sys.stderr)
        return 2
    today = datetime.datetime.now(tz=datetime.timezone.utc).date().isoformat()
    return run(args.json, key, today, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
