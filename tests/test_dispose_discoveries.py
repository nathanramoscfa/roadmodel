"""update/dispose_discoveries.py — every flagged model is added or declined.

A priced same-series successor joins the catalog with its predecessor's
letters (which the rating guard accepts as its placeholder); everything else is
declined with a reason, an unpriced model re-checked each run; the curation
pass's own declines stand; and a second run changes nothing.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))


def _load(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, UPDATE_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve annotations through it
    spec.loader.exec_module(mod)
    return mod


dd = _load("dispose_discoveries")
rg = _load("rating_guard")

TODAY = dt.date(2026, 10, 1)
SOL = (
    '      <model id="gpt-6-sol" name="GPT-6 Sol"\n'
    '             input-price-per-1m="$2.00" output-price-per-1m="$10.00"\n'
    '             jurisdiction="us"\n'
    '             tier-coding="S" tier-planning="B" tier-agentic="S"\n'
    '             tier-multimodal="B" tier-long-context="S" tier-knowledge="A"\n'
    '             tier-speed="B"\n'
    '             headline-benchmarks="x" pricing-notes="y" best-for="z" />'
)
FLASH = (
    '      <model id="gemini-3.8-flash" name="Gemini 3.8 Flash"\n'
    '             input-price-per-1m="$0.75" output-price-per-1m="$3.50"\n'
    '             jurisdiction="us"\n'
    '             tier-coding="A" tier-planning="A" tier-agentic="A"\n'
    '             tier-multimodal="B" tier-long-context="A" tier-knowledge="A"\n'
    '             tier-speed="S"\n'
    '             headline-benchmarks="x" pricing-notes="y" best-for="z" />'
)
SELECTOR = f"""<selector>
<model-options>
    <tier cost="medium">
{SOL}
    </tier>
    <tier cost="low">
{FLASH}
    </tier>
</model-options>
<access-methods>
    <method id="openai-api" name="OpenAI API" provider="openai" billing="per-token"
            supports-models="gpt-6-sol" best-for="b" />
    <method id="google-api" name="Google API" provider="google" billing="per-token"
            supports-models="gemini-3.8-flash" best-for="b" />
</access-methods>
</selector>
"""
COST_SCALE = """# Cost scale

## Declined Models (discovery lane)

Models the catalog does not carry.

