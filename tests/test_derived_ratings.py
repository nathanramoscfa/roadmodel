"""update/derive_ratings.py — the four measurable ratings as a function of data.

Pure tests over the banding, the derivation, the selector edit, and the
coding S-tier enumeration regeneration, plus the consistency gate: the
committed selector's tier-coding / tier-agentic / tier-long-context /
tier-knowledge must equal what the committed docs/benchmarks.json derives
(both crons run --write before opening a PR, so this only fails on a hand
edit — and the failure message says how to regenerate).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "derive_ratings", REPO_ROOT / "update" / "derive_ratings.py"
)
assert _spec is not None and _spec.loader is not None
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)


def _bench(**rows: dict[str, float | None]) -> dict[str, dict[str, object]]:
    return {cid: {"aa_name": cid, "evaluations": ev} for cid, ev in rows.items()}


SELECTOR = """<selector>
<model-options>
  <tier cost="low">
      <model id="cheap-one" name="Cheap One"
             input-price-per-1m="$0.5" output-price-per-1m="$2"
             tier-coding="B" tier-planning="B" tier-agentic="B"
             tier-multimodal="B" tier-long-context="B" tier-knowledge="B"
             tier-speed="S"
             best-for="placeholder" />
  </tier>
  <tier cost="very-high">
      <model id="leader" name="Leader"
             input-price-per-1m="$10" output-price-per-1m="$50"
             tier-coding="S" tier-planning="S" tier-agentic="S"
             tier-multimodal="S" tier-long-context="S" tier-knowledge="S"
             tier-speed="D"
             best-for="the frontier" />
      <model id="unmeasured" name="Unmeasured"
             input-price-per-1m="$5" output-price-per-1m="$25"
             tier-coding="S" tier-planning="A" tier-agentic="A"
             tier-multimodal="D" tier-long-context="B" tier-knowledge="B"
             tier-speed="B"
             best-for="no AA row" />
  </tier>
</model-options>
<selection-algorithm>
    Guardrails:
      - For PRIMARY = `multimodal`, only consider models with tier-multimodal
        of S or A (currently: stale-name at S).
      - For PRIMARY = `coding` at S-tier requirement, the candidate set is
        leader, unmeasured; cost tie-breaker favors
        unmeasured when the ratings are equivalent for the prompt.
      - Default to something else otherwise.
