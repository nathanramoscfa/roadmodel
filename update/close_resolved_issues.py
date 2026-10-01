#!/usr/bin/env python3
"""Close the catalog crons' own issues once the catalog resolves them.

The crons file an issue when a source names a model the catalog lacks (a CLI's
docs, a provider's price list), or when a snapshot lists one the curation pass
neither added nor declined. A later automated refresh usually resolves it,
and the issue stayed open anyway, waiting for someone to notice. This closes
each one whose condition no longer holds in the committed catalog, saying how
it was resolved:

- ``chore(catalog): <Tool> docs introduced model "<model>"`` and
  ``chore(catalog): provider-direct model "<model>" not in <model-options>``
  close when <model> is a ``<model>`` in docs/model-selector.txt;
- ``chore(catalog): provider page prices "<provider>/<slug>"; …`` closes when
  the model is in the catalog or declined in the discovery lane
  (docs/model-tier-cost-scale.md).

Runs daily in .github/workflows/cron-health.yml.

    python update/close_resolved_issues.py            # close resolved issues
    python update/close_resolved_issues.py --dry-run  # print what it would close
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discovery import _variants, catalog_keys, normalize, parse_declined  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"

_MODEL_ISSUE = re.compile(
    r'^chore\(catalog\): (?:.+ docs introduced model|provider-direct model) "(?P<model>[^"]+)"'
)
_DISCOVERY_ISSUE = re.compile(
    r'^chore\(catalog\): provider page prices "(?P<provider>[^/"]+)/(?P<slug>[^"]+)"'
)


def resolution(title: str, keys: set[str], declined: set[tuple[str, str]]) -> str | None:
    """How the committed catalog resolves the issue titled ``title``, or None
    while it still stands."""
    if m := _MODEL_ISSUE.match(title):
        if _variants(m["model"]) & keys:
            return f"`{m['model']}` is in the catalog (docs/model-selector.txt)."
        return None
    if m := _DISCOVERY_ISSUE.match(title):
        if _variants(m["slug"]) & keys:
            return f"`{m['slug']}` is in the catalog (docs/model-selector.txt)."
        if (m["provider"].lower(), normalize(m["slug"])) in declined:
            return (
                f"`{m['provider']}/{m['slug']}` is declined in the discovery lane "
                "(docs/model-tier-cost-scale.md)."
            )
    return None


def open_issues() -> list[tuple[int, str]]:
    out = subprocess.run(  # noqa: S603 — fixed gh binary, no shell, literal args
        [  # noqa: S607 — "gh" resolved via the runner's PATH
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "300",
            "--json",
            "number,title",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [(int(i["number"]), str(i["title"])) for i in json.loads(out)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="print, close nothing")
    args = parser.parse_args()

    keys = catalog_keys(SELECTOR_PATH.read_text(encoding="utf-8"))
    declined = {
        (d.provider.lower(), normalize(d.slug))
        for d in parse_declined(COST_SCALE_PATH.read_text(encoding="utf-8"))
    }
    closed = 0
    for number, title in open_issues():
        reason = resolution(title, keys, declined)
        if reason is None:
            continue
        closed += 1
        print(f"#{number} {title} — {reason}")
        if not args.dry_run:
            subprocess.run(  # noqa: S603 — fixed gh binary, no shell; the number and comment are ours
                [  # noqa: S607 — "gh" resolved via the runner's PATH
                    "gh",
                    "issue",
                    "close",
                    str(number),
                    "--comment",
                    f"Resolved automatically: {reason} Closed by update/close_resolved_issues.py.",
                ],
                check=True,
            )
    print(f"{closed} resolved issue(s){' (dry run)' if args.dry_run else ' closed'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
