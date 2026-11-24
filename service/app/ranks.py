# service/app/ranks.py
"""Each pick ranked three deep, as a roadmap's Settings rank it.

/recommend's Cost / Balanced / Quality picks are read off the caller's own
cost/quality frontier (``roadmodel.scoring.ladder``). A roadmap's Settings show
each of those picks with a Runner-up and a Backup from two other makers, and
every option with the level it runs at, its AA Intelligence Index there and
its price there (``scoring.settings_ladder``). The page shows a pick the same
way, so this module reads the same three ranks for a request: on the pools as
they stand and on every platform the caller reaches, the ladder the picks
themselves are read from. With them come the settings that ladder weighed
(each model the caller can run at each effort the task may run, with its AA
Index and price there), so the page's chart draws the frontier the picks were
read from and not one of its own.

``scoring.ranked_columns`` computes both (roadmodel > 0.2.118). The service
installs roadmodel from PyPI, so until that release is the floor
``_ranked_0_2_118`` reads them from the same functions the package uses;
tests/test_ranks.py holds the two to one answer.

Ranks are an addition to an answer, never a condition of it: every function
here returns None in place of raising.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from roadmodel import scoring  # type: ignore[import-untyped]

from .models import LadderPoint, LadderTask, RankedOption, Ranks

logger = logging.getLogger(__name__)

# A ladder-table key (scoring.table_key): `<category>/<complexity>[/novel]`.
_COMPLEXITIES = ("low", "medium", "high")


def task_from_key(key: object) -> scoring.Task | None:
    """The task a ladder-table key names (``coding/high``,
    ``planning/high/novel``), or None for anything else."""
    if not isinstance(key, str):
        return None
    parts = key.split("/")
    if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "novel"):
        return None
    category, complexity = parts[0], parts[1]
    if category not in scoring.CATEGORY_EVIDENCE or complexity not in _COMPLEXITIES:
        return None
    return scoring.Task(category, complexity, len(parts) == 3)


def ladder_task(task: scoring.Task) -> LadderTask:
    return LadderTask(category=task.category, complexity=task.complexity, novel=task.novel)


class Read(NamedTuple):
    """What a request's ladder holds beyond its three picks: each tier's Pick
    with its ``runner_up`` and ``backup`` (the package's option dicts), and
    every setting the ladder weighed (``scoring.ladder_points``)."""

    columns: dict[str, dict[str, Any]]
    points: list[dict[str, Any]]


def _ranked_0_2_118(task: scoring.Task, text: str, unavailable: list[str]) -> Read | None:
    """``scoring.ranked_columns`` for roadmodel 0.2.118, which ranks a
    roadmap's Settings this way (``settings_ladder``) but only with every pool
    at headroom, and has no ``ladder_points``: the same loop and the same
    reading of each setting, over the same package functions, on the pools as
    they stand. Delete with the floor bump past 0.2.118."""
    cat = scoring._cost._load_catalog()
    bench = scoring.with_unmeasured(scoring._load_benchmarks(), cat)
    seen: dict[frozenset[str], Any] = {}

    def read(without: list[str]) -> Any:
        key = frozenset([*unavailable, *without])
        if key not in seen:
            seen[key] = scoring.ladder(
                task, text, unavailable_models=sorted(key), catalog=cat, benchmarks=bench
            )
        return seen[key]

    lad = read([])
    if lad is None:
        return None
    by_maker: dict[str, set[str]] = {}
    for m in cat.get("models", []):
        mid = str(m.get("id", ""))
        maker = scoring._cost.model_provider(mid, cat) or str(m.get("provider", "unknown"))
        by_maker.setdefault(maker, set()).add(mid)
    for entry in scoring._configurations.configurations():
        for method in cat.get("access_methods", []):
            if method.get("id") == entry["platform_id"]:
                by_maker.setdefault(str(method["provider"]), set()).add(entry["id"])
                break

    # A caller who funds something is ranked their own models only: with
    # their funded makers off the table the ladder reads the whole catalog,
    # as it does for a caller who funds nothing.
    funds = any(c.funding != "unfunded" for c in lad.settings)
    columns: dict[str, dict[str, Any]] = {}
    for tier in scoring.LADDER_TIERS:
        rung = lad.rungs[tier]
        pick = scoring._option(rung.candidate, rung.level, bench, cat)
        ranked: list[dict[str, Any] | None] = [pick]
        makers = [rung.candidate.provider]
        while len(ranked) < 3:
            rest = read(sorted(m for maker in makers for m in by_maker.get(maker, ())))
            nxt = None if rest is None else rest.rungs[tier]
            if (
                nxt is None
                or nxt.candidate.provider in makers
                or (funds and nxt.candidate.funding == "unfunded")
            ):
                break
            ranked.append(scoring._option(nxt.candidate, nxt.level, bench, cat))
            makers.append(nxt.candidate.provider)
        steps = 1
        while len(ranked) < 3:
            lower = scoring._step_down(rung.candidate, rung.level, steps, cat)
            ranked.append(
                None
                if lower is None
                else scoring._option(rung.candidate, lower, bench, cat, stepped_down=True)
            )
            steps += 1
        columns[tier] = {**pick, "runner_up": ranked[1], "backup": ranked[2]}
    points: list[dict[str, Any]] = []
    for c in lad.settings:
        aa = scoring._candidate_aa(c, bench)
        if aa is None:
            continue
        points.append(
            {
                "model_id": c.model_id,
                "platform_id": c.platform_id,
                "effort": c.evidence_level,
                "aa_index": round(aa + c.aa_estimate_penalty, 1),
                "margin": c.aa_estimate_penalty,
                "price_usd_per_1m": scoring.frontier_price(c),
                "adequate": c.requirement_penalty == 0,
                "estimated": c.aa_estimated or c.aa_inherited_from is not None,
            }
        )
    return Read(columns, points)


def read(task: scoring.Task, text: str, unavailable_models: list[str] | None = None) -> Read | None:
    """The ranked columns and the weighed settings for ``task`` over the
    user-context ``text`` (the table format the scorer reads). None when the
    context leaves no frontier, or on any failure."""
    unavailable = list(unavailable_models or [])
    try:
        ranked = getattr(scoring, "ranked_columns", None)
        if ranked is None:
            return _ranked_0_2_118(task, text, unavailable)
        out = ranked(task, text, unavailable_models=unavailable)
        return None if out is None else Read(dict(out.columns), list(out.points))
    except Exception:  # noqa: BLE001 - ranks are an addition, never fatal
        logger.warning("ranked ladder read failed (non-fatal)")
        return None


def columns(
    task: scoring.Task, text: str, unavailable_models: list[str] | None = None
) -> dict[str, dict[str, Any]] | None:
    """:func:`read`'s columns alone."""
    got = read(task, text, unavailable_models)
    return None if got is None else got.columns


# A page plots these; a frontier over a catalog many times today's would
# still be a few hundred settings.
MAX_POINTS = 600


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _point(row: object) -> LadderPoint | None:
    """One weighed setting as the response carries it; None for a row that
    does not hold a model, an index and a price."""
    if not isinstance(row, dict):
        return None
    model_id, aa, price = (
        row.get("model_id"),
        _number(row.get("aa_index")),
        _number(row.get("price_usd_per_1m")),
    )
    if not isinstance(model_id, str) or not model_id or aa is None or price is None:
        return None
    effort = row.get("effort")
    return LadderPoint(
        model_id=model_id,
        platform_id=str(row.get("platform_id") or ""),
        effort=effort if isinstance(effort, str) else None,
        aa_index=aa,
        margin=max(0.0, _number(row.get("margin")) or 0.0),
        price_usd_per_1m=price,
        adequate=row.get("adequate") is not False,
        estimated=row.get("estimated") is True,
    )


def points(raw: list[dict[str, Any]] | None) -> list[LadderPoint] | None:
    """The weighed settings as the response carries them, or None when there
    are none to carry. A setting that does not fit the response's shape is
    left out."""
    out = [p for p in map(_point, (raw or [])[:MAX_POINTS]) if p is not None]
    return out or None


class Placed(NamedTuple):
    """A ladder response's additions: what the task was read as, each tier's
    ranked column, and the weighed settings."""

    task: LadderTask | None
    columns: dict[str, dict[str, Any]]
    points: list[LadderPoint] | None


def placed(guard: object, text: str, unavailable_models: list[str] | None) -> Placed:
    """What a ladder response adds to its picks. ``guard`` is the package's
    report on the response: it names the frontier-table row the picks were
    copied from, and the row is read again here over the same user-context
    ``text`` and the same unavailable models, less the models too small for
    the task's material when the package refit the row to it. Nothing for a
    response the frontier table did not place. Never raises."""
    if not isinstance(guard, dict) or guard.get("mode") != "frontier":
        return Placed(None, {}, None)
    task = task_from_key(guard.get("classification"))
    if task is None:
        return Placed(None, {}, None)
    try:
        unavailable = list(unavailable_models or [])
        fit = guard.get("context")
        if isinstance(fit, dict) and fit.get("excluded") and fit.get("fits", True):
            unavailable += scoring.too_small_for(int(fit["input_tokens"]))
        got = read(task, text, unavailable)
        if got is None:
            return Placed(ladder_task(task), {}, None)
        return Placed(ladder_task(task), got.columns, points(got.points))
    except Exception:  # noqa: BLE001 - ranks are an addition, never fatal
        logger.warning("ranked ladder failed (non-fatal)")
        return Placed(ladder_task(task), {}, None)


def _option(raw: object) -> RankedOption | None:
    """One ranked option as the response carries it, from the package's
    option dict; None for a rank the pool cannot fill."""
    if not isinstance(raw, dict):
        return None
    price = raw.get("price_usd_per_1m")
    aa = raw.get("aa_index")
    return RankedOption(
        model=str(raw["model"]),
        model_id=str(raw["model_id"]),
        platform=str(raw["platform"]),
        platform_id=str(raw["platform_id"]),
        effort=str(raw["effort"]),
        level=str(raw["level_cell"]),
        aa_index=float(aa) if isinstance(aa, (int, float)) else None,
        aa_estimated=bool(raw.get("aa_estimated")),
        price_usd_per_1m=float(price) if isinstance(price, (int, float)) else None,
        price_measured=(
            bool(raw["price_measured"]) if raw.get("price_measured") is not None else None
        ),
        stepped_down=bool(raw.get("stepped_down")),
        ultracode=str(raw.get("ultracode") or "").lower() == "on",
    )


def for_pick(column: dict[str, Any] | None, model: str, platform: str) -> Ranks | None:
    """``column``'s three ranks for the pick the response carries (its catalog
    display name, and its platform as the engine wrote it: a name or an id),
    or None when the column's Pick is another model or platform: a guard
    replaced the row's pick, and ranks read around the row's would describe
    the wrong one."""
    if not column:
        return None
    try:
        pick = _option(column)
        if (
            pick is None
            or pick.model.lower() != model.strip().lower()
            or platform.strip().lower() not in {pick.platform.lower(), pick.platform_id.lower()}
        ):
            return None
        return Ranks(
            pick=pick,
            runner_up=_option(column.get("runner_up")),
            backup=_option(column.get("backup")),
        )
    except Exception:  # noqa: BLE001 - ranks are an addition, never fatal
        logger.warning("ranked option shaping failed (non-fatal)")
        return None
