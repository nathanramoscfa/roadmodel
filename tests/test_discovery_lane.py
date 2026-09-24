"""The provider-page discovery lane reaches the curation model (update/discovery.py).

gpt-6-astra sat in ``update/catalog-openai.json``'s ``unexpected_slugs`` for
weeks while every catalog run reported ``<model-options>`` complete: #650 told
the curation prompt to add or decline each flagged model, but
``update_models.build_user_message`` never put the snapshots in front of the
model. These tests pin the whole lane: the extractors record each flagged
model with its price, the curation input carries every model the catalog
neither carries nor declines, a decline lives where the curation model can
write it and survives the file being regenerated, and the gate accepts the new
snapshot field.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = REPO_ROOT / "update"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
if str(UPDATE_DIR) not in sys.path:
    sys.path.insert(0, str(UPDATE_DIR))

import discovery  # noqa: E402


def _load(name: str) -> ModuleType:
    return importlib.reload(importlib.import_module(name))


SELECTOR = """
<model-options>
  <model id="claude-opus-5-5" name="Opus 5.5"
    input-price-per-1m="4" output-price-per-1m="20"/>
  <model id="gpt-5.6-sol" name="GPT-5.6 Sol"
    input-price-per-1m="4" output-price-per-1m="20"/>
</model-options>
"""

COST_SCALE = f"""# Model Tier Cost Scale

## Provider Jurisdictions

| Provider | Code |
|---|---|
| OpenAI | us |

{discovery.DECLINED_HEADING}

