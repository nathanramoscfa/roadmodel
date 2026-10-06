# scripts/check_funding_invariant.py
"""Daily alarm: the operator's money pays for the operator lane only.

Phase 4.11 funds a request from one of three lanes (web/lib/funding-lane.ts):
the operator's own provider keys, the visitor's key, or no key at all. The
operator lane answers exactly three reasons, `founder`, `invited` and `bypass`,
and `web/app/api/recommend/route.ts` stamps the reason into
`audit_log.cache_stats.funding_reason` on the row it writes.

This check reads the last 25 hours of `audit_log` and fails when an operator
row that spent money breaks either rule:

  * its reason is outside {founder, invited, bypass} (or absent);
  * it has no `user_id` and its reason is not `bypass` (founder and invited
    are signed-in lanes, so an anonymous operator row is a lane leak).

A row "spent money" when its outcome is `ok` or its `cost_usd` is above zero.
Refusals the operator lane writes before any provider call (`rate_limited`,
`burst_dropped`, `daily_cost_cap`, `bypassed_rate_limit`) carry no reason by
design and moved nothing, so they are not judged.

The output is counts and row ids only: never a user id, an IP hash, or any
`cache_stats` content. Exit 0 = clean, 1 = violations (cron-health.yml turns
that into the tracking issue), 2 = could not read the ledger.

Usage (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in the environment):
    python scripts/check_funding_invariant.py [--hours 25]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

ALLOWED_REASONS = frozenset({"founder", "invited", "bypass"})
PAGE = 1000
# Only the columns the rule reads. Nothing here identifies a person.
SELECT = "id,user_id,outcome,cost_usd,cache_stats"

Row = dict[str, Any]
PageReader = Callable[[str, int, int], list[Row]]


def spent_money(row: Row) -> bool:
    """True when the operator's provider key was used for this row."""
    cost = row.get("cost_usd")
    return (
        row.get("outcome") == "ok"
        or (isinstance(cost, int | float) and cost > 0)
        or (isinstance(cost, str) and _positive(cost))
    )


def _positive(text: str) -> bool:
    try:
        return float(text) > 0
    except ValueError:
        return False


def funding_reason(row: Row) -> str | None:
    stats = row.get("cache_stats")
    if isinstance(stats, dict):
        reason = stats.get("funding_reason")
        if isinstance(reason, str):
            return reason
    return None


def violation(row: Row) -> str | None:
    """Why this operator row breaks the invariant, or None when it holds."""
    if not spent_money(row):
        return None
    reason = funding_reason(row)
    if reason not in ALLOWED_REASONS:
        return "reason_outside_lane"
    if row.get("user_id") is None and reason != "bypass":
        return "anonymous_non_bypass"
    return None


def find_violations(rows: Iterable[Row]) -> list[tuple[Any, str]]:
    found: list[tuple[Any, str]] = []
    for row in rows:
        why = violation(row)
        if why:
            found.append((row.get("id"), why))
    return found


def read_operator_rows(since_iso: str, page: PageReader) -> list[Row]:
    """Every operator row since `since_iso`, page by page (never the 1,000-row default)."""
    rows: list[Row] = []
    start = 0
    while True:
        chunk = page(since_iso, start, start + PAGE - 1)
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        start += PAGE


def postgrest_page(base_url: str, key: str) -> PageReader:
    def read(since_iso: str, start: int, end: int) -> list[Row]:
        query = urllib.parse.urlencode(
            {
                "select": SELECT,
                "funded_by": "eq.operator",
                "ts": f"gte.{since_iso}",
                "order": "id",
            }
        )
        req = urllib.request.Request(  # noqa: S310  (https only, checked in main)
            f"{base_url.rstrip('/')}/rest/v1/audit_log?{query}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Range-Unit": "items",
                "Range": f"{start}-{end}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310
            body = json.loads(resp.read())
        if not isinstance(body, list):
            raise ValueError("audit_log read did not return a list")
        return body

    return read


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hours", type=float, default=25.0)
    args = parser.parse_args(argv)

    base_url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base_url.startswith("https://") or not key:
        print("funding-invariant: SUPABASE_URL (https) and SUPABASE_SERVICE_ROLE_KEY are required")
        return 2

    since = (datetime.now(UTC) - timedelta(hours=args.hours)).isoformat()
    try:
        rows = read_operator_rows(since, postgrest_page(base_url, key))
    except (urllib.error.URLError, ValueError, OSError) as err:
        # The error class only: a URLError string can carry the request URL.
        print(f"funding-invariant: could not read audit_log ({type(err).__name__})")
        return 2

    spent = [r for r in rows if spent_money(r)]
    found = find_violations(rows)
    print(
        f"funding-invariant: {len(rows)} operator rows in the last {args.hours:g}h, "
        f"{len(spent)} spent money, {len(found)} violations"
    )
    for row_id, why in found:
        print(f"  VIOLATION row id={row_id} rule={why}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
