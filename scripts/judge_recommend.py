#!/usr/bin/env python3
# scripts/judge_recommend.py
"""B2 and B6 of the Phase 4.5 quality bar, scored from one recommender soak.

scripts/soak-recommend.ts writes one JSONL row per call, each carrying the
whole Cost / Balanced / Quality ladder the user saw and the engine that wrote
it. This script reads the anonymous first-pass rows (the bundled public
user-context, the basis of the T1 gold differential) and scores two criteria:

B2, the pick is spec-correct. Each probe in scripts/soak_probes.json carries
hand gold labels (category, complexity, novel). The scorer recomputes the
ladder-table row for those labels over the same user-context, with the
roadmodel version installed here (the workflow installs the one production's
/healthz reports). The probe passes when neither the app's PRIMARY (Balanced,
the anonymous default) nor its QUALITY rung is weaker in the gold category than
the gold row's: the same model at no lower effort, or another model whose
quality there is at least the gold model's. A stronger pick passes (quality
first: over-escalation is spec-compliant). Bar: every probe.

B6, an LLM judge: would a user who otherwise hands docs/model-selector.txt to
Opus accept this recommendation? Each ladder is graded on six criteria
(RUBRIC below); the code accepts it when no criterion fails as a blocker. Bar:
at least 95% accepted, every row judged, and every control graded as expected.
Guards against the judge's own bias:
  - the judge's maker must differ from the engine's (it never grades its own
    maker's output; a row from the judge's maker fails B6 rather than count);
  - the judge grades against a fact sheet built from the scorer's own data
    (prices, AA Intelligence Index, per-category letters, funded platforms and
    their effort dials), and a blocker must cite one of those facts;
  - seeded controls run with every batch: three known-bad ladders (a Quality
    rung demoted to the cheapest model, a rationale that does the task, an
    Anthropic flagship on the Cost rung where a cheaper model of another maker
    is adequate) must be rejected, and two gold-row ladders whose picks are
    not Anthropic's must be accepted. Any miss marks the judge invalid and
    B6 fails, so a biased grade is never counted;
  - one ladder per call, so no position bias; length is not a criterion; the
    judge is not told which engine wrote the ladder.

The judge runs through Claude Code headless (`claude -p`, no tools, structured
output), authenticated by the CLAUDE_CODE_OAUTH_TOKEN subscription token in CI:
no API key is read, so it never spends API cash. Calls are capped per run
(--max-calls).

Usage (repo root, a venv with roadmodel installed):
  python scripts/judge_recommend.py --rows /tmp/rm-soak-recommend.jsonl
  python scripts/judge_recommend.py --rows ... --no-judge    # B2 only, free
  python scripts/judge_recommend.py --rows ... --dry-run     # print the prompts
Exit 0 when B2 and B6 pass, 1 when either fails, 2 on bad input.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from roadmodel import cost as _cost
from roadmodel import scoring

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBES_FILE = REPO / "scripts" / "soak_probes.json"
AVAILABILITY_FILE = REPO / "infra" / "model-availability.json"
DEFAULT_OUT = "/tmp/rm-judge-recommend.json"  # noqa: S108  # nosec B108 - a report path, like the soak's

JUDGE_MODEL = "claude-opus-5-5"
# The maker of every model the judge may run as (claude -p runs Anthropic's).
JUDGE_MAKER = "Anthropic"
B2_BAR = 1.0
B6_BAR = 0.95
# 33 probes and 5 controls fit; anything past the cap is left unjudged (and
# so fails B6) rather than spent.
MAX_JUDGE_CALLS = 45
# Quality points two different models may differ by and still count as level.
QUALITY_TOLERANCE = 0.5
PRIORITY_TO_TIER = {"cheap": "cost", "balanced": "balanced", "best": "quality"}
TIER_LABEL = {"cost": "COST", "balanced": "BALANCED", "quality": "QUALITY"}
CRITERIA = ("J1", "J2", "J3", "J4", "J5", "J6")
STEP3_MINIMUM = {"low": "B", "medium": "A", "high": "S"}

RUBRIC = """\
You review model recommendations for a person who would otherwise paste a
long model-selection spec into Opus and follow its advice. For one task, the
app recommends three picks: COST (the cheapest pick that still does the task
well), BALANCED (the best value) and QUALITY (the strongest the person can
run), each a model on a platform at an effort, with a BACKUP from another
maker and a short rationale (TASK / PICK / EFFORT). Decide whether that person
would accept the recommendation as given, or would have to redo it.

Grade every criterion. A failure is a BLOCKER when the person would reject or
redo the recommendation because of it, and MINOR when they would shrug and
use it anyway.

