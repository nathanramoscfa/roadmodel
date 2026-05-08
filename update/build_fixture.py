#!/usr/bin/env python3
"""Build a sources-fixture JSON for `update_models.py --fixture`.

Fetches the live upstream sources (same path the Monday cron uses),
injects a synthetic Cursor pricing row to exercise the Model lifecycle
rules in update/prompt.md, and writes a JSON fixture in the shape
consumed by `update_models.py --fixture`.

Usage:

    # Build a fixture for the costlier-successor scenario
    python update/build_fixture.py costlier-successor \\
        --output tests/fixtures/costlier_successor.json

    # Preview the LLM's decision (one Opus call, ~$0.50-1.00)
    python update/update_models.py --dry-run \\
        --fixture tests/fixtures/costlier_successor.json

Why "permanent" = generator + transient fixture: a committed fixture
would freeze the benchmark snapshots and Cursor pricing the LLM sees,
which ages within weeks. The generator is the durable artifact —
re-run it whenever you want a fresh smoke test against current
upstream data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "update"))

from update_models import gather_sources  # noqa: E402

# Anchored on the GPT-5.5 row (a real OpenAI flagship) so the synthetic
# row sits inside the same provider block. If Cursor ever delists
# GPT-5.5, update ANCHOR_PATTERN.
ANCHOR_PATTERN = re.compile(r"^\| \[GPT-5\.5\][^\n]*\n", re.MULTILINE)

SCENARIOS: dict[str, dict[str, str]] = {
    "costlier-successor": {
        "description": (
            "Inject synthetic GPT-5.6 at $40/M output, above all current "
            "OpenAI flagships. Expected behavior: ADD gpt-5.6 to "
            "<model-options> with auto-assigned tier ratings (no "
            "benchmark signal for this model anywhere → all 7 tiers "
            "default to B); KEEP gpt-5.5 ($30/M) and gpt-5.4 ($15/M) "
            "since the successor is costlier than both. Emit a 'new "
            "model added' warning."
        ),
        # Notes intentionally indistinguishable from a real Cursor row —
        # if we mark this as a fixture, the LLM (correctly) refuses to
        # add it to <model-options>, which prevents the auto-add path
        # from being exercised. Compensate with realistic-looking notes.
        "synthetic_row": (
            "| [GPT-5.6](https://developers.openai.com/api/docs/models/gpt-5.6) "
            "| OpenAI    | $7    | -           | $0.7       | $40    "
            "| Requires Max Mode on request-based plans; Agentic and "
            "reasoning capabilities; Successor to GPT-5.5 with extended "
            "reasoning depth; Fast mode is available at higher rates; "
            "Long context (Max Mode) supports up to 1M tokens with 2x "
            "input pricing |\n"
        ),
    },
    "cheaper-successor": {
        "description": (
            "Inject synthetic GPT-5.6 at $25/M output (≤ gpt-5.5's "
            "$30/M, > gpt-5.4's $15/M). Expected behavior: ADD gpt-5.6; "
            "REMOVE gpt-5.5 (superseded, same series, $25 ≤ $30); KEEP "
            "gpt-5.4 (not superseded since $25 > $15); regenerate the "
            "multimodal and coding S-tier guardrail enumerations to "
            "reflect the swap. Emit 'superseded' and 'new model added' "
            "warnings."
        ),
        # Same rationale as costlier-successor: notes look real so the
        # LLM exercises the full lifecycle path.
        "synthetic_row": (
            "| [GPT-5.6](https://developers.openai.com/api/docs/models/gpt-5.6) "
            "| OpenAI    | $4    | -           | $0.4       | $25    "
            "| Requires Max Mode on request-based plans; Agentic and "
            "reasoning capabilities; More token-efficient than GPT-5.5; "
            "Fast mode is available at higher rates; Long context (Max "
            "Mode) supports up to 1M tokens with 2x input pricing |\n"
        ),
    },
}


def inject_row(pricing_md: str, synthetic_row: str) -> str:
    match = ANCHOR_PATTERN.search(pricing_md)
    if match is None:
        raise SystemExit(
            "Anchor pattern (GPT-5.5 row) not found in Cursor pricing "
            "markdown. The pricing schema may have changed; update "
            "ANCHOR_PATTERN in update/build_fixture.py."
        )
    insert_at = match.end()
    return pricing_md[:insert_at] + synthetic_row + pricing_md[insert_at:]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "scenario",
        choices=sorted(SCENARIOS),
        help="Lifecycle scenario to inject. See module docstring.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the fixture JSON (parent dir auto-created).",
    )
    args = parser.parse_args()

    scenario = SCENARIOS[args.scenario]
    print(f"Scenario: {args.scenario}")
    print(f"  {scenario['description']}\n")

    print("Fetching live upstream sources...")
    fetched, fetch_errors = gather_sources()
    pricing = next((s for s in fetched if s["type"] == "pricing"), None)
    if pricing is None:
        sys.stderr.write(
            "Live Cursor pricing fetch failed; cannot build fixture.\n"
            + "\n".join(fetch_errors)
            + "\n"
        )
        return 1
    print(f"  fetched {len(fetched)} sources, {len(fetch_errors)} fetch errors")

    pricing["content"] = inject_row(pricing["content"], scenario["synthetic_row"])
    print("  injected synthetic GPT-5.6 row after GPT-5.5 anchor\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched": fetched,
        "fetch_errors": fetch_errors,
        "_scenario": args.scenario,
        "_scenario_description": scenario["description"],
    }
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {args.output}")
    print("\nNow run:")
    print(f"  python update/update_models.py --dry-run --fixture {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
