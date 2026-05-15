"""Subscription Tiers freshness watchdog.

The "Subscription Tiers and Access Methods" section of
docs/model-tier-cost-scale.md is refreshed weekly by the cron using the
Anthropic web_search server-side tool (see update/prompt.md §
"Subscription tiers"). The cron updates the
`<!-- subscription-tiers-reviewed: YYYY-MM-DD -->` marker to today's
date only when every row in the table was either verified unchanged or
successfully updated against clear official-source evidence; an
inconclusive run leaves the marker verbatim.

A stale marker therefore indicates one of:
- The cron has failed for 180+ days (test_freshness.py would also trip).
- The cron has succeeded but subscription verification has been
  inconclusive every week for 180+ days (web_search is returning
  ambiguous results or hitting rate limits persistently).

Either case warrants a manual eyeball pass and a hand-bump of the
marker. After confirming the four provider pricing pages, bump the
`<!-- subscription-tiers-reviewed: YYYY-MM-DD -->` line in
docs/model-tier-cost-scale.md to today's date.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"
STALE_DAYS_THRESHOLD = 180
MARKER_RE = re.compile(r"<!--\s*subscription-tiers-reviewed:\s*(\d{4}-\d{2}-\d{2})\s*-->")


def test_subscription_tiers_recently_reviewed() -> None:
    text = COST_SCALE_PATH.read_text()
    match = MARKER_RE.search(text)
    assert match, (
        "docs/model-tier-cost-scale.md is missing the "
        "`<!-- subscription-tiers-reviewed: YYYY-MM-DD -->` marker above "
        "the Subscription Tiers section. Add it and set today's date."
    )
    reviewed = dt.date.fromisoformat(match.group(1))
    age_days = (dt.date.today() - reviewed).days
    assert age_days <= STALE_DAYS_THRESHOLD, (
        f"Subscription Tiers section was last reviewed {age_days} days ago "
        f"(threshold: {STALE_DAYS_THRESHOLD} days). Eyeball each "
        f"provider's pricing page and bump the marker:\n"
        f"  - https://cursor.com/pricing\n"
        f"  - https://anthropic.com/pricing\n"
        f"  - https://openai.com/chatgpt/pricing\n"
        f"  - https://gemini.google.com/advanced\n"
        f"Then update `<!-- subscription-tiers-reviewed: YYYY-MM-DD -->` "
        f"in docs/model-tier-cost-scale.md to today's date."
    )