</selection-algorithm>
</selector>
"""


def test_bands_are_gap_to_leader() -> None:
    assert dr.letter_for_gap(0) == "S"
    assert dr.letter_for_gap(5) == "S"
    assert dr.letter_for_gap(5.1) == "A"
    assert dr.letter_for_gap(20) == "A"
    assert dr.letter_for_gap(20.1) == "B"
    assert dr.letter_for_gap(35) == "B"
    assert dr.letter_for_gap(35.1) == "C"
    assert dr.letter_for_gap(50) == "C"
    assert dr.letter_for_gap(50.1) == "D"


def test_derive_scales_fractions_to_points_and_skips_nulls() -> None:
    bench = _bench(
        leader={"hle": 0.60, "lcr": None, "scicode": 0.62, "terminalbench_v4_0": 0.9},
        cheap_one={"hle": 0.42, "lcr": 0.7, "scicode": 0.50, "terminalbench_v4_0": None},
    )
    d = dr.derive(bench)
    # HLE fraction → points: 0.42 → 42.0, gap 18 → A.
    assert d["knowledge"]["cheap_one"]["letter"] == "A"
    # Only cheap_one has LCR, so it IS the leader.
    assert d["long-context"] == {
        "cheap_one": {"value": 70.0, "leader": 70.0, "gap": 0.0, "letter": "S"}
    }
    assert "cheap_one" not in d["agentic"]
    # Coding's composite takes both of its parts: only the leader has them,
    # and a lone measured model leads its own composite.
    assert "cheap_one" not in d["coding"]
    assert d["coding"]["leader"]["value"] == 100.0 and d["coding"]["leader"]["letter"] == "S"


def test_the_coding_composite_is_the_mean_percentile_of_its_parts() -> None:
    bench = _bench(
        a={"scicode": 0.60, "terminalbench_v4_0": 0.10},
        b={"scicode": 0.50, "terminalbench_v4_0": 0.60},
        c={"scicode": 0.40, "terminalbench_v4_0": 0.30},
        d={"scicode": 0.70},  # one part only: no composite
    )
    out = dr.with_composites(bench)
    composite = {cid: row["evaluations"].get("coding_composite") for cid, row in out.items()}
    # SciCode ranks a > b > c, Terminal-Bench 4.0 ranks b > c > a.
    assert composite == {"a": 0.5, "b": 0.75, "c": 0.25, "d": None}
    assert "coding_composite" not in bench["a"]["evaluations"]  # a copy, not a mutation


def test_plan_apply_and_enumeration_round_trip() -> None:
    bench = _bench(
        leader={"hle": 0.60, "lcr": 0.9, "scicode": 0.62, "terminalbench_v4_0": 0.9},
        **{"cheap-one": {"hle": 0.20, "lcr": 0.85, "scicode": 0.60, "terminalbench_v4_0": 0.5}},
    )
    changes, unmeasured = dr.plan_changes(SELECTOR, bench)
    by = {(c["id"], c["category"]): (c["from"], c["to"]) for c in changes}
    # Placeholder B → derived letters; the leader keeps its S everywhere.
    assert by[("cheap-one", "knowledge")] == ("B", "C")  # gap 40
    assert by[("cheap-one", "long-context")] == ("B", "S")  # gap 5
    # Coding and agentic are by rank: second of two measured holds its B.
    assert ("cheap-one", "coding") not in by and ("cheap-one", "agentic") not in by
    assert not any(c["id"] == "leader" for c in changes)
    # The unmeasured model is reported and keeps its estimates, except that
    # an S takes a measurement.
    assert all("unmeasured" in ids for ids in unmeasured.values())
    assert [(c["category"], c["from"], c["to"]) for c in changes if c["id"] == "unmeasured"] == [
        ("coding", "S", "A")
    ]

    updated = dr.apply_changes(SELECTOR, changes)
    tiers = dr.current_tiers(updated)
    assert tiers["cheap-one"]["knowledge"] == "C"
    assert tiers["cheap-one"]["long-context"] == "S"
    assert tiers["unmeasured"]["coding"] == "A"
    # Untouched attributes survive verbatim.
    assert 'tier-planning="B"' in updated and 'tier-speed="S"' in updated
    assert dr.plan_changes(updated, bench)[0] == []

    # The coding S-tier enumeration lists every tier-coding="S" model,
    # cheapest first, with the cheapest as the tie-breaker.
    regen = dr.regenerate_coding_enumeration(updated)
    assert (
        "the candidate set is\n        leader; cost tie-breaker favors\n"
        "        leader when the ratings are equivalent for the prompt."
    ) in regen
    assert dr.regenerate_coding_enumeration(regen) == regen
    # The multimodal list: every S, then every A, each cheapest first.
    multimodal = dr.regenerate_multimodal_enumeration(regen)
    assert "of S or A (currently: leader at S).\n" in multimodal
    assert dr.regenerate_multimodal_enumeration(multimodal) == multimodal


def test_report_names_changes_caps_and_estimates() -> None:
    bench = _bench(**{"cheap-one": {"hle": 0.5}})
    changes, unmeasured = dr.plan_changes(SELECTOR, bench)
    text = dr.render_report(changes, unmeasured, {"cheap-one": "Cheap One"})
    assert "| Cheap One | knowledge | HLE | 50.0 | 50.0 | 0.0 | — | B | **S** |" in text
    # Every unmeasured S in a derived category is capped, and said so.
    assert "- leader: coding S → A" in text and "- unmeasured: coding S → A" in text
    assert "planning, multimodal, speed" in text
    # Names come from the catalog map when present, else the id.
    assert "**coding**: Cheap One, leader, unmeasured" in text


def test_agentic_letters_by_rank_hold_the_spread() -> None:
    """Of every 40 measured models: 9 S, 16 A, 7 B, 2 C, the rest D — by rank
    on the evidence, whatever its scale."""
    shares = dr.RANK_SHARES["agentic"]
    n = 40
    letters = [dr.letter_for_rank(better, 1, n, shares) for better in range(n)]
    assert [letters.count(x) for x in "SABCD"] == [9, 16, 7, 2, 6]
    assert letters == sorted(letters, key="SABCD".index)
    # A tie group shares its mean position, so it never splits: eight models
    # tied at the bottom of 40 (positions 32–39) are all D.
    assert dr.letter_for_rank(32, 8, n, shares) == "D"
    # The top-ranked model is S however few are measured.
    assert dr.letter_for_rank(0, 1, 2, shares) == "S"
    assert dr.letter_for_rank(1, 1, 2, shares) == "B"


def test_derive_letters_agentic_by_rank_with_rank_and_count() -> None:
    values = {f"m{i:02d}": (40 - i) / 100 for i in range(40)}  # m00 best
    bench = _bench(**{cid: {"terminalbench_v4_0": v} for cid, v in values.items()})
    d = dr.derive(bench)["agentic"]
    assert d["m00"] == {
        "value": 40.0,
        "leader": 40.0,
        "gap": 0.0,
        "rank": 1,
        "of": 40,
        "letter": "S",
    }
    assert d["m08"]["letter"] == "S" and d["m09"]["letter"] == "A"
    assert d["m24"]["letter"] == "A" and d["m25"]["letter"] == "B"
    assert d["m33"]["letter"] == "C" and d["m34"]["letter"] == "D"
    # The gap rule still governs the other categories on the same data shape.
    assert "rank" not in dr.derive(_bench(a={"hle": 0.5}, b={"hle": 0.4}))["knowledge"]["b"]


def test_a_retired_models_row_never_shifts_a_letter() -> None:
    """A retired model keeps its selector element and, for a day, its
    benchmark row; ranks and leaders use the catalog's live models only."""
    retired = SELECTOR.replace(
        'id="unmeasured" name="Unmeasured"',
        'id="unmeasured" name="Unmeasured" retired-on="2026-10-01"',
    )
    assert dr.live_ids(retired) == {"cheap-one", "leader"}
    bench = _bench(
        leader={"hle": 0.60},
        **{"cheap-one": {"hle": 0.42}},
        unmeasured={"hle": 0.90},  # would lead HLE if it counted
    )
    changes, _ = dr.plan_changes(retired, bench)
    by = {(c["id"], c["category"]): c for c in changes}
    assert by[("cheap-one", "knowledge")]["leader"] == 60.0
    assert ("leader", "knowledge") not in by  # still the leader: S