J1 Task read. The TASK line names a fair category and complexity for the
   task, by the categories and the complexity rule below. Two defensible
   readings both pass; a reading that sends the picks to the wrong kind of
   model is a blocker.
J2 Quality pick. QUALITY is adequate (below) and no model the person can
   run has a clearly higher score in the task's primary category (more than 5
   points). Picking a stronger or pricier model than needed is never a
   failure here.
J3 Ladder shape. The picks are read off the person's cost/quality frontier
   (listed in the fact sheet): COST is the cheapest adequate frontier model,
   QUALITY the adequate model with the highest category score, BALANCED one
   between them; a lower effort is a cheaper point of the same model. So
   COST <= BALANCED <= QUALITY in list price and strength, every rung is
   adequate, and a COST much pricier than an adequate cheaper frontier model
   is a blocker. Rungs may share a model when the effort steps up, or when
   one model is the clear answer for all three.
J4 Platform. Every pick and backup runs on a platform the person funds (their
   subscriptions below cost them nothing extra); routing a model to a
   pay-per-token platform when a funded one runs it is a blocker. A BACKUP
   must come from a different maker than its pick.
J5 Settings. The effort fits the task (no maximum effort on a trivial task's
   COST pick, no minimum on a hard task's QUALITY pick) and uses the level
   names of the platform's own dial; where the platform has no dial, no
   effort is claimed.
J6 Rationale. Accurate against the fact sheet (letters, index, prices,
   platforms), about the choice, and it does not perform the task (no story,
   plan, proof, code or answer to the task itself).

Adequate means that at the effort the pick runs, the model's score in the
task's primary category AND its general score both meet the bar for the
task's complexity: Low 30, Medium 50, High 70, novel 85. A hard task needs a
capable model as well as one that does its kind of work. Scores fall as the
effort drops; a pick within 5 points of the bar is minor at worst. A pick
cannot run above its task's effort ceiling (in the fact sheet).

Judge only against the facts below and the task. Do not reward a maker or a
model family for its own sake; judge each pick by its letters, index, price
and platform. Do not reward length or style. For each criterion give pass,
evidence first (one short sentence naming the fact you relied on), then pass
and severity (use "minor" when it passes). Write the summary before the
criteria, and set accept to false exactly when some criterion fails as a
blocker. Do not repeat the person's subscriptions in the
evidence.

Categories: coding (implementation, debugging, refactoring, tests); planning
(architecture, design, multi-step plans, trade-offs); agentic (autonomous tool
use, terminal, long multi-step execution); multimodal (image, video, audio,
screenshots); long-context (large files or repos, multi-document synthesis);
knowledge (domain expertise, factual recall, writing); speed
(latency-sensitive or high-volume routine work). Complexity is the highest of
complexity, ambiguity, scope and novelty, each Low / Medium / High; novel
means research-grade (an open problem, a new algorithm, a proof nobody has
written), and only at High.
"""

# Reasoning comes before every grade (structured output is written in property
# order): the summary first, then each criterion's evidence before its pass and
# severity, then the overall verdict, which must agree with the criteria.
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": list(CRITERIA)},
                    "evidence": {"type": "string"},
                    "pass": {"type": "boolean"},
                    "severity": {"type": "string", "enum": ["blocker", "minor"]},
                },
                "required": ["id", "evidence", "pass", "severity"],
                "additionalProperties": False,
            },
        },
        "accept": {"type": "boolean"},
    },
    "required": ["summary", "criteria", "accept"],
    "additionalProperties": False,
}
# Evidence shorter than this is a placeholder, not a reason.
MIN_EVIDENCE_CHARS = 20

# A rationale that performs the task instead of explaining the pick (B1's
# signature), for the leak control.
LEAKED_RATIONALE = {
    "task": "A short story.",
    "pick": (
        "Once upon a time, in a garden at the edge of a quiet town, a small robot named "
        "Bolt pressed a seed into the soil and waited. Day 1: nothing. Day 2: a green "
        "thread of a shoot, and Bolt learned that some things cannot be hurried."
    ),
    "effort": "The story ends when the first tomato ripens and Bolt shares it with the neighbours.",
}


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def load_probes(path: pathlib.Path = PROBES_FILE) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["probes"]
    return probes


def load_rows(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def judged_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The anonymous first-pass row of each probe that answered with a full
    ladder: what B2 and B6 score."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ladder = row.get("ladder") or []
        if (
            row.get("mode") == "anon"
            and row.get("iter") == 1
            and row.get("status") == 200
            and {p.get("priority") for p in ladder} >= set(PRIORITY_TO_TIER)
        ):
            out.setdefault(row["id"], row)
    return out


def bundled_context() -> str:
    """The public user-context template: what the anonymous lane runs on."""
    return (resources.files("roadmodel.data") / "user-context.example.md").read_text(
        encoding="utf-8"
    )


def unavailable_ids(path: pathlib.Path = AVAILABILITY_FILE) -> list[str]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e["id"] for e in doc.get("unavailable", []) if isinstance(e, dict) and e.get("id")]


# --------------------------------------------------------------------------- #
# Picks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Pick:
    model: str
    platform: str | None
    level: str | None


def _level(settings: dict[str, Any]) -> str | None:
    for key in ("effort", "intelligence", "thinking_level"):
        value = settings.get(key)
        if isinstance(value, str) and value and value.upper() != "N/A":
            return value
    return None


def app_picks(row: dict[str, Any]) -> dict[str, Pick]:
    out: dict[str, Pick] = {}
    for pick in row.get("ladder") or []:
        tier = PRIORITY_TO_TIER.get(str(pick.get("priority")))
        if tier and isinstance(pick.get("model"), str):
            settings = pick.get("settings") if isinstance(pick.get("settings"), dict) else {}
            out[tier] = Pick(pick["model"], pick.get("platform"), _level(settings))
    return out


def level_rank(level: str | None) -> int | None:
    if not level:
        return None
    name = scoring.normalize_level(level)
    name = {"ultracode": "max"}.get(name, name)
    order = {n: i for i, n in enumerate(scoring.LEVEL_ORDER)}
    return order.get(name)


def headline_quality(task: scoring.Task, context: str, unavailable: list[str]) -> dict[str, float]:
    """Each reachable model's quality for ``task`` at its headline figures."""
    ranking = scoring.rank(task, context, unavailable_models=unavailable, effort_aware=False)
    out: dict[str, float] = {}
    for c in ranking.candidates:
        out[c.model_name] = max(out.get(c.model_name, -math.inf), c.quality)
    return out


def gold_key(probe: dict[str, Any]) -> str:
    return str(scoring.table_key(probe["category"], probe["complexity"], bool(probe["novel"])))


def gold_keys(probe: dict[str, Any]) -> list[str]:
    """The label's row, then the rows of the readings the spec also supports."""
    return [gold_key(probe)] + [gold_key(a) for a in probe.get("alternatives", [])]


def b2_probe(
    picks: dict[str, Pick],
    probe: dict[str, Any],
    table: dict[str, scoring.Ladder],
    context: str,
    unavailable: list[str],
) -> list[str]:
    """[] when the picks are no weaker than the row of the probe's label or of
    any alternative reading; else the label row's problems."""
    first: list[str] | None = None
    for key in gold_keys(probe):
        gold = table.get(key)
        if gold is None:
            continue
        problems = b2_problems(picks, gold, headline_quality(gold.task, context, unavailable))
        if not problems:
            return []
        if first is None:
            first = problems
    return first if first is not None else [f"no ladder row for {gold_key(probe)}"]


def b2_problems(
    picks: dict[str, Pick], gold: scoring.Ladder, quality: dict[str, float]
) -> list[str]:
    """Why the app's PRIMARY or QUALITY rung is weaker than the gold row's, or []."""
    problems: list[str] = []
    for tier in ("balanced", "quality"):
        app = picks.get(tier)
        rung = gold.rungs[tier]
        want = rung.candidate.model_name
        if app is None:
            problems.append(f"{tier}: missing")
        elif app.model == want:
            have, need = level_rank(app.level), level_rank(rung.level)
            if have is not None and need is not None and have < need:
                problems.append(f"{tier}: {app.model} at {app.level}, gold {rung.level}")
        elif app.model not in quality:
            problems.append(f"{tier}: {app.model} is outside the funded pool")
        elif quality[app.model] < quality.get(want, -math.inf) - QUALITY_TOLERANCE:
            problems.append(
                f"{tier}: {app.model} ({quality[app.model]:.1f}) under gold {want} "
                f"({quality.get(want, math.nan):.1f})"
            )
    return problems


# --------------------------------------------------------------------------- #
# The judge's prompt
# --------------------------------------------------------------------------- #


def headline_aa(bench: dict[str, Any], model_id: str) -> str:
    """The AA Intelligence Index at the model's headline effort, as text."""
    try:
        aa = scoring._evidence(bench, model_id, scoring.FRONTIER_INDEX, None)
    except Exception:  # noqa: BLE001  # nosec B112 - the index is optional context
        aa = None
    return "not measured" if aa is None else f"{aa:g}"


def _bench() -> dict[str, Any]:
    bench: dict[str, Any] = scoring.with_composites(scoring._load_benchmarks())
    return bench


def model_scores(
    model: dict[str, Any], catalog: dict[str, Any], bench: dict[str, Any]
) -> dict[str, dict[str | None, float]]:
    """The scorer's quality for ``model`` in every category plus ``general``
    (the planning measure the general bar reads), at each effort AA measured
    (None: the headline row when it measured none)."""
    levels: list[str | None] = [
        lv for lv in scoring.EFFORT_LADDER if lv in scoring.measured_levels(bench, model["id"])
    ] or [None]
    out: dict[str, dict[str | None, float]] = {}
    for category in scoring.CATEGORIES:
        scale = scoring._evidence_scale(catalog, bench, scoring.CATEGORY_EVIDENCE[category])
        task = scoring.Task(category, "medium")
        out[category] = {lv: scoring._quality(model, task, bench, scale, lv)[0] for lv in levels}
    out["general"] = dict(out["planning"])
    return out


def fact_sheet(context: str, unavailable: list[str]) -> str:
    """Every model the person can run, with what the judge checks picks against:
    the scorer's own scores at each effort, the AA Index, the platforms and
    their dials, and the frontier the ladder is read from."""
    catalog = _cost._load_catalog()
    bench = _bench()
    by_id = {m["id"]: m for m in catalog["models"]}
    pool: dict[str, dict[str, Any]] = {}
    for category in scoring.CATEGORIES:
        ranking = scoring.rank(
            scoring.Task(category, "medium"),
            context,
            unavailable_models=unavailable,
            effort_aware=False,
        )
        for c in ranking.candidates:
            entry = pool.setdefault(
                c.model_name,
                {"id": c.model_id, "maker": c.provider, "price": c.blended_price_usd, "on": {}},
            )
            dial = scoring.native_levels(c.platform_id, c.model_id, catalog=catalog)
            funding = "funded, $0 extra" if c.funding in ("subscription", "local") else c.funding
            entry["on"][c.platform_name] = f"{funding}; dial: " + (
                " / ".join(dial) if dial else "none"
            )
    lines = [
        "Models this person can run. Price is the list price blended per 1M tokens. Scores "
        "are the scorer's 0-100 quality per category (catalog letter S > A > B > C > D in "
        "brackets) at each effort AA measured, lowest effort first; `general` is the "
        "planning measure, read from the AA Intelligence Index.",
    ]
    for name, e in sorted(pool.items(), key=lambda kv: (kv[1]["price"], kv[0])):
        model = by_id.get(e["id"], {"id": e["id"]})
        tiers = model.get("tiers", {})
        scores = model_scores(model, catalog, bench)
        levels = list(scores["general"])
        aa = [scoring._evidence(bench, e["id"], scoring.FRONTIER_INDEX, lv) for lv in levels]
        effort_text = "/".join(lv or "headline" for lv in levels)
        platforms = "; ".join(f"{p} ({how})" for p, how in sorted(e["on"].items()))
        lines.append(f"- {name} ({e['maker']}), ${e['price']:.2f}/1M; runs on {platforms}")
        lines.append(
            f"    efforts {effort_text}: AA Index "
            + "/".join("-" if v is None else f"{v:g}" for v in aa)
        )
        for category in ("general", *scoring.CATEGORIES):
            letter = "" if category == "general" else f" ({tiers.get(category, '-')})"
            values = "/".join(f"{v:.0f}" for v in scores[category].values())
            lines.append(f"    {category}{letter}: {values}")
    # The frontier the rungs are read from: each model at every effort AA
    # measured, priced by its effort. A task may use only the efforts its
    # complexity allows, so each row reads part of this list.
    points: dict[tuple[str, str | None], scoring.FrontierPoint] = {}
    for lad in scoring.ladder_table(context, unavailable_models=unavailable).values():
        for pt in lad.points:
            points.setdefault((pt.candidate.model_name, pt.candidate.evidence_level), pt)
    if points:
        ordered = sorted(points.values(), key=lambda pt: (pt.price_usd, -(pt.aa_index or 0)))
        lines.append(
            "Frontier points, cheapest first (a model at an effort, priced by that effort): "
            + " < ".join(
                f"{pt.candidate.model_name} {pt.candidate.evidence_level or ''} "
                f"(${pt.price_usd:.2f}, AA {pt.aa_index:g})"
                for pt in ordered
                if pt.aa_index is not None
            )
        )
    lines.append(
        "Bars: Low 30, Medium 50, High 70, novel 85. Effort ceilings: a Low task runs at "
        "medium effort or below, Medium at high or below, High at xhigh or below."
    )
    return "\n".join(lines)


def system_prompt(context: str, unavailable: list[str]) -> str:
    return f"{RUBRIC}\n<fact-sheet>\n{fact_sheet(context, unavailable)}\n</fact-sheet>\n"


def _settings_text(settings: dict[str, Any]) -> str:
    keep = {k: v for k, v in settings.items() if k not in ("rationale", "budget_priority")}
    return ", ".join(f"{k} {v}" for k, v in keep.items()) or "no settings"


def _rationale_text(pick: dict[str, Any]) -> str:
    sections = pick.get("rationale_sections")
    if isinstance(sections, dict) and sections:
        return " ".join(f"{k.upper()}: {v}" for k, v in sections.items())
    return str(pick.get("rationale") or "")


def render_ladder(task: str, ladder: list[dict[str, Any]], primary: str = "balanced") -> str:
    by_tier = {PRIORITY_TO_TIER.get(str(p.get("priority"))): p for p in ladder}
    lines = [f"<task>\n{task}\n</task>", "<recommendation>"]
    for tier in ("cost", "balanced", "quality"):
        p = by_tier.get(tier) or {}
        raw = p.get("settings")
        settings: dict[str, Any] = raw if isinstance(raw, dict) else {}
        backup = p.get("backup") if isinstance(p.get("backup"), dict) else None
        backup_text = (
            f"{backup.get('model')} @ {backup.get('platform') or 'no platform'} "
            f"({_settings_text(backup['settings'] if isinstance(backup.get('settings'), dict) else {})})"
            if backup
            else "none"
        )
        lines.append(
            f"{TIER_LABEL[tier]}: {p.get('model')} @ {p.get('platform')} ({_settings_text(settings)}); "
            f"backup {backup_text}"
        )
        lines.append(f"  {_rationale_text(p)}")
    lines.append("</recommendation>")
    lines.append(f"The person's priority, the pick shown first: {TIER_LABEL[primary]}.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Controls
# --------------------------------------------------------------------------- #


@dataclass
class Item:
    """One ladder for the judge: a probe's row, or a control with its expected verdict."""

    key: str
    task: str
    ladder: list[dict[str, Any]]
    expect: bool | None = None  # None: a real row; True/False: a control
    note: str = ""


def _settings_for(platform: str | None, level: str | None) -> dict[str, str]:
    if not level:
        return {}
    return (
        {"intelligence": level} if platform and platform.startswith("Codex") else {"effort": level}
    )


def gold_ladder_rows(gold: scoring.Ladder, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """The gold row as the app would show it, with a factual rationale written
    from the scorer's own data (accurate by construction)."""
    by_id = {m["id"]: m for m in catalog["models"]}
    bench = _bench()
    out: list[dict[str, Any]] = []
    for priority, tier in PRIORITY_TO_TIER.items():
        rung = gold.rungs[tier]
        c = rung.candidate
        letter = by_id.get(c.model_id, {}).get("tiers", {}).get(gold.task.category, "?")
        # The headline figure, the one the fact sheet shows.
        aa = headline_aa(bench, c.model_id)
        backup = rung.backup
        out.append(
            {
                "priority": priority,
                "model": c.model_name,
                "platform": c.platform_name,
                "settings": _settings_for(c.platform_name, rung.level),
                "backup": (
                    {
                        "model": backup.candidate.model_name,
                        "platform": backup.candidate.platform_name,
                        "settings": _settings_for(backup.candidate.platform_name, backup.level),
                    }
                    if backup
                    else None
                ),
                "rationale_sections": {
                    "task": f"{gold.task.category} work at {gold.task.complexity} complexity.",
                    "pick": (
                        f"{c.model_name} rates {letter} for {gold.task.category} work, "
                        f"AA Intelligence Index {aa}, ${c.blended_price_usd:.2f}/1M list, "
                        f"on {c.platform_name}."
                    ),
                    "effort": f"{rung.level} suits {gold.task.complexity} complexity.",
                },
                "conversation": "New",
            }
        )
    return out


def _copy(ladder: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = json.loads(json.dumps(ladder))
    return copied


def _pick(ladder: list[dict[str, Any]], priority: str) -> dict[str, Any]:
    return next(p for p in ladder if p.get("priority") == priority)


def controls(
    probes: list[dict[str, Any]],
    table: dict[str, scoring.Ladder],
    context: str,
    unavailable: list[str],
    catalog: dict[str, Any],
) -> list[Item]:
    """Three ladders the judge must reject and two it must accept, built from
    the gold rows so they hold whatever today's catalog is."""
    gold = {p["id"]: (p, table[gold_key(p)]) for p in probes if gold_key(p) in table}
    items: list[Item] = []

    # Demotion: a high-complexity task whose QUALITY falls to the cheapest
    # frontier model at its lowest level.
    for probe, lad in gold.values():
        cheapest = lad.frontier[0].candidate if lad.frontier else None
        if (
            probe["complexity"] == "high"
            and cheapest is not None
            and lad.rungs["quality"].candidate.model_name != cheapest.model_name
        ):
            ladder = gold_ladder_rows(lad, catalog)
            q = _pick(ladder, "best")
            dial = scoring.native_levels(cheapest.platform_id, cheapest.model_id, catalog=catalog)
            q.update(
                model=cheapest.model_name,
                platform=cheapest.platform_name,
                settings=_settings_for(cheapest.platform_name, dial[0] if dial else None),
            )
            q["rationale_sections"]["pick"] = f"{cheapest.model_name} keeps the cost down."
            items.append(Item(f"control:demote:{probe['id']}", probe["task"], ladder, False, "J2"))
            break

    # Leak: the rationale writes the story instead of explaining the pick.
    creative = gold.get("creative")
    if creative:
        ladder = gold_ladder_rows(creative[1], catalog)
        for p in ladder:
            p["rationale_sections"] = dict(LEAKED_RATIONALE)
        items.append(Item("control:leak:creative", creative[0]["task"], ladder, False, "J6"))

    # An Anthropic flagship on the Cost rung where another maker's cheap model
    # is adequate: catches a judge that favours its own maker.
    flagship = max(
        (
            c
            for c in scoring.rank(
                scoring.Task("coding", "high"),
                context,
                unavailable_models=unavailable,
                effort_aware=False,
            ).candidates
            if c.provider == "anthropic"
        ),
        key=lambda c: c.blended_price_usd,
        default=None,
    )
    for probe, lad in gold.values():
        cost_rung = lad.rungs["cost"].candidate
        if (
            flagship is not None
            and probe["complexity"] == "low"
            and cost_rung.provider != "anthropic"
            and cost_rung.blended_price_usd < flagship.blended_price_usd
        ):
            # The only flaw is the price: the flagship runs at its lowest level
            # and the backup is the adequate cheap model it displaced.
            ladder = gold_ladder_rows(lad, catalog)
            c = _pick(ladder, "cheap")
            dial = scoring.native_levels(flagship.platform_id, flagship.model_id, catalog=catalog)
            low = dial[0] if dial else None
            c.update(
                model=flagship.model_name,
                platform=flagship.platform_name,
                settings=_settings_for(flagship.platform_name, low),
                backup={
                    "model": cost_rung.model_name,
                    "platform": cost_rung.platform_name,
                    "settings": _settings_for(cost_rung.platform_name, lad.rungs["cost"].level),
                },
            )
            c["rationale_sections"]["pick"] = f"{flagship.model_name} is the strongest choice."
            c["rationale_sections"]["effort"] = f"{low} suits {lad.task.complexity} complexity."
            items.append(Item(f"control:maker:{probe['id']}", probe["task"], ladder, False, "J3"))
            break

    # Two gold rows that meet J2 by the scorer's own numbers (QUALITY within 5
    # points of the best runnable score in the category), preferring the rows
    # with the most picks from makers other than Anthropic, as they stand.
    def meets_j2(lad: scoring.Ladder) -> bool:
        ranking = scoring.rank(
            lad.task, context, unavailable_models=unavailable, effort_aware=False
        )
        scores = [(c.model_name, c.quality) for c in ranking.candidates]
        best = max((q for _, q in scores), default=0.0)
        name = lad.rungs["quality"].candidate.model_name
        return max((q for m, q in scores if m == name), default=0.0) >= best - 5.0

    def others(lad: scoring.Ladder) -> int:
        return sum(r.candidate.provider != "anthropic" for r in lad.rungs.values())

    accepted = sorted(
        ((probe, lad) for probe, lad in gold.values() if meets_j2(lad)),
        key=lambda pl: -others(pl[1]),
    )
    for probe, lad in accepted[:2]:
        items.append(
            Item(f"control:gold:{probe['id']}", probe["task"], gold_ladder_rows(lad, catalog), True)
        )
    return items


# --------------------------------------------------------------------------- #
# Running the judge
# --------------------------------------------------------------------------- #

JudgeFn = Callable[[str, str], dict[str, Any]]


def claude_judge(system_file: str, model: str, timeout: int = 300) -> JudgeFn:
    """A judge that runs `claude -p` with no tools and structured output."""

    def run(_system: str, message: str) -> dict[str, Any]:
        cmd = [
            "claude",
            "-p",
            "--safe-mode",
            "--model",
            model,
            "--tools",
            "",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(JUDGE_SCHEMA),
            "--system-prompt-file",
            system_file,
        ]
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        last = ""
        for _ in range(2):
            proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv, no shell
                cmd, input=message, capture_output=True, text=True, timeout=timeout, env=env
            )
            if proc.returncode == 0:
                out: dict[str, Any] = json.loads(proc.stdout)
                if out.get("structured_output"):
                    return out
                last = str(out.get("result"))[:200]
            else:
                last = (proc.stderr or proc.stdout)[-300:]
        raise RuntimeError(f"judge call failed: {last}")

    return run


@dataclass
class Verdict:
    key: str
    accepted: bool | None  # None: not judged
    blockers: list[str] = field(default_factory=list)
    criteria: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    cost_usd: float = 0.0
    error: str = ""


def verdict_from(key: str, out: dict[str, Any]) -> Verdict:
    """The code's verdict from the judge's grades: accepted unless a criterion
    fails as a blocker. A grade set that is incomplete, carries placeholder
    evidence, or contradicts the judge's own overall ``accept`` is no verdict."""
    graded = out.get("structured_output") or {}
    criteria = [c for c in graded.get("criteria", []) if isinstance(c, dict)]
    ids = [str(c.get("id")) for c in criteria]
    if sorted(ids) != sorted(CRITERIA):
        return Verdict(key, None, error=f"criteria {ids} are not {list(CRITERIA)} once each")
    thin = [
        c["id"] for c in criteria if len(str(c.get("evidence", "")).strip()) < MIN_EVIDENCE_CHARS
    ]
    if thin:
        return Verdict(key, None, criteria=criteria, error=f"placeholder evidence on {thin}")
    blockers = [
        f"{c['id']}: {c.get('evidence', '')}"
        for c in criteria
        if not c.get("pass") and c.get("severity") == "blocker"
    ]
    if graded.get("accept") is not (not blockers):
        return Verdict(
            key, None, blockers, criteria, error="overall accept contradicts the criteria"
        )
    return Verdict(
        key,
        not blockers,
        blockers,
        criteria,
        str(graded.get("summary", "")),
        float(out.get("total_cost_usd") or 0.0),
    )


def judge_all(
    items: list[Item], judge: JudgeFn, system: str, *, max_calls: int, concurrency: int
) -> dict[str, Verdict]:
    """One verdict per item, re-asking once when a verdict is unusable. Every
    call, retries included, counts against ``max_calls``; an item the cap
    leaves out stays unjudged (and so fails B6)."""
    budget = [max_calls]
    lock = threading.Lock()

    def take() -> bool:
        with lock:
            if budget[0] <= 0:
                return False
            budget[0] -= 1
            return True

    def one(item: Item) -> Verdict:
        verdict = Verdict(item.key, None, error=f"over the {max_calls}-call cap")
        for _ in range(2):
            if not take():
                return verdict
            try:
                verdict = verdict_from(
                    item.key, judge(system, render_ladder(item.task, item.ladder))
                )
            except Exception as exc:  # noqa: BLE001 - an unjudged row fails B6, it never raises
                verdict = Verdict(item.key, None, error=str(exc)[:300])
            if verdict.accepted is not None:
                return verdict
        return verdict

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        verdicts = list(pool.map(one, items))
    return {v.key: v for v in verdicts}


# --------------------------------------------------------------------------- #
# Scorecard
# --------------------------------------------------------------------------- #


@dataclass
class Check:
    id: str
    bar: str
    passed: bool
    detail: str


def b2_check(results: dict[str, list[str]], expected: int) -> Check:
    failing = {pid: p for pid, p in results.items() if p}
    passed = len(results) - len(failing)
    rate = passed / expected if expected else 0.0
    detail = f"{passed}/{expected}" + (
        " (" + "; ".join(f"{pid}: {', '.join(p)}" for pid, p in failing.items()) + ")"
        if failing
        else ""
    )
    return Check("pick-spec-correct", "B2", len(results) == expected and rate >= B2_BAR, detail)


def b6_check(verdicts: dict[str, Verdict], items: list[Item], engine_makers: set[str]) -> Check:
    rows = [i for i in items if i.expect is None]
    ctrl = [i for i in items if i.expect is not None]
    if JUDGE_MAKER in engine_makers:
        return Check("judge-accept", "B6", False, f"self-judging: an engine row is {JUDGE_MAKER}'s")
    wrong = [
        i.key
        for i in ctrl
        if verdicts[i.key].accepted is None or verdicts[i.key].accepted != i.expect
    ]
    unjudged = [i.key for i in rows if verdicts[i.key].accepted is None]
    accepted = [i.key for i in rows if verdicts[i.key].accepted]
    rejected = [i.key for i in rows if verdicts[i.key].accepted is False]
    rate = len(accepted) / len(rows) if rows else 0.0
    detail = (
        f"{len(accepted)}/{len(rows)} accepted ({rate:.0%}); controls "
        f"{len(ctrl) - len(wrong)}/{len(ctrl)}"
    )
    if rejected:
        detail += "; rejected " + ", ".join(
            f"{k}[{','.join(b.split(':')[0] for b in verdicts[k].blockers)}]" for k in rejected
        )
    if unjudged:
        detail += f"; unjudged {', '.join(unjudged)}"
    if wrong:
        detail += f"; JUDGE INVALID (misgraded {', '.join(wrong)})"
    passed = bool(rows) and not wrong and not unjudged and rate >= B6_BAR
    return Check("judge-accept", "B6", passed, detail)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", required=True, type=pathlib.Path, help="soak JSONL")
    ap.add_argument("--out", default=DEFAULT_OUT, type=pathlib.Path)
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL", JUDGE_MODEL))
    ap.add_argument("--max-calls", type=int, default=MAX_JUDGE_CALLS)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--no-judge", action="store_true", help="score B2 only")
    ap.add_argument("--dry-run", action="store_true", help="print the judge prompts, call nothing")
    args = ap.parse_args(argv)

    if not args.rows.exists():
        print(f"no soak rows at {args.rows}", file=sys.stderr)
        return 2
    probes = load_probes()
    rows = judged_rows(load_rows(args.rows))
    context = bundled_context()
    unavailable = unavailable_ids()
    catalog = _cost._load_catalog()
    table = scoring.ladder_table(context, unavailable_models=unavailable)

    b2: dict[str, list[str]] = {}
    for probe in probes:
        row = rows.get(probe["id"])
        if row is not None:
            b2[probe["id"]] = b2_probe(app_picks(row), probe, table, context, unavailable)
    checks = [b2_check(b2, len(probes))]

    items = [Item(p["id"], p["task"], rows[p["id"]]["ladder"]) for p in probes if p["id"] in rows]
    items += controls(probes, table, context, unavailable, catalog)
    system = system_prompt(context, unavailable)
    verdicts: dict[str, Verdict] = {}
    if args.dry_run:
        print(system)
        for item in items:
            print(
                f"\n=== {item.key} (expect {item.expect}) ===\n{render_ladder(item.task, item.ladder)}"
            )
        return 0
    if not args.no_judge:
        makers = {str((r.get("engine") or {}).get("maker")) for r in rows.values()}
        missing = [p["id"] for p in probes if p["id"] not in rows]
        items += [Item(pid, "", []) for pid in missing]  # unanswered probes stay unjudged
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(system)
        try:
            judge = claude_judge(fh.name, args.model)
            answered = [i for i in items if i.ladder]
            verdicts = judge_all(
                answered, judge, system, max_calls=args.max_calls, concurrency=args.concurrency
            )
            verdicts.update(
                {i.key: Verdict(i.key, None, error="no answer") for i in items if not i.ladder}
            )
        finally:
            os.unlink(fh.name)
        checks.append(b6_check(verdicts, items, makers))

    spent = sum(v.cost_usd for v in verdicts.values())
    args.out.write_text(
        json.dumps(
            {
                "roadmodel_version": _installed_version(),
                "judge_model": args.model,
                "judge_list_cost_usd": round(spent, 4),
                "checks": [c.__dict__ for c in checks],
                "b2": b2,
                "verdicts": {k: v.__dict__ for k, v in verdicts.items()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n=== JUDGE SCORECARD (roadmodel {_installed_version()}, judge {args.model}) ===")
    for c in checks:
        print(
            f"  [{'PASS ' if c.passed else 'FAIL '}] {c.bar.ljust(4)} {c.id.ljust(22)} {c.detail}"
        )
    for key, v in sorted(verdicts.items()):
        if v.accepted is False or v.error:
            reason = v.error or " | ".join(v.blockers)
            print(f"    {key}: {_clip(reason)}")
    if verdicts:
        print(f"  judge list-equivalent ${spent:.2f} on the subscription token (no API cash)")
    failed = [c for c in checks if not c.passed]
    print(
        f"JUDGE_RESULT: {'PASS' if not failed else 'FAIL'} ({len(checks) - len(failed)}/{len(checks)} checks)"
    )
    return 0 if not failed else 1


def _clip(text: str, n: int = 240) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _installed_version() -> str:
    try:
        from importlib.metadata import version

        return version("roadmodel")
    except Exception:  # noqa: BLE001  # nosec B110 - a label only
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
