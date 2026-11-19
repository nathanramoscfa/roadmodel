#!/usr/bin/env python3
"""Collect the launch-day benchmark table of each catalog model Artificial
Analysis has not measured, for roadmodel's day-one AA Index estimate.

For each such model with no table yet in update/launch-tables.json, Opus reads
the vendor's own launch materials and transcribes the headline comparison
table, every column, naming each column's model by its catalog or benchmark id.
It finds them with web search and reads them with web fetch, which may open
vendor domains only (VENDOR_DOMAINS); Artificial Analysis is blocked in both,
and its rows are left out. The reply is data: it is kept only once
update/launch_data.check_launch_tables accepts it (ids from the roster, percent
scores, the model's own column present). update/build_index_estimates.py then
writes docs/index-estimates.json.

Spend is capped in dollars, from the API's own usage figures (opus_turn.
turn_cost): each entry's ``spent_usd`` is what its tries cost, and

* a model is tried at most MAX_ATTEMPTS times, RETRY_DAYS apart, and never
  again once it has cost MODEL_BUDGET_USD;
* no try starts once the tries of the last RETRY_DAYS days cost
  WEEKLY_BUDGET_USD (counted from each tried model's whole ledger, so the
  count can only run high);
* a run tries at most MAX_MODELS_PER_RUN models, newest first, and each try is
  one Opus turn capped at SEARCH_USES searches and FETCH_USES fetches of
  FETCH_TOKENS each.

A model its own launch table already places is never tried again; one only
later launches' tables place (estimate.from_other_tables) still is, since its
own table places it more closely.

    python update/collect_launch_tables.py            # needs ANTHROPIC_API_KEY
    python update/collect_launch_tables.py --dry-run  # the models it would try
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

UPDATE = Path(__file__).resolve().parent
REPO = UPDATE.parent
for path in (UPDATE, REPO / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import launch_data  # noqa: E402

from roadmodel import estimate  # noqa: E402

TABLES = UPDATE / "launch-tables.json"
# What a run could not do (an API error, a missing key): the workflow fails on
# it, which raises the cron-health alarm. A try that found no table is no error.
ERRORS = UPDATE / ".cache" / "launch-tables-errors.txt"
BENCHMARKS = REPO / "docs" / "benchmarks.json"
CATALOG = REPO / "docs" / "catalog.json"

MAX_MODELS_PER_RUN = 2
MAX_ATTEMPTS = 3
RETRY_DAYS = 7
MODEL_BUDGET_USD = 4.0
WEEKLY_BUDGET_USD = 10.0
SEARCH_USES = 5
FETCH_USES = 6
FETCH_TOKENS = 100_000
MAX_TOKENS = 16_000

# Where a vendor publishes its launch materials: announcements, model and
# system cards, evaluation PDFs, docs, official model cards and repositories.
VENDOR_DOMAINS = (
    "anthropic.com",
    "www.anthropic.com",
    "www-cdn.anthropic.com",
    "assets.anthropic.com",
    "docs.anthropic.com",
    "platform.claude.com",
    "openai.com",
    "cdn.openai.com",
    "deploymentsafety.openai.com",
    "developers.openai.com",
    "platform.openai.com",
    "deepmind.google",
    "storage.googleapis.com",
    "blog.google",
    "ai.google.dev",
    "x.ai",
    "docs.x.ai",
    "ai.meta.com",
    "about.fb.com",
    "dev.meta.ai",
    "research.meta.ai",
    "mistral.ai",
    "docs.mistral.ai",
    "huggingface.co",
    "z.ai",
    "docs.z.ai",
    "moonshotai.github.io",
    "platform.moonshot.ai",
    "api-docs.deepseek.com",
    "github.com",
    "raw.githubusercontent.com",
    "arxiv.org",
    "cursor.com",
    "docs.cursor.com",
)
BLOCKED = ["artificialanalysis.ai"]

SYSTEM = """You transcribe a newly released AI model's launch benchmark table.

Find the model VENDOR's own launch materials: the announcement post, the model
or system card (PDFs count), the evaluation methodology document, or the
official model card or repository. For OpenAI releases whose announcement page
is unreachable or omits capability tables, also check
https://deploymentsafety.openai.com/. Use web search only to locate them; read
values only from the vendor's pages. Never take a value from a third-party
site, and never record an Artificial Analysis metric: skip any row labeled AA,
"-AA", "(AA)", Artificial Analysis or AA Index, or footnoted as coming from
Artificial Analysis, and set to null any cell footnoted as Artificial
Analysis's run.

