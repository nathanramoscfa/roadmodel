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
        leader={
            "artificial_analysis_coding_index": 80.0,
            "hle": 0.60,
            "lcr": None,
            "terminalbench_v2_1": 0.9,
        },
        cheap_one={
            "artificial_analysis_coding_index": 58.0,
            "hle": 0.42,
            "lcr": 0.7,
            "terminalbench_v2_1": None,
        },
    )
    d = dr.derive(bench)
    assert d["coding"]["leader"]["letter"] == "S"
    assert d["coding"]["cheap_one"] == {"value": 58.0, "leader": 80.0, "gap": 22.0, "letter": "B"}
    # HLE fraction → points: 0.42 → 42.0, gap 18 → A.
    assert d["knowledge"]["cheap_one"]["letter"] == "A"
    # Only cheap_one has LCR, so it IS the leader.
    assert d["long-context"] == {
        "cheap_one": {"value": 70.0, "leader": 70.0, "gap": 0.0, "letter": "S"}
    }
    assert "cheap_one" not in d["agentic"]


def test_plan_apply_and_enumeration_round_trip() -> None:
    bench = _bench(
        leader={
            "artificial_analysis_coding_index": 80.0,
            "hle": 0.60,
            "lcr": 0.9,
            "terminalbench_v2_1": 0.9,
        },
        **{
            "cheap-one": {
                "artificial_analysis_coding_index": 77.0,
                "hle": 0.20,
                "lcr": 0.85,
                "terminalbench_v2_1": 0.5,
            }
        },
    )
    changes, unmeasured = dr.plan_changes(SELECTOR, bench)
    by = {(c["id"], c["category"]): (c["from"], c["to"]) for c in changes}
    # Placeholder B → derived letters; the leader keeps its S everywhere.
    assert by[("cheap-one", "coding")] == ("B", "S")  # gap 3
    assert by[("cheap-one", "knowledge")] == ("B", "C")  # gap 40
    assert by[("cheap-one", "long-context")] == ("B", "S")  # gap 5
    assert by[("cheap-one", "agentic")] == ("B", "C")  # gap 40
    assert not any(c["id"] == "leader" for c in changes)
    # The unmeasured model is reported, not edited.
    assert all("unmeasured" in ids for ids in unmeasured.values())
    assert not any(c["id"] == "unmeasured" for c in changes)

    updated = dr.apply_changes(SELECTOR, changes)
    tiers = dr.current_tiers(updated)
    assert tiers["cheap-one"]["coding"] == "S"
    assert tiers["cheap-one"]["knowledge"] == "C"
    assert tiers["cheap-one"]["long-context"] == "S"
    # Untouched attributes survive verbatim.
    assert 'tier-planning="B"' in updated and 'tier-speed="S"' in updated
    assert dr.plan_changes(updated, bench)[0] == []

    # The coding S-tier enumeration lists every tier-coding="S" model,
    # cheapest first, with the cheapest as the tie-breaker.
    regen = dr.regenerate_coding_enumeration(updated)
    assert (
        "the candidate set is\n        cheap-one, unmeasured, leader; cost tie-breaker favors\n"
        "        cheap-one when the ratings are equivalent for the prompt."
    ) in regen
    # Idempotent.
    assert dr.regenerate_coding_enumeration(regen) == regen


def test_report_names_changes_and_editorial_categories() -> None:
    bench = _bench(
        **{
            "cheap-one": {
                "artificial_analysis_coding_index": 50.0,
                "hle": None,
                "lcr": None,
                "terminalbench_v2_1": None,
            }
        }
    )
    changes, unmeasured = dr.plan_changes(SELECTOR, bench)
    text = dr.render_report(changes, unmeasured, {"cheap-one": "Cheap One"})
    assert "| Cheap One | coding | AA Coding Index | 50.0 | 50.0 | 0.0 | B | **S** |" in text
    assert "planning, multimodal, speed" in text
    # Names come from the catalog map when present, else the id.
    assert "**knowledge**: Cheap One, leader, unmeasured" in text


def test_committed_selector_matches_committed_benchmark_layer() -> None:
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    bench = json.loads((REPO_ROOT / "docs" / "benchmarks.json").read_text())["models"]
    changes, _ = dr.plan_changes(selector, bench)
    assert changes == [], (
        "docs/model-selector.txt disagrees with docs/benchmarks.json on derived ratings: "
        + "; ".join(f"{c['id']} {c['category']} {c['from']}→{c['to']}" for c in changes)
        + " — run: python update/derive_ratings.py --write && python update/render_md.py && python update/build_catalog.py"
    )
    # And the coding S-tier enumeration is exactly the regeneration.
    assert dr.regenerate_coding_enumeration(selector) == selector
