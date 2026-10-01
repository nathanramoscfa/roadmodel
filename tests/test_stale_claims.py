"""Claims in hand-written model prose that the data contradicts (update/stale_claims.py).

A hand-written best-for / headline-benchmarks stays as written until the
catalog's data contradicts a claim in it ("Latest Grok release" once Grok 4.7
ships); update/model_prose.py then takes the field over. These tests pin what
counts as a contradiction, and, as importantly, what does not: a claim about
another model, a vendor-reported figure, a figure for another effort variant,
price history, "best suited for".
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import model_prose  # noqa: E402
import stale_claims  # noqa: E402

CATS = ("coding", "planning", "agentic", "multimodal", "long-context", "knowledge", "speed")
TODAY = dt.date(2026, 10, 1)


def _el(
    mid: str,
    name: str,
    price: tuple[float, float],
    letters: str = "AAAAAAA",
    best_for: str = "Curated.",
    headline: str = "AA Intelligence Index 1.0",
) -> str:
    ratings = " ".join(f'tier-{c}="{letter}"' for c, letter in zip(CATS, letters, strict=True))
    return (
        f'      <model id="{mid}" name="{name}"\n'
        f'             input-price-per-1m="${price[0]:.2f}" output-price-per-1m="${price[1]:.2f}"\n'
        f'             jurisdiction="us" {ratings}\n'
        f'             headline-benchmarks="{headline}"\n'
        f'             pricing-notes="-"\n'
        f'             best-for="{best_for}" />'
    )


def _selector(**tiers: list[str]) -> str:
    blocks = "".join(
        f'    <tier cost="{tier.replace("_", "-")}">\n' + "\n".join(els) + "\n    </tier>\n"
        for tier, els in tiers.items()
    )
    return f"<model-options>\n{blocks}</model-options>\n<access-methods>\n</access-methods>\n"


def _bench(**rows: tuple[str, float, dict[str, float]]) -> dict[str, Any]:
    """id -> (release_date, AA Index, other evaluations)."""
    return {
        "models": {
            mid.replace("_", "-").replace("-dot-", "."): {
                "aa_name": f"{mid} (Max)",
                "release_date": rel,
                "evaluations": {"artificial_analysis_intelligence_index": idx, **ev},
                "median_output_tokens_per_second": 100.0,
            }
            for mid, (rel, idx, ev) in rows.items()
        }
    }


def _claims(
    text: str, mid: str, selector: str, bench: dict[str, Any], today: dt.date = TODAY
) -> list[str]:
    catalog = model_prose.load_models(selector, bench)
    m = next(o for o in catalog if o.id == mid)
    return [f.kind for f in stale_claims.claims(text, m, catalog, today)]


GROKS = _selector(
    low=[_el("grok-4.3", "Grok 4.3", (1.25, 2.5)), _el("grok-4.7", "Grok 4.7", (2, 6))]
)
GROK_BENCH = _bench(grok_4_dot_3=("2026-04-30", 24.9, {}), grok_4_dot_7=("2026-09-21", 46.4, {}))


# --- superlatives ----------------------------------------------------------


def test_latest_is_false_once_a_newer_model_of_the_family_ships() -> None:
    assert _claims("Latest Grok release with a 2M context", "grok-4.3", GROKS, GROK_BENCH) == [
        "superlative"
    ]
    assert _claims("Latest Grok release with a 2M context", "grok-4.7", GROKS, GROK_BENCH) == []


def test_most_capable_ranges_over_the_scope_the_clause_names() -> None:
    selector = _selector(
        very_high=[
            _el("gpt-5.5", "GPT-5.5", (5, 30)),
            _el("gpt-6-astra", "GPT-6 Astra", (10, 50)),
            _el("claude-opus-5-5", "Opus 5.5", (4, 20)),
        ]
    )
    bench = _bench(
        gpt_5_dot_5=("2026-04-23", 38.4, {}),
        gpt_6_astra=("2026-09-03", 52.7, {}),
        claude_opus_5_5=("2026-08-01", 57.6, {}),
    )
    claim = "OpenAI's most capable frontier model"
    assert _claims(claim, "gpt-5.5", selector, bench) == ["superlative"]  # GPT-6 Astra
    # Opus 5.5 outscores Astra, but "OpenAI's" puts Anthropic out of scope.
    assert _claims(claim, "gpt-6-astra", selector, bench) == []


def test_best_at_a_category_needs_the_best_letter_in_scope() -> None:
    selector = _selector(
        medium=[
            _el("gpt-5.3-codex", "GPT-5.3 Codex", (1.75, 14), letters="AAAAAAA"),
            _el("sonnet-5", "Sonnet 5", (2, 10), letters="AASAAAA"),
        ],
        high=[_el("opus-x", "Opus X", (4, 20), letters="SSSAAAA")],
    )
    bench = _bench(gpt_5_dot_3_codex=("2026-02-05", 32.5, {}))
    tiered = "Highest terminal and tool-use proficiency at the medium tier"
    assert _claims(tiered, "gpt-5.3-codex", selector, bench) == ["superlative"]  # Sonnet 5: S
    assert _claims(tiered, "sonnet-5", selector, bench) == []  # Opus X is S too, but high tier
    assert _claims("best long-context recall at 1M tokens", "gpt-5.3-codex", selector, bench) == []
    assert _claims(
        "best long-context recall at 1M tokens",
        "gpt-5.3-codex",
        _selector(
            medium=[
                _el("gpt-5.3-codex", "GPT-5.3 Codex", (1.75, 14)),
                _el("gemini-x", "Gemini X", (2, 12), letters="AAAASAA"),
            ]
        ),
        bench,
    ) == ["superlative"]


def test_cheapest_in_a_family() -> None:
    selector = _selector(
        low=[
            _el("gpt-5-mini", "GPT-5 Mini", (0.25, 2)),
            _el("gpt-5.6-luna", "GPT-5.6 Luna", (0.2, 1.2)),
            _el("gemini-2.5-flash", "Gemini 2.5 Flash", (0.1, 0.4)),
        ],
        medium=[_el("gpt-5", "GPT-5", (1.25, 10))],
    )
    bench = _bench(gpt_5_mini=("2025-08-07", 16.8, {}))
    # "GPT-5 family" names the family, not the gpt-5 model; Gemini is outside it.
    assert _claims("The cheapest GPT-5 family variant", "gpt-5-mini", selector, bench) == [
        "superlative"
    ]
    assert _claims("The cheapest GPT-5 family variant", "gpt-5.6-luna", selector, bench) == []


@pytest.mark.parametrize(
    "text",
    [
        "best suited for the most demanding reasoning",
        "prefer grok-4.7 when the latest generation matters",  # about another model
        "Terminal-Bench 2.1 84.6 (top-tier)",
    ],
)
def test_not_a_superlative_about_this_model(text: str) -> None:
    assert _claims(text, "grok-4.3", GROKS, GROK_BENCH) == []


# --- letters, prices, promotions --------------------------------------------


def test_letter_claims() -> None:
    selector = _selector(
        medium=[_el("gpt-5.1-codex", "GPT-5.1 Codex", (1.25, 10), letters="ABADACB")]
    )
    bench = _bench()
    assert _claims("the lowest-cost S-tier coding model", "gpt-5.1-codex", selector, bench) == [
        "letter"
    ]
    assert _claims("an A-tier coding and agentic profile", "gpt-5.1-codex", selector, bench) == []
    assert _claims("native multimodal-D", "gpt-5.1-codex", selector, bench) == []
    # Another model's letter.
    assert (
        _claims("lacks Gemini's native multimodal-A rating", "gpt-5.1-codex", selector, bench) == []
    )


def test_prices_must_include_the_models_own() -> None:
    selector = _selector(
        high=[_el("gpt-5.6-sol", "GPT-5.6 Sol", (4, 20))],
        low=[_el("gemini-2.5-flash", "Gemini 2.5 Flash", (0.3, 2.5))],
    )
    bench = _bench()
    assert _claims("at $0.30/M output", "gemini-2.5-flash", selector, bench) == ["price"]
    assert _claims("at $2.50/M output (input $0.30)", "gemini-2.5-flash", selector, bench) == []
    assert (
        _claims("now ($4/$20) (was $5/$30 at initial listing)", "gpt-5.6-sol", selector, bench)
        == []
    )
    assert _claims("priced at $5/$30", "gpt-5.6-sol", selector, bench) == ["price"]


def test_a_promotion_is_stale_the_day_after_it_ends() -> None:
    selector = _selector(high=[_el("gpt-5.6-sol", "GPT-5.6 Sol", (4, 20))])
    text = "promotional pricing through November 21, 2026"
    assert _claims(text, "gpt-5.6-sol", selector, _bench(), dt.date(2026, 11, 21)) == []
    assert _claims(text, "gpt-5.6-sol", selector, _bench(), dt.date(2026, 11, 22)) == ["promotion"]


# --- Artificial Analysis figures ---------------------------------------------


GLM = _selector(low=[_el("glm-5.3", "GLM-5.3", (1.4, 4.4)), _el("glm-6", "GLM-6", (1.4, 4.4))])
GLM_BENCH = _bench(
    glm_5_dot_3=("2026-08-18", 44.8, {"hle": 0.423, "terminalbench_v2_1": 0.851}),
    glm_6=("2026-09-30", 50.0, {"hle": 0.50}),
)


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("AA Intelligence Index 44.8 (max); HLE 42.3%", []),
        ("AA Intelligence Index 44.9", []),  # one unit of rounding
        ("AA Intelligence Index 40.1 (max)", ["figure"]),
        ("strong AA Intelligence Index (40.1 max) for the price", ["figure"]),
        ("HLE 38.0%", ["figure"]),
        ("Terminal-Bench 2.1 80.0", ["figure"]),
        ("AA Intelligence Index 40.1 (non-reasoning)", []),  # another effort variant
        ("Terminal-Bench 2.1 90.6, HLE 36.8% (all GLM-reported)", []),  # the vendor's figure
        ("HLE 42.3% (#1)", ["rank"]),  # GLM-6 scores higher
        ("HLE 42.3% (#2)", []),
    ],
)
def test_figures(text: str, kinds: list[str]) -> None:
    assert _claims(text, "glm-5.3", GLM, GLM_BENCH) == kinds


def test_refresh_brings_an_aa_figure_current_at_its_own_precision() -> None:
    m = next(o for o in model_prose.load_models(GLM, GLM_BENCH) if o.id == "glm-5.3")
    assert (
        stale_claims.refresh_figures("Terminal-Bench 2.1 80.0 (max)", m)
        == "Terminal-Bench 2.1 85.1 (max)"
    )
    # A figure for another effort variant is left alone.
    assert (
        stale_claims.refresh_figures("Terminal-Bench 2.1 80.0 (high)", m)
        == "Terminal-Bench 2.1 80.0 (high)"
    )
    assert stale_claims.refresh_figures("Terminal-Bench 2.1 90.6 (GLM-reported)", m) == (
        "Terminal-Bench 2.1 90.6 (GLM-reported)"
    )


# --- through model_prose ------------------------------------------------------


def test_a_contradicted_best_for_is_taken_over_and_marked() -> None:
    selector = _selector(
        low=[
            _el(
                "grok-4.3", "Grok 4.3", (1.25, 2.5), best_for="Latest Grok release with 2M context"
            ),
            _el("grok-4.7", "Grok 4.7", (2, 6), best_for="Latest Grok release, jointly trained"),
        ]
    )
    out, changes = model_prose.apply(selector, GROK_BENCH, TODAY)
    taken = {(c.id, c.field): c.why for c in changes}
    assert "Grok 4.7 is newer" in taken[("grok-4.3", "best-for")]
    assert ("grok-4.7", "best-for") not in taken  # still true: left as written
    marker = out.split('id="grok-4.7"')[0].split('prose-generated="')[1].split('"')[0]
    assert "best-for" in marker.split()


def test_a_contradicted_headline_keeps_its_other_claims() -> None:
    headline = (
        "AA Intelligence Index 44.8 (max); HLE 38.0%; Terminal-Bench 2.1 80.0; "
        "LMArena Text Elo 1472.5 (#25); cheapest GLM; 1M-token context"
    )
    selector = _selector(
        low=[
            _el("glm-5.3", "GLM-5.3", (1.4, 4.4), headline=headline),
            _el("glm-5.3-flash", "GLM-5.3-Flash", (0.15, 0.5)),
        ]
    )
    bench = _bench(glm_5_dot_3=("2026-08-18", 44.8, {"hle": 0.423, "terminalbench_v2_1": 0.851}))
    out, changes = model_prose.apply(selector, bench, TODAY)
    new = next(c.new for c in changes if c.id == "glm-5.3" and c.field == "headline-benchmarks")
    # Fresh AA figures, the TB 2.1 figure brought current, LMArena and the
    # context window kept, the false "cheapest GLM" gone.
    assert new == (
        "AA Intelligence Index 44.8 (max); HLE 42.3%; Terminal-Bench 2.1 85.1; "
        "LMArena Text Elo 1472.5 (#25); 1M-token context"
    )