def _ts_block(source: str, name: str) -> str:
    """The body of `export const <name> ... = { ... };` in a TypeScript file."""
    m = re.search(rf"export const {name}\b.*?= \{{(.*?)\n\}};", source, re.S)
    assert m, f"{name} not found"
    return m.group(1)


def test_web_and_scoring_mirror_the_derivation() -> None:
    """The /models tooltips (web/lib/benchmark-grid.ts) must explain the rule
    the letters follow, and the scoring core must read the same evidence."""
    from roadmodel import scoring

    grid = (REPO_ROOT / "web" / "lib" / "benchmark-grid.ts").read_text(encoding="utf-8")
    bands = re.findall(r'\{ max: (\d+), letter: "([SABCD])" \}', grid)
    assert [(float(m), letter) for m, letter in bands] == dr.BANDS
    out_of = re.search(r"export const RANK_OUT_OF = (\d+);", grid)
    assert out_of and out_of.group(1) == str(dr.RANK_OUT_OF)
    ranks = _ts_block(grid, "RANK_DERIVATION")
    for cat, shares in dr.RANK_SHARES.items():
        body = re.search(rf"\n  {re.escape(cat)}: \[(.*?)\],", ranks, re.S)
        assert body, f"RANK_DERIVATION lacks {cat}"
        pairs = re.findall(r'letter: "([SABCD])", count: (\d+)', body.group(1))
        assert [(letter, int(c)) for letter, c in pairs] == shares
    ceiling = re.search(r'export const ESTIMATE_CEILING: Rating = "([SABCD])";', grid)
    assert ceiling and ceiling.group(1) == dr.ESTIMATE_CEILING
    composites = _ts_block(grid, "COMPOSITE_DERIVATION")
    for cat, (key, _scale, _label) in dr.CATEGORY_EVIDENCE.items():
        # The scoring core reads the same evidence.
        assert scoring.CATEGORY_EVIDENCE[cat] == key
        if key in dr.COMPOSITES:
            # A composite: the same parts in the scoring core and on the page.
            parts = dr.COMPOSITES[key]
            assert scoring.COMPOSITES[key] == parts
            body = re.search(
                rf"\n  {re.escape(cat)}: \{{.*?parts: \[(.*?)\] \}},", composites, re.S
            )
            assert body, f"COMPOSITE_DERIVATION lacks {cat}"
            assert tuple(re.findall(r'"(\w+)"', body.group(1))) == parts
        else:
            # A single evidence column carries the category's `category` tag.
            block = re.search(rf'key: "{key}",(.*?)\n  \}}', grid, re.S)
            assert block and f'category: "{cat}"' in block.group(1), f"{key} is not tagged {cat}"
    assert set(dr.RANK_SHARES) <= scoring.RANK_SCALED


def test_committed_selector_matches_committed_benchmark_layer() -> None:
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    bench = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())["models"]
    changes, _ = dr.plan_changes(selector, bench)
    assert changes == [], (
        "docs/model-selector.txt disagrees with docs/benchmarks.json on derived ratings: "
        + "; ".join(f"{c['id']} {c['category']} {c['from']}→{c['to']}" for c in changes)
        + " — run: python update/derive_ratings.py --write && python update/render_md.py && python update/build_catalog.py"
    )
    # And both letter-driven enumerations are exactly the regeneration.
    assert dr.regenerate_coding_enumeration(selector) == selector
    assert dr.regenerate_multimodal_enumeration(selector) == selector
    # No derived category holds an unmeasured S.
    assert not [c for c in changes if c.get("capped")]