Transcribe capability and reasoning benchmark tables first (skip safety-refusal,
policy-compliance, jailbreak, or toxicity-only tables): every row and every
column, the competitor and predecessor columns included; they are the point.
If the vendor published no multi-column comparison table, a single-column list
or table reporting the launching model's own capability scores still counts
(with columns [model_id]). Values exactly as printed, percentages as
percentages (0-100). Leave out rows in other units (Elo, dollars, ratings,
seconds). A blank, dash or "not reported" is null. Mark a lower-is-better row
"higher_is_better": false. When a row measures one of the five index
components ("hle" for Humanity's Last Exam without tools, "terminalbench_v4_0"
for Terminal-Bench 4.0, "scicode" for SciCode, "terminalbench_v2_1" for
Terminal-Bench 2.1, "gpqa" for GPQA Diamond without tools), tag it
"component": "<key>". When the launching model has several columns (effort
levels, Pro, Deep Think, Heavy, parallel or best-of-N, "without safeguards"),
keep only the one at its highest standard effort as the model's own column; the
others are null columns.

Name each column's model with an id from the roster in the request, or null
when the column is a model the roster does not list or another configuration
of a listed model. The launching model's own column is its id.

Reply with ONE JSON object and nothing else:
{"release_date": "YYYY-MM-DD" or null,
 "tables": [{"source": "https://...", "columns": [id or null, ...],
             "rows": [{"benchmark": "name", "values": [number or null, ...],
                       "higher_is_better": true, "component": "hle"}]}]}