- google/Gemini 2.5 Computer Use — computer-use variant, not a general text model (declined 2026-09-25)
"""


def _flag(provider: str, slug: str, price: tuple[float, float] | None = None) -> object:
    return dd.Flag(
        provider, slug, price[0] if price else None, price[1] if price else None, "provider page"
    )


def test_a_priced_successor_is_added_beside_its_predecessor() -> None:
    selector, cost_scale, actions = dd.dispose(
        SELECTOR, COST_SCALE, [_flag("openai", "gpt-6.1-sol", (2.0, 10.0))], TODAY
    )
    assert [a.kind for a in actions] == ["added"]
    models = rg.models(selector)
    assert models["gpt-6.1-sol"].name == "GPT-6.1 Sol"
    assert models["gpt-6.1-sol"].tiers == models["gpt-6-sol"].tiers
    # Right after its predecessor, in the medium tier its $10 output price sets.
    assert selector.index('id="gpt-6.1-sol"') > selector.index('id="gpt-6-sol"')
    assert selector.index('id="gpt-6.1-sol"') < selector.index('<tier cost="low">')
    assert 'supports-models="gpt-6-sol,gpt-6.1-sol"' in selector
    assert 'best-for=""' in selector and 'headline-benchmarks=""' in selector
    assert cost_scale == COST_SCALE
    # The rating guard accepts the letters as the new model's placeholder.
    assert rg.guard(SELECTOR, selector, "", {})[1] == []
    # A second run changes nothing.
    again = dd.dispose(selector, cost_scale, [_flag("openai", "gpt-6.1-sol", (2.0, 10.0))], TODAY)
    assert again == (selector, cost_scale, [])


def test_an_unpriced_model_is_declined_then_added_once_priced() -> None:
    _, cost_scale, actions = dd.dispose(
        SELECTOR, COST_SCALE, [_flag("google", "Gemini 3.9 Flash")], TODAY
    )
    assert [a.kind for a in actions] == ["declined"]
    line = f"- google/Gemini 3.9 Flash — {dd.NO_PRICE} (declined 2026-10-01)"
    assert line in cost_scale
    # The AI pass's decline survives untouched.
    assert "- google/Gemini 2.5 Computer Use — computer-use variant" in cost_scale
    # Priced later: the decline is lifted and the successor added.
    selector, cost_scale2, actions = dd.dispose(
        SELECTOR, cost_scale, [_flag("google", "Gemini 3.9 Flash", (0.75, 3.5))], TODAY
    )
    assert [a.kind for a in actions] == ["lifted", "added"]
    assert line not in cost_scale2
    assert rg.models(selector)["gemini-3.9-flash"].name == "Gemini 3.9 Flash"


def test_a_priced_new_series_is_declined_and_stays_declined() -> None:
    flag = _flag("google", "Gemini 3.9 Flash-Lite", (0.1, 0.4))
    selector, cost_scale, actions = dd.dispose(SELECTOR, COST_SCALE, [flag], TODAY)
    assert selector == SELECTOR and [a.detail for a in actions] == [dd.NEW_SERIES]
    assert dd.dispose(selector, cost_scale, [flag], TODAY)[2] == []


def test_the_curation_pass_decides_first() -> None:
    # Declined by the pass (any reason of its own): never added, however priced.
    declined = COST_SCALE + "- openai/gpt-6.1-sol — limited preview (declined 2026-09-30)\n"
    result = dd.dispose(SELECTOR, declined, [_flag("openai", "gpt-6.1-sol", (2.0, 10.0))], TODAY)
    assert result == (SELECTOR, declined, [])
    # Carried already: left alone.
    assert (
        dd.dispose(SELECTOR, COST_SCALE, [_flag("openai", "GPT-6 Sol", (2.0, 10.0))], TODAY)[2]
        == []
    )


def test_a_specialized_model_is_declined_as_such() -> None:
    noted = COST_SCALE + f"- google/Gemini Robotics Er 2 — {dd.NO_PRICE} (declined 2026-09-30)\n"
    flags = [_flag("google", "Gemini Robotics Er 2"), _flag("openai", "gpt-image-2", (5.0, 40.0))]
    selector, cost_scale, actions = dd.dispose(SELECTOR, noted, flags, TODAY)
    assert selector == SELECTOR
    assert [(a.kind, a.flag.slug, a.detail) for a in actions] == [
        ("declined", "Gemini Robotics Er 2", dd.SPECIALIZED),
        ("declined", "gpt-image-2", dd.SPECIALIZED),
    ]
    assert f"- google/Gemini Robotics Er 2 — {dd.SPECIALIZED} (declined 2026-10-01)" in cost_scale
    assert dd.NO_PRICE not in cost_scale
    assert dd.dispose(selector, cost_scale, flags, TODAY)[2] == []


def test_a_newly_priced_new_series_is_declined_as_one() -> None:
    noted = COST_SCALE + f"- google/Gemini 3.9 Flash-Lite — {dd.NO_PRICE} (declined 2026-09-30)\n"
    flag = _flag("google", "Gemini 3.9 Flash-Lite", (0.1, 0.4))
    _, cost_scale, actions = dd.dispose(SELECTOR, noted, [flag], TODAY)
    assert [(a.kind, a.detail) for a in actions] == [("declined", dd.NEW_SERIES)]
    assert dd.NO_PRICE not in cost_scale


def test_the_curation_pass_outranks_a_provisional_decline() -> None:
    both = (
        COST_SCALE
        + f"- google/Gemini 3.9 Flash-Lite — {dd.NO_PRICE} (declined 2026-09-30)\n"
        + "- google/Gemini 3.9 Flash-Lite — superseded by a newer Flash-Lite (declined 2026-10-01)\n"
    )
    flag = _flag("google", "Gemini 3.9 Flash-Lite", (0.1, 0.4))
    _, cost_scale, actions = dd.dispose(SELECTOR, both, [flag], TODAY)
    assert dd.NO_PRICE not in cost_scale
    assert "superseded by a newer Flash-Lite (declined 2026-10-01)" in cost_scale
    assert [a.line() for a in actions] == [
        "- lifted: `google/Gemini 3.9 Flash-Lite` — the curation pass declined it: "
        "superseded by a newer Flash-Lite"
    ]


def test_a_provisional_decline_goes_once_the_catalog_carries_the_model() -> None:
    # The extractors stop flagging a carried model, so no flag names it.
    noted = COST_SCALE + f"- openai/GPT-6 Sol — {dd.NO_PRICE} (declined 2026-09-30)\n"
    _, cost_scale, actions = dd.dispose(SELECTOR, noted, [], TODAY)
    assert cost_scale == COST_SCALE
    assert [a.line() for a in actions] == [
        "- lifted: `openai/GPT-6 Sol` — the catalog carries it now"
    ]


def test_ids_and_names_follow_the_catalog() -> None:
    assert dd.new_id(_flag("openai", "gpt-6.1-sol"), "gpt-6-sol") == "gpt-6.1-sol"
    assert dd.new_id(_flag("anthropic", "Claude Opus 5.6"), "claude-opus-5-5") == "claude-opus-5-6"
    assert (
        dd.new_id(_flag("anthropic", "Claude Sonnet 5.5"), "claude-sonnet-5") == "claude-sonnet-5-5"
    )
    assert dd.new_id(_flag("google", "Gemini 3.9 Flash"), "gemini-3.8-flash") == "gemini-3.9-flash"
    assert dd.new_name(_flag("openai", "gpt-6.1-sol"), "GPT-6 Sol") == "GPT-6.1 Sol"
    assert dd.new_name(_flag("anthropic", "Claude Opus 5.6"), "Opus 5.5") == "Opus 5.6"


def test_flags_come_from_snapshots_and_tracker_docs(tmp_path: Path) -> None:
    snap = tmp_path / "catalog-openai.json"
    snap.write_text(
        json.dumps(
            {
                "provider": "openai",
                "unexpected_slugs": ["gpt-6.1-sol", "gpt-6.2-sol"],
                "discovered": [
                    {"slug": "gpt-6.1-sol", "input_price_per_1m": 2.0, "output_price_per_1m": 10.0}
                ],
            }
        )
    )
    tracker = tmp_path / "gemini-thinking.json"
    tracker.write_text(json.dumps({"unexpected_models": ["Gemini Robotics Er 2"]}))
    flags = dd.load_flags([snap], {"google": tracker})
    assert [(f.provider, f.slug, f.priced) for f in flags] == [
        ("google", "Gemini Robotics Er 2", False),
        ("openai", "gpt-6.1-sol", True),
        ("openai", "gpt-6.2-sol", False),
    ]


def test_the_report_names_each_disposition() -> None:
    _, _, actions = dd.dispose(
        SELECTOR,
        COST_SCALE,
        [
            _flag("openai", "gpt-6.1-sol", (2.0, 10.0)),
            _flag("google", "Gemini 3.9 Flash"),
            _flag("google", "Gemini Robotics Er 2"),
        ],
        TODAY,
    )
    report = dd.render_report(actions)
    assert "- added: `openai/gpt-6.1-sol` — as `gpt-6.1-sol`, the `gpt-6-sol` successor" in report
    assert f"- declined: `google/Gemini 3.9 Flash` — {dd.NO_PRICE}" in report
    assert f"- declined: `google/Gemini Robotics Er 2` — {dd.SPECIALIZED}" in report


def test_the_catalog_workflow_disposes_before_the_codex_sync_and_the_rating_guard() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "update-models.yml").read_text()
    # The curation pass sees today's flags and prices: the snapshots refresh first.
    assert wf.index("- name: Refresh provider-direct catalog snapshots") < wf.index(
        "- name: Refresh roadmodel catalog (Opus)"
    )
    at = wf.index("python update/dispose_discoveries.py --write")
    assert wf.index("prose_guard.py --apply") < wf.index("merge_catalog.py --write --base") < at
    assert at < wf.index("--sync-method codex-cli") < wf.index("rating_guard.py --apply")
    # The issue step runs after the overlay, so it flags only what is left.
    assert wf.index("Re-apply provider-direct models (federation overlay)") < wf.index(
        "Flag unfederated provider-direct models"
    )
    assert "update/.last-dispositions.md" in wf
