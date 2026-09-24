"""The catalog's lifecycle rule (update/supersede.py) and what honours it.

A model is superseded when another model from the same maker costs the same or
less (blended), scores higher on the AA Intelligence Index, is rated at least
as high in every category, and is offered by every access method that offers
it. It is tagged at once, dropped from the recommender's candidates while the
successor is available, and retired 30 days later: it then leaves
docs/catalog.json (the website, the MCP catalog) but stays in the selector as
the record of what replaced it.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import supersede  # noqa: E402

TODAY = dt.date(2026, 9, 24)
CATS = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")


def _model(
    mid: str, price_in: float, price_out: float, aa: float | None, letter: str = "A", **tier: str
) -> str:
    ratings = " ".join(f'tier-{c}="{tier.get(c.replace("-", "_"), letter)}"' for c in CATS)
    bench = f"AA Intelligence Index {aa}" if aa is not None else "none"
    return (
        f'<model id="{mid}" name="{mid.title()}"\n'
        f'       input-price-per-1m="${price_in:.2f}" output-price-per-1m="${price_out:.2f}"\n'
        f'       jurisdiction="us" {ratings}\n'
        f'       headline-benchmarks="{bench}" pricing-notes="" best-for=""/>'
    )


def _selector(models: list[str], methods: dict[str, tuple[str, list[str]]]) -> str:
    method_xml = "\n".join(
        f'<method id="{mid}" name="{mid}" provider="{prov}" supports-models="{",".join(ids)}"/>'
        for mid, (prov, ids) in methods.items()
    )
    return (
        '<model-options>\n<tier cost="high">\n'
        + "\n".join(models)
        + "\n</tier>\n</model-options>\n<access-methods>\n"
        + method_xml
        + "\n</access-methods>\n"
    )


BASE_METHODS = {
    "maker-api": ("maker", ["old", "new"]),
    "other-api": ("other", ["rival"]),
    "cursor": ("cursor", ["old", "new", "rival"]),
}


def _succ(
    models: list[str], methods: dict[str, tuple[str, list[str]]] = BASE_METHODS
) -> dict[str, str]:
    text = _selector(models, methods)
    return supersede.successors(text, supersede.parse_models(text, {}))


def test_a_newer_model_that_wins_on_every_count_supersedes() -> None:
    assert _succ([_model("old", 5, 25, 40), _model("new", 4, 20, 50)]) == {"old": "new"}


@pytest.mark.parametrize(
    ("new", "why"),
    [
        (_model("new", 6, 30, 50), "costs more"),
        (_model("new", 4, 20, 40), "scores the same"),
        (_model("new", 4, 20, 50, speed="D"), "rates lower in a category"),
        (_model("new", 4, 20, None), "has no AA Index"),
    ],
)
def test_no_supersession_unless_every_condition_holds(new: str, why: str) -> None:
    assert _succ([_model("old", 5, 25, 40, speed="C"), new]) == {}, why


def test_the_successor_must_run_everywhere_the_old_model_does() -> None:
    methods = dict(BASE_METHODS, only_old=("maker", ["old"]))
    assert _succ([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], methods) == {}


def test_only_the_same_maker_supersedes() -> None:
    assert _succ([_model("old", 5, 25, 40), _model("rival", 1, 2, 60)]) == {}


def _plan(
    text: str, today: dt.date, base: dict[str, supersede.Tags] | None = None
) -> supersede.Plan:
    return supersede.plan(text, {}, today, base)


def test_the_clock_starts_on_first_supersession_and_retires_30_days_on() -> None:
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    first = _plan(text, TODAY)
    assert first.newly == ["old"] and first.tags["old"] == supersede.Tags("new", "2026-09-24")
    tagged = supersede.apply(text, first)
    assert 'superseded-by="new" superseded-on="2026-09-24"' in tagged
    # The next day nothing moves; the date is kept.
    assert _plan(tagged, TODAY + dt.timedelta(days=1)).newly == []
    assert supersede.apply(tagged, _plan(tagged, TODAY + dt.timedelta(days=1))) == tagged
    # Thirty days on it retires, dated that day.
    later = TODAY + dt.timedelta(days=supersede.RETIRE_AFTER_DAYS)
    retire = _plan(tagged, later)
    assert retire.retired == ["old"] and retire.tags["old"].retired == later.isoformat()


def test_retirement_is_sticky_and_an_unretired_tag_clears() -> None:
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    tagged = supersede.apply(text, _plan(text, TODAY))
    # The successor's price rises before retirement: the tag clears.
    pricier = tagged.replace(
        'input-price-per-1m="$4.00" output-price-per-1m="$20.00"',
        'input-price-per-1m="$9.00" output-price-per-1m="$40.00"',
    )
    cleared = _plan(pricier, TODAY + dt.timedelta(days=5))
    assert cleared.cleared == ["old"] and "old" not in cleared.tags
    assert "superseded-by" not in supersede.apply(pricier, cleared)
    # Once retired, it stays retired whatever changes.
    retired = supersede.apply(tagged, _plan(tagged, TODAY + dt.timedelta(days=30)))
    pricier_after = retired.replace(
        'input-price-per-1m="$4.00" output-price-per-1m="$20.00"',
        'input-price-per-1m="$9.00" output-price-per-1m="$40.00"',
    )
    assert _plan(pricier_after, TODAY + dt.timedelta(days=40)).tags["old"].retired == "2026-10-24"


def test_a_tag_the_curation_pass_dropped_comes_back_with_its_date() -> None:
    text = _selector([_model("old", 5, 25, 40), _model("new", 4, 20, 50)], BASE_METHODS)
    committed = supersede.apply(text, _plan(text, TODAY))
    regenerated = text  # the curation pass re-emitted the element without its tags
    p = _plan(regenerated, TODAY + dt.timedelta(days=3), supersede.base_tags(committed))
    assert p.newly == [] and p.tags["old"].since == "2026-09-24"


def test_committed_tags_are_well_formed() -> None:
    """Stable invariants on the committed selector (not a re-run of the rule,
    which depends on the day's benchmarks): every tag names a real model,
    carries ISO dates, and a retirement comes 30 days or more after the tag."""
    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    models = {m.id: m for m in supersede.parse_models(text, {})}
    for m in models.values():
        if m.by is None:
            assert m.since is None and m.retired is None, m.id
            continue
        assert m.by in models and m.by != m.id, f"{m.id} superseded by unknown {m.by!r}"
        since = dt.date.fromisoformat(m.since or "")
        if m.retired:
            gap = (dt.date.fromisoformat(m.retired) - since).days
            assert gap >= supersede.RETIRE_AFTER_DAYS, m.id


def _load(name: str) -> ModuleType:
    return importlib.reload(importlib.import_module(name))


def test_the_catalog_drops_a_retired_model_and_dates_a_superseded_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = _load("build_catalog")
    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    tags = supersede.base_tags(text)
    live = sorted((k, v) for k, v in tags.items() if v.retired is None)
    if len(live) < 2:
        pytest.skip("the committed selector has too few superseded models to test with")
    victim, t = live[0]
    p = supersede.Plan(
        {**tags, victim: supersede.Tags(t.by, t.since, "2026-10-24")}, [], [], [victim]
    )
    selector = tmp_path / "model-selector.txt"
    selector.write_text(supersede.apply(text, p))
    monkeypatch.setattr(build, "SELECTOR_PATH", selector)
    catalog = build.build_catalog()
    ids = {m["id"] for m in catalog["models"]}
    assert victim not in ids
    assert all(victim not in m["supports_models"] for m in catalog["access_methods"])
    other = next(m for m in catalog["models"] if m["id"] == live[1][0])
    since = dt.date.fromisoformat(other["superseded_on"])
    assert other["retires_on"] == (since + dt.timedelta(days=build.RETIRE_AFTER_DAYS)).isoformat()


def test_the_recommender_never_sees_a_superseded_model_while_its_successor_is_available() -> None:
    from roadmodel import recommend

    text = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    live = sorted((k, v) for k, v in supersede.base_tags(text).items() if v.retired is None)
    if not live:
        pytest.skip("no superseded (unretired) model in the committed selector")
    old, t = live[0]
    element = re.compile(rf'<model\s+id="{re.escape(old)}"')
    kept = recommend._drop_superseded(text, None)
    assert not element.search(kept)
    assert all(old not in m.split(",") for m in re.findall(r'supports-models="([^"]*)"', kept))
    # Its successor benched at runtime: the superseded model is the fallback.
    fallback = recommend._drop_superseded(text, [t.by])
    assert element.search(fallback)
    # And an untagged model is untouched.
    untagged = next(m for m in supersede.parse_models(text, {}) if m.by is None)
    assert re.search(rf'<model\s+id="{re.escape(untagged.id)}"', kept)


def test_both_crons_run_the_rule() -> None:
    bench = (REPO_ROOT / ".github" / "workflows" / "update-benchmarks.yml").read_text()
    models = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    assert "python update/supersede.py --write" in bench
    assert "python update/supersede.py --write --base /tmp/base-selector.txt" in models
    prompt = (UPDATE_DIR / "prompt.md").read_text()
    assert "superseded-by" in prompt and "retired-on" in prompt
    assert json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())["models"]