Omit "component" unless the row is one of those five components. Each row's
values align one-to-one with its table's columns. Reply
{"release_date": null, "tables": []} when the vendor published no capability
benchmarks you can read."""


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def roster(catalog: dict[str, Any], bench: dict[str, Any]) -> dict[str, str]:
    """Every id a column may name, with the name a vendor would print."""
    out = {
        str(b_id): str(row.get("aa_name") or b_id)
        for b_id, row in bench.items()
        if isinstance(row, dict)
    }
    for m in catalog.get("models", []):
        if isinstance(m, dict) and m.get("id"):
            out[str(m["id"])] = str(m.get("name") or m["id"])
    return dict(sorted(out.items()))


def _spent(entry: Any) -> float:
    value = entry.get("spent_usd") if isinstance(entry, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def weekly_spend(tables: dict[str, Any], today: dt.date) -> float:
    """What the tries of the last RETRY_DAYS days cost, high side: each model
    tried in that window counts its whole ledger (it can have been tried at
    most once in it)."""
    total = 0.0
    for entry in tables.values():
        checked = entry.get("checked_on") if isinstance(entry, dict) else None
        if isinstance(checked, str) and (today - dt.date.fromisoformat(checked)).days < RETRY_DAYS:
            total += _spent(entry)
    return round(total, 3)


def due(
    catalog: dict[str, Any], bench: dict[str, Any], tables: dict[str, Any], today: dt.date
) -> list[str]:
    """The catalog models to try this run, newest first: AA has not measured
    them, their own table does not place them yet, and they have no table, or
    their last try is RETRY_DAYS old, under MAX_ATTEMPTS tries and
    MODEL_BUDGET_USD."""
    estimates = estimate.estimate_all(tables, bench, catalog=catalog)
    out: list[tuple[str, str]] = []
    for m in catalog.get("models", []):
        mid = str(m.get("id", "")) if isinstance(m, dict) else ""
        if not mid or estimate.measured_index(bench, mid) is not None:
            continue
        if mid in estimates and estimates[mid].method in estimate.OWN_METHODS:
            continue
        entry = tables.get(mid)
        date = str(
            (entry or {}).get("release_date")
            or m.get("added_on")
            or (bench.get(mid) or {}).get("release_date")
            or ""
        )
        if entry is None:
            out.append((date, mid))
            continue
        attempts = int(entry.get("attempts") or 0)
        checked = entry.get("checked_on")
        stale = not checked or (today - dt.date.fromisoformat(checked)).days >= RETRY_DAYS
        if attempts < MAX_ATTEMPTS and stale and _spent(entry) < MODEL_BUDGET_USD:
            out.append((date, mid))
    # Newest first; a model with no date known goes last. sorted() is stable,
    # so equal dates keep the catalog's order.
    out = sorted(out, key=lambda pair: pair[0], reverse=True)
    return [mid for _, mid in out][:MAX_MODELS_PER_RUN]


def request(model_id: str, name: str, ids: dict[str, str]) -> str:
    lines = "\n".join(f"{i}: {n}" for i, n in ids.items())
    return (
        f"Model: {name} (id {model_id}).\n\nRoster of ids a column may name (id: name):\n{lines}\n"
    )


def tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": SEARCH_USES,
            "blocked_domains": BLOCKED,
        },
        {
            "type": "web_fetch_20260318",
            "name": "web_fetch",
            "max_uses": FETCH_USES,
            "max_content_tokens": FETCH_TOKENS,
            "allowed_domains": list(VENDOR_DOMAINS),
        },
    ]


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


def parse(text: str) -> dict[str, Any]:
    """The reply's JSON object: the whole text, a fenced block, or the span
    from its first ``{`` to its last ``}``."""
    raw = text.strip()
    for candidate in (raw, *(m.group(1) for m in _FENCE.finditer(raw))):
        try:
            doc = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            return doc
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        doc = json.loads(raw[start : end + 1])
        if isinstance(doc, dict):
            return doc
    raise ValueError("no JSON object in the reply")


def entry_from(
    reply: dict[str, Any], previous: dict[str, Any] | None, today: dt.date, cost: float = 0.0
) -> dict[str, Any]:
    """The launch-tables entry a reply makes: its tables (the previous ones
    when it found none), the release date, the try counted and its cost added
    to the ledger."""
    release = reply.get("release_date")
    if not isinstance(release, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release):
        release = (previous or {}).get("release_date") or today.isoformat()
    tables = reply.get("tables")
    if not isinstance(tables, list) or not tables:
        tables = list((previous or {}).get("tables") or [])
    entry: dict[str, Any] = {
        "release_date": release,
        "tables": tables,
        "checked_on": today.isoformat(),
        "attempts": int((previous or {}).get("attempts") or 0) + 1,
    }
    spent = round(_spent(previous) + cost, 3)
    if spent:
        entry["spent_usd"] = spent
    return entry


def collect(
    client: Any, model_id: str, name: str, ids: dict[str, str], previous: dict[str, Any] | None
) -> dict[str, Any]:
    """One Opus turn for ``model_id``: the entry its reply makes, its cost in
    the ledger. A turn that ends unfinished or replies with no JSON counts as a
    try that found none; so does an API error after a response was billed. An
    API error before any is raised: nothing was read, so it is no try."""
    from anthropic import APIError
    from opus_turn import OPUS_MODEL, OpusTurnIncomplete, stream_until_complete

    costs: list[float] = []
    try:
        text = stream_until_complete(
            client,
            model=OPUS_MODEL,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM}],
            user_message=request(model_id, name, ids),
            tools=tools(),
            label=f"launch-table {model_id}",
            on_cost=costs.append,
        )
        reply = parse(text)
    except (OpusTurnIncomplete, ValueError) as err:
        print(f"{model_id}: {err}; recorded as no table", file=sys.stderr)
        reply = {}
    except APIError as err:
        if not costs:
            raise
        print(f"{model_id}: {type(err).__name__} after a billed response; recorded as no table")
        reply = {}
    return entry_from(reply, previous, _today(), sum(costs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list the models it would try")
    parser.add_argument(
        "--prune-only",
        action="store_true",
        help="drop retired catalog models from launch-tables.json and exit",
    )
    args = parser.parse_args(argv)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    bench = json.loads(BENCHMARKS.read_text(encoding="utf-8"))["models"]
    doc = json.loads(TABLES.read_text(encoding="utf-8"))
    tables: dict[str, Any] = doc["models"]
    ids = roster(catalog, bench)
    names = {str(m["id"]): str(m.get("name") or m["id"]) for m in catalog["models"]}
    # A model that left the catalog needs no table.
    for gone in sorted(set(tables) - set(names)):
        del tables[gone]
    if args.prune_only:
        TABLES.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return 0
    targets = due(catalog, bench, tables, _today())
    print(
        f"launch tables due: {', '.join(targets) or 'none'} "
        f"(last {RETRY_DAYS} days: ${weekly_spend(tables, _today()):.2f} "
        f"of ${WEEKLY_BUDGET_USD:.2f})"
    )
    if args.dry_run or not targets:
        TABLES.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return 0
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        ERRORS.parent.mkdir(parents=True, exist_ok=True)
        ERRORS.write_text("ANTHROPIC_API_KEY is not set\n", encoding="utf-8")
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    from anthropic import Anthropic, APIError

    client = Anthropic(api_key=api_key)
    errors: list[str] = []
    for mid in targets:
        week = weekly_spend(tables, _today())
        if week >= WEEKLY_BUDGET_USD:
            print(f"weekly budget reached (${week:.2f}); {mid} and the rest wait")
            break
        previous = tables.get(mid)
        try:
            entry = collect(client, mid, names[mid], ids, previous)
        except APIError as err:
            # Not a try: nothing was read or billed. The next run tries again.
            errors.append(f"{mid}: {type(err).__name__}: {err}")
            continue
        try:
            launch_data.check_launch_tables(
                {**doc, "models": {**tables, mid: entry}}, set(ids), set(names)
            )
        except ValueError as err:
            # Data this check refuses is a try that found nothing usable.
            print(f"{mid}: transcription refused ({err}); recorded as no table", file=sys.stderr)
            entry = {**entry, "tables": list((previous or {}).get("tables") or [])}
        tables[mid] = entry
        found = estimate.estimate(mid, entry, bench)
        print(
            f"{mid}: {len(entry['tables'])} table(s); estimate {found.index if found else 'none'}; "
            f"ledger ${_spent(entry):.2f} over {entry['attempts']} tries"
        )
    TABLES.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    ERRORS.parent.mkdir(parents=True, exist_ok=True)
    ERRORS.write_text("".join(f"{line}\n" for line in errors), encoding="utf-8")
    for line in errors:
        print(line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
