"""Model prose written from data (update/model_prose.py).

The catalog cron used to fill a new model's `best-for` and `headline-benchmarks`
with placeholders ("Auto-added cheap-tier Meta model; pending editorial best-for
refinement.") that waited on a maintainer who never came, and /models showed
them for weeks. These tests hold the committed catalog to two things: no model's
text describes the pipeline instead of the model, and every field the generator
owns is what the generator writes from today's letters, prices and benchmarks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import model_prose  # noqa: E402

CATS = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")


# ---------------------------------------------------------------------------
# The committed catalog
# ---------------------------------------------------------------------------


def _catalog_models() -> list[dict[str, Any]]:
    return json.loads((REPO_ROOT / "docs" / "catalog.json").read_text())["models"]


@pytest.mark.parametrize("field", ["best_for", "headline_benchmarks"])
def test_every_model_has_real_text(field: str) -> None:
    bad = {
        m["id"]: m[field]
        for m in _catalog_models()
        if not m[field].strip() or model_prose.PROCESS_RE.search(m[field])
    }
    assert not bad, (
        f"{field} is empty or describes the pipeline instead of the model: {bad}. "
        "Run `python update/model_prose.py --write`, then render_md.py and build_catalog.py."
    )


def test_selector_matches_the_generator() -> None:
    selector = model_prose.SELECTOR_PATH.read_text()
    benchmarks = json.loads(model_prose.BENCHMARKS_PATH.read_text())
    new_text, changes = model_prose.apply(selector, benchmarks)
    assert new_text == selector, (
        f"{len(changes)} generated field(s) are stale, e.g. "
        f"{[(c.id, c.field) for c in changes[:3]]}. Run `python update/model_prose.py --write`, "
        "then render_md.py and build_catalog.py."
    )


# ---------------------------------------------------------------------------
# The generator, on a small selector
# ---------------------------------------------------------------------------


def _model(
    mid: str,
    price_in: float,
    price_out: float,
    letter: str = "A",
    best_for: str = "",
    headline: str = "",
    extra: str = "",
    **tier: str,
) -> str:
    ratings = " ".join(f'tier-{c}="{tier.get(c.replace("-", "_"), letter)}"' for c in CATS)
    return (
        f'      <model id="{mid}" name="{mid.title()}"\n'
        f'             input-price-per-1m="${price_in:.2f}" output-price-per-1m="${price_out:.2f}"\n'
        f'             jurisdiction="us" {ratings}\n'
        f'             headline-benchmarks="{headline}"\n'
        f'             pricing-notes="-"\n'
        f'             best-for="{best_for}"{extra} />'
    )


def _selector(*models: str, tier: str = "low") -> str:
    return (
        f'<model-options>\n    <tier cost="{tier}">\n'
        + "\n".join(models)
        + "\n    </tier>\n</model-options>\n<access-methods>\n</access-methods>\n"
    )


def _bench(**rows: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for mid, ev in rows.items():
        out[mid] = {
            "aa_name": ev.pop("aa_name", mid.title()),
            "evaluations": ev,
            "median_output_tokens_per_second": 120.0,
        }
    return {"models": out}


def _attrs(text: str, mid: str) -> dict[str, str]:
    for el in model_prose.MODEL_RE.finditer(text):
        a = model_prose._parse_attrs(el.group(1))
        if a.get("id") == mid:
            return {
                "best-for": a.get("best-for", ""),
                "headline-benchmarks": a.get("headline-benchmarks", ""),
                "marker": a.get(model_prose.MARKER, ""),
            }
    raise KeyError(mid)


PLACEHOLDER_BF = "Auto-added cheap-tier Meta model; pending editorial best-for refinement."
PLACEHOLDER_HB = (
    "Auto-added pending editorial tier review; specific benchmark numbers pending next refresh"
)


def test_a_placeholder_is_replaced_and_marked() -> None:
    text = _selector(
        _model("muse", 1.25, 4.25, "A", PLACEHOLDER_BF, PLACEHOLDER_HB, coding="S", speed="B"),
        _model("rival", 3, 15, "B", "A curated description.", "AA Intelligence Index 30.0"),
    )
    bench = _bench(
        muse={
            "artificial_analysis_intelligence_index": 48.1,
            "hle": 0.487,
            "aa_name": "Muse (Max)",
        },
        rival={"artificial_analysis_intelligence_index": 30.0},
    )
    out, changes = model_prose.apply(text, bench)
    muse = _attrs(out, "muse")
    assert muse["marker"] == "best-for headline-benchmarks"
    assert muse["headline-benchmarks"] == "AA Intelligence Index 48.1 (max); HLE 48.7%"
    assert muse["best-for"].startswith("Frontier-class coding, plus strong planning")
    assert "is the highest in the catalog" in muse["best-for"]
    assert "cheapest model in the catalog rated S for coding" in muse["best-for"]
    assert not model_prose.PROCESS_RE.search(muse["best-for"] + muse["headline-benchmarks"])
    # The curated rival is left exactly as written, and carries no marker.
    rival = _attrs(out, "rival")
    assert rival == {
        "best-for": "A curated description.",
        "headline-benchmarks": "AA Intelligence Index 30.0",
        "marker": "",
    }
    assert {(c.id, c.field) for c in changes} == {
        ("muse", "best-for"),
        ("muse", "headline-benchmarks"),
    }


def test_the_pass_is_idempotent() -> None:
    text = _selector(_model("muse", 1.25, 4.25, "A", PLACEHOLDER_BF, PLACEHOLDER_HB))
    bench = _bench(muse={"artificial_analysis_intelligence_index": 48.1})
    once, _ = model_prose.apply(text, bench)
    twice, changes = model_prose.apply(once, bench)
    assert twice == once and changes == []


def test_generated_text_follows_the_data() -> None:
    """A marked field is rewritten on every run, so a new benchmark figure or a
    letter change reaches the prose without anyone touching it."""
    text = _selector(_model("muse", 1.25, 4.25, "A", PLACEHOLDER_BF, PLACEHOLDER_HB))
    first, _ = model_prose.apply(
        text, _bench(muse={"artificial_analysis_intelligence_index": 40.0})
    )
    moved = first.replace('tier-coding="A"', 'tier-coding="S"')
    second, _ = model_prose.apply(
        moved, _bench(muse={"artificial_analysis_intelligence_index": 44.5})
    )
    muse = _attrs(second, "muse")
    assert muse["headline-benchmarks"] == "AA Intelligence Index 44.5"
    assert muse["best-for"].startswith("Frontier-class coding")


def test_headline_keeps_sourced_claims_and_drops_process_ones() -> None:
    headline = (
        "AA Intelligence Index 30.0 (old); LMArena Text Elo 1470.9 (#27); "
        "Terminal-Bench 2.1 90.6, HLE 36.8% (all DeepSeek-reported); "
        "specific numbers pending independent refresh; 1M-token context"
    )
    text = _selector(_model("glm", 1.4, 4.4, "B", "Curated.", headline))
    bench = _bench(
        glm={"artificial_analysis_intelligence_index": 41.8, "scicode": 0.516, "lcr": 0.8}
    )
    out, _ = model_prose.apply(text, bench)
    assert _attrs(out, "glm")["headline-benchmarks"] == (
        "AA Intelligence Index 41.8; SciCode 51.6; AA-LCR 0.800; LMArena Text Elo 1470.9 (#27); "
        "Terminal-Bench 2.1 90.6, HLE 36.8% (all DeepSeek-reported); 1M-token context"
    )
    assert _attrs(out, "glm")["best-for"] == "Curated."


def test_a_measured_model_whose_headline_cites_no_aa_figure_gains_them() -> None:
    text = _selector(_model("sol", 2, 12, "A", "Curated.", "LMArena WebDev #6 (Elo 1692.3)"))
    out, _ = model_prose.apply(text, _bench(sol={"artificial_analysis_intelligence_index": 47.5}))
    sol = _attrs(out, "sol")
    assert (
        sol["headline-benchmarks"] == "AA Intelligence Index 47.5; LMArena WebDev #6 (Elo 1692.3)"
    )
    assert sol["marker"] == "headline-benchmarks"


def test_an_unmeasured_model_says_so_until_aa_measures_it() -> None:
    text = _selector(
        _model("codestral", 0.3, 0.9, "B", "Curated.", "Code model; numbers pending refresh")
    )
    out, _ = model_prose.apply(text, {"models": {}})
    assert _attrs(out, "codestral")["headline-benchmarks"] == (
        "Code model; Artificial Analysis has not measured Codestral yet, so its letters are estimates"
    )
    later, _ = model_prose.apply(
        out, _bench(codestral={"artificial_analysis_intelligence_index": 20.0})
    )
    assert (
        _attrs(later, "codestral")["headline-benchmarks"]
        == "AA Intelligence Index 20.0; Code model"
    )


def test_best_for_reports_rank_price_record_weak_spots_and_successor() -> None:
    text = _selector(
        _model(
            "old",
            1,
            4,
            "A",
            PLACEHOLDER_BF,
            extra=' superseded-by="new" superseded-on="2026-09-24"',
            speed="D",
            multimodal="C",
        ),
        _model("new", 1, 4, "A", "Curated.", "AA Intelligence Index 50.0"),
        _model("pricey", 5, 25, "A", "Curated.", "AA Intelligence Index 45.0"),
    )
    bench = _bench(
        old={"artificial_analysis_intelligence_index": 40.0},
        new={"artificial_analysis_intelligence_index": 50.0},
        pricey={"artificial_analysis_intelligence_index": 45.0},
    )
    out, _ = model_prose.apply(text, bench)
    assert _attrs(out, "old")["best-for"] == (
        "Strong coding, planning, agentic work, long context and knowledge at a low price. "
        "Its AA Intelligence Index of 40.0 ranks 3rd of 3 measured models. "
        "Weakest at speed (D), then multimodal input (C). Superseded by New."
    )


def test_highest_at_its_price_or_lower() -> None:
    text = _selector(
        _model("cheap", 0.5, 2, "A", PLACEHOLDER_BF, "AA Intelligence Index 1"),
        _model("costly", 5, 25, "A", "Curated.", "AA Intelligence Index 1"),
        _model("weak", 0.25, 1, "A", "Curated.", "AA Intelligence Index 1"),
    )
    bench = _bench(
        cheap={"artificial_analysis_intelligence_index": 40.0},
        costly={"artificial_analysis_intelligence_index": 50.0},
        weak={"artificial_analysis_intelligence_index": 30.0},
    )
    out, _ = model_prose.apply(text, bench)
    assert (
        "ranks 2nd of 3 measured models, the highest of any model at its price or lower."
        in _attrs(out, "cheap")["best-for"]
    )


def test_a_retired_model_is_left_as_its_record() -> None:
    retired = _model(
        "gone",
        1,
        4,
        "A",
        PLACEHOLDER_BF,
        PLACEHOLDER_HB,
        extra=' superseded-by="x" superseded-on="2026-08-01" retired-on="2026-08-31"',
    )
    text = _selector(retired)
    out, changes = model_prose.apply(text, {"models": {}})
    assert out == text and changes == []


def test_clauses_split_on_top_level_semicolons_only() -> None:
    assert model_prose.split_clauses("A 1 (v4; note); B 2;  ; C") == ["A 1 (v4; note)", "B 2", "C"]


@pytest.mark.parametrize(
    "text",
    [
        PLACEHOLDER_BF,
        PLACEHOLDER_HB,
        "placeholder tier ratings inherited from sonnet-4.6 pending editorial refresh",
        "pick over 4.5 since 4.6 supersedes it per the equal-output-price replacement rule",
        "No benchmark figures cited yet",
    ],
)
def test_process_text_is_recognised(text: str) -> None:
    assert model_prose.PROCESS_RE.search(text)