Intro paragraph.
- openai/gpt-5-nano — a smaller sibling the catalog does not recommend (declined 2026-09-24)
"""


def _snapshot(
    tmp_path: Path, provider: str, flagged: list[str], priced: list[dict[str, object]]
) -> Path:
    path = tmp_path / f"catalog-{provider}.json"
    path.write_text(
        json.dumps(
            {
                "provider": provider,
                "source_url": f"https://{provider}.example/pricing",
                "unexpected_slugs": flagged,
                "discovered": priced,
            }
        )
    )
    return path


def test_normalize_reads_ids_and_display_names_alike() -> None:
    assert discovery.normalize("Claude Opus 5.5") == discovery.normalize("claude-opus-5-5")
    assert discovery.normalize("Gemini 3.1 Flash-Lite") == "gemini-3-1-flash-lite"
    keys = discovery.catalog_keys(SELECTOR)
    assert {"claude-opus-5-5", "opus-5-5", "gpt-5-6-sol"} <= keys


def test_load_lists_what_the_catalog_neither_carries_nor_declines(tmp_path: Path) -> None:
    snaps = [
        _snapshot(
            tmp_path,
            "openai",
            ["gpt-6-astra", "gpt-5-nano", "gpt-5.6-sol"],
            [{"slug": "gpt-6-astra", "input_price_per_1m": 10.0, "output_price_per_1m": 50.0}],
        ),
        # A maker-prefixed display name matches the catalog's own name.
        _snapshot(tmp_path, "anthropic", ["Claude Opus 5.5", "Claude Mythos 5"], []),
    ]
    found = discovery.load(snaps, SELECTOR, COST_SCALE)
    assert [(d.provider, d.slug) for d in found] == [
        ("anthropic", "Claude Mythos 5"),
        ("openai", "gpt-6-astra"),
    ]
    astra = found[1]
    assert (astra.input_price_per_1m, astra.output_price_per_1m) == (10.0, 50.0)
    assert found[0].input_price_per_1m is None  # no price recorded: read the page


def test_the_block_names_every_entry_with_its_price_and_source(tmp_path: Path) -> None:
    snaps = [
        _snapshot(
            tmp_path,
            "openai",
            ["gpt-6-astra"],
            [{"slug": "gpt-6-astra", "input_price_per_1m": 10.0, "output_price_per_1m": 50.0}],
        )
    ]
    block = discovery.render_block(discovery.load(snaps, SELECTOR, COST_SCALE))
    assert block.startswith("<provider_discovery>") and block.endswith("</provider_discovery>")
    assert "- openai/gpt-6-astra — $10 input / $50 output per 1M tokens" in block
    assert "https://openai.example/pricing" in block
    assert discovery.render_block([]) == ""


def test_the_curation_input_carries_the_block() -> None:
    update_models = _load("update_models")
    block = "<provider_discovery>\n- openai/gpt-6-astra — x — source: y\n</provider_discovery>"
    msg = update_models.build_user_message(
        "SEL", "CS", [], [], target="cost_scale", discovery_block=block
    )
    assert block in msg
    assert "<provider_discovery>" not in update_models.build_user_message("SEL", "CS", [], [])


def test_every_committed_flag_reaches_the_curation_input() -> None:
    """The regression itself: what the committed snapshots flag, and the
    committed catalog neither carries nor declines, is in the message the
    curation model receives."""
    update_models = _load("update_models")
    selector = (REPO_ROOT / "docs" / "model-selector.txt").read_text()
    cost_scale = (REPO_ROOT / "docs" / "model-tier-cost-scale.md").read_text()
    pending = discovery.load(discovery.snapshot_paths(), selector, cost_scale)
    msg = update_models.build_user_message(
        selector,
        cost_scale,
        [],
        [],
        target="cost_scale",
        discovery_block=discovery.render_block(pending),
    )
    for d in pending:
        assert f"- {d.provider}/{d.slug} — " in msg
    carried = discovery.catalog_keys(selector)
    declined = {
        (x.provider, discovery.normalize(x.slug)) for x in discovery.parse_declined(cost_scale)
    }
    for path in discovery.snapshot_paths():
        snap = json.loads(path.read_text())
        for slug in snap.get("unexpected_slugs", []):
            handled = (
                discovery.normalize(slug) in carried
                or (
                    str(snap["provider"]),
                    discovery.normalize(slug),
                )
                in declined
            )
            assert handled or f"/{slug} — " in msg, (
                f"{path.name} flags {slug!r} but the input omits it"
            )


def test_a_decline_survives_the_file_being_regenerated() -> None:
    base = COST_SCALE
    # The regeneration kept the section but dropped the line.
    dropped_line = base.replace(
        "- openai/gpt-5-nano — a smaller sibling the catalog does not recommend (declined 2026-09-24)\n",
        "",
    )
    text, restored = discovery.preserve_declined(base, dropped_line)
    assert [d.slug for d in restored] == ["gpt-5-nano"]
    assert [d.slug for d in discovery.parse_declined(text)] == ["gpt-5-nano"]
    # The regeneration dropped the section whole: heading and intro come back too.
    dropped_section = base.split(discovery.DECLINED_HEADING)[0]
    text, restored = discovery.preserve_declined(base, dropped_section)
    assert discovery.DECLINED_HEADING in text and "Intro paragraph." in text
    assert [d.slug for d in discovery.parse_declined(text)] == ["gpt-5-nano"]
    # Nothing dropped: nothing changes.
    assert discovery.preserve_declined(base, base) == (base, [])


@pytest.mark.parametrize(
    ("module", "fixture", "slug", "price"),
    [
        ("extract_openai_catalog", "openai-pricing-sample.md", "gpt-6-astra", (10.0, 50.0)),
        ("extract_openai_catalog", "openai-pricing-sample.md", "gpt-7-nova", (12.0, 60.0)),
        (
            "extract_anthropic_catalog",
            "anthropic-pricing-sample.md",
            "Claude Mythos 5",
            (10.0, 50.0),
        ),
    ],
)
def test_extractors_record_a_flagged_models_price(
    module: str, fixture: str, slug: str, price: tuple[float, float]
) -> None:
    mod = _load(module)
    snap = mod.build_snapshot((FIXTURES / fixture).read_text(), source_url="file://sample")
    assert slug in snap["unexpected_slugs"]
    row = next(r for r in snap["discovered"] if r["slug"] == slug)
    assert (row["input_price_per_1m"], row["output_price_per_1m"]) == price


def test_the_gate_checks_the_discovered_field(tmp_path: Path) -> None:
    gate = _load("validate_catalog_conformance")
    snap = json.loads((UPDATE_DIR / "catalog-openai.json").read_text())
    assert gate.check_snapshot_schema(tmp_path / "catalog-openai.json", snap) == []
    snap["discovered"] = [{"slug": "not-flagged", "input_price_per_1m": 1.0}]
    assert any(
        "discovered entry" in f for f in gate.check_snapshot_schema(tmp_path / "x.json", snap)
    )
    snap["discovered"] = [{"slug": snap["unexpected_slugs"][0], "output_price_per_1m": -1}]
    assert any(
        "must be a positive number" in f
        for f in gate.check_snapshot_schema(tmp_path / "x.json", snap)
    )


def test_the_prompt_and_the_doc_name_the_same_block_and_section() -> None:
    prompt = (UPDATE_DIR / "prompt.md").read_text()
    assert "<provider_discovery>" in prompt
    assert discovery.DECLINED_HEADING.removeprefix("## ") in prompt
    assert "(declined YYYY-MM-DD)" in prompt
    cost_scale = (REPO_ROOT / "docs" / "model-tier-cost-scale.md").read_text()
    assert discovery.DECLINED_HEADING in cost_scale
