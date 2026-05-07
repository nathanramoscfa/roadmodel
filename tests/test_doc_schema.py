"""Schema and cross-doc consistency invariants on the committed docs.

Tier 2: structural invariants on each doc — every <model> element has
        all required attributes; every cost-scale provider table has
        the 7-column header.
Tier 3: cross-doc — every model in <model-options> with a fixed price
        appears in the cost-scale doc with matching prices and notes.

Catches: bot drift (e.g., dropping pricing-notes attribute), one-doc
updates that miss the other, and any schema change that wasn't
intentional.

Note: model-selector.txt is XML-shaped but not strict XML — its body
text legitimately contains backticked references to its own tag names
(e.g., `<task-categories>` in the selection-algorithm). We parse with
regex rather than ElementTree to handle this without rewriting the doc.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"

REQUIRED_MODEL_ATTRS = (
    "id",
    "name",
    "input-price-per-1m",
    "output-price-per-1m",
    "tier-coding",
    "tier-planning",
    "tier-agentic",
    "tier-multimodal",
    "tier-long-context",
    "tier-knowledge",
    "tier-speed",
    "headline-benchmarks",
    "pricing-notes",
    "best-for",
)
VALID_TIER_COSTS = {"very-high", "high", "medium", "low"}
COST_SCALE_REQUIRED_COLUMNS = (
    "Model",
    "Input",
    "Cache Write",
    "Cache Read",
    "Output",
    "Tier",
    "Notes",
)

SELECTOR_TO_COST_SCALE_NAME = {
    "opus-4.7": "Claude 4.7 Opus",
    "gpt-5.5": "GPT-5.5",
    "sonnet-4.6": "Claude 4.6 Sonnet",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.3-codex": "GPT-5.3 Codex",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
    "composer-2": "Composer 2",
    "grok-4.3": "Grok 4.3",
    "claude-4.5-haiku": "Claude 4.5 Haiku",
    "gpt-5.4-mini": "GPT-5.4 Mini",
    "gpt-5.4-nano": "GPT-5.4 Nano",
}

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_TIER_RE = re.compile(r'<tier\s+cost="([^"]+)"\s*>(.*?)</tier>', re.DOTALL)
_MODEL_RE = re.compile(r"<model\s+([^>]+?)\s*/>", re.DOTALL)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def _parse_models() -> list[tuple[str, dict[str, str]]]:
    """Return [(tier_cost, {attr: value}), ...] for every <model/> in <model-options>."""
    text = SELECTOR_PATH.read_text()
    options_match = _OPTIONS_RE.search(text)
    assert options_match, "<model-options>...</model-options> block not found"
    options_block = options_match.group(1)
    out: list[tuple[str, dict[str, str]]] = []
    for tier_m in _TIER_RE.finditer(options_block):
        tier_cost = tier_m.group(1)
        for model_m in _MODEL_RE.finditer(tier_m.group(2)):
            attrs = dict(_ATTR_RE.findall(model_m.group(1)))
            out.append((tier_cost, attrs))
    return out


def _norm_price(price: str) -> str:
    """Normalize "$5", "$5.00", "5" → "5.00" for stable comparison."""
    cleaned = price.strip().lstrip("$")
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return cleaned


def _parse_cost_scale_models() -> dict[str, dict[str, str]]:
    """Walk the markdown and return {model_name: {Input, Output, ..., Notes}}."""
    out: dict[str, dict[str, str]] = {}
    in_pricing_table = False
    header_cells: list[str] = []
    for line in COST_SCALE_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_pricing_table = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == "Model" and "Notes" in cells:
            header_cells = cells
            in_pricing_table = True
            continue
        if not in_pricing_table:
            continue
        if cells and cells[0].startswith("---"):
            continue
        if len(cells) != len(header_cells):
            continue
        row = dict(zip(header_cells, cells))
        out[row["Model"]] = row
    return out


# --- Tier 2: structural invariants ---


def test_at_least_one_model_present() -> None:
    models = _parse_models()
    assert models, "No <model/> elements found in <model-options>"


def test_every_model_has_all_required_attributes() -> None:
    failures: list[str] = []
    for _, attrs in _parse_models():
        missing = [a for a in REQUIRED_MODEL_ATTRS if a not in attrs]
        if missing:
            failures.append(f"<model id='{attrs.get('id', '<unknown>')}'> missing: {missing}")
    assert not failures, "Schema regressions on <model> elements:\n  " + "\n  ".join(failures)


def test_tier_groupings_use_known_cost_values() -> None:
    seen_costs = {tier_cost for tier_cost, _ in _parse_models()}
    unknown = seen_costs - VALID_TIER_COSTS
    assert not unknown, (
        f"Unknown <tier cost='...'> values: {unknown}; expected subset of {VALID_TIER_COSTS}"
    )


def test_cost_scale_provider_tables_have_required_columns() -> None:
    text = COST_SCALE_PATH.read_text()
    headers_found = re.findall(r"^\|\s*Model\s*\|.*\|\s*Notes\s*\|", text, re.MULTILINE)
    assert len(headers_found) >= 5, (
        f"Expected at least 5 provider tables with full Model/.../Notes headers, "
        f"found {len(headers_found)}"
    )
    for header in headers_found:
        cells = [c.strip() for c in header.strip("|").split("|")]
        missing = [c for c in COST_SCALE_REQUIRED_COLUMNS if c not in cells]
        assert not missing, f"Provider table header missing columns {missing}: {header}"


# --- Tier 3: cross-doc consistency ---


def test_every_priced_selector_model_is_in_cost_scale() -> None:
    cost_scale = _parse_cost_scale_models()
    missing: list[str] = []
    for _, attrs in _parse_models():
        sel_id = attrs.get("id", "")
        if sel_id not in SELECTOR_TO_COST_SCALE_NAME:
            continue
        cs_name = SELECTOR_TO_COST_SCALE_NAME[sel_id]
        if cs_name not in cost_scale:
            missing.append(f"{sel_id} (expects '{cs_name}' in cost-scale)")
    assert not missing, "Selector models absent from cost-scale tables:\n  " + "\n  ".join(missing)


def test_selector_pricing_matches_cost_scale_pricing() -> None:
    cost_scale = _parse_cost_scale_models()
    mismatches: list[str] = []
    for _, attrs in _parse_models():
        sel_id = attrs.get("id", "")
        if sel_id not in SELECTOR_TO_COST_SCALE_NAME:
            continue
        cs_name = SELECTOR_TO_COST_SCALE_NAME[sel_id]
        if cs_name not in cost_scale:
            continue
        cs_row = cost_scale[cs_name]
        sel_in = _norm_price(attrs.get("input-price-per-1m", ""))
        sel_out = _norm_price(attrs.get("output-price-per-1m", ""))
        cs_in = _norm_price(cs_row.get("Input", ""))
        cs_out = _norm_price(cs_row.get("Output", ""))
        if sel_in != cs_in:
            mismatches.append(f"{sel_id} input: selector={sel_in}, cost-scale={cs_in}")
        if sel_out != cs_out:
            mismatches.append(f"{sel_id} output: selector={sel_out}, cost-scale={cs_out}")
    assert not mismatches, "Cross-doc price mismatches:\n  " + "\n  ".join(mismatches)


def test_selector_pricing_notes_match_cost_scale_notes() -> None:
    cost_scale = _parse_cost_scale_models()
    mismatches: list[str] = []
    for _, attrs in _parse_models():
        sel_id = attrs.get("id", "")
        if sel_id not in SELECTOR_TO_COST_SCALE_NAME:
            continue
        cs_name = SELECTOR_TO_COST_SCALE_NAME[sel_id]
        if cs_name not in cost_scale:
            continue
        sel_notes = (attrs.get("pricing-notes") or "").strip()
        cs_notes = cost_scale[cs_name].get("Notes", "").strip()
        if sel_notes != cs_notes:
            mismatches.append(
                f"{sel_id}: selector pricing-notes='{sel_notes}' vs cost-scale Notes='{cs_notes}'"
            )
    assert not mismatches, (
        "Cross-doc pricing-notes mismatches (these should be byte-identical):\n  "
        + "\n  ".join(mismatches)
    )


def test_selector_tier_classification_matches_output_price() -> None:
    """Output price must place each model in the correct <tier cost='...'>
    bucket per the documented Low/Medium/High/Very High thresholds.
    Catches: bot moving a model into the wrong bucket after a price change.
    """
    misplaced: list[str] = []
    for tier_cost, attrs in _parse_models():
        sel_id = attrs.get("id", "")
        price_str = attrs.get("output-price-per-1m", "")
        # routing pseudo-models have non-numeric prices; skip
        if "varies" in price_str or "~" in price_str:
            continue
        try:
            price = float(price_str.lstrip("$"))
        except ValueError:
            continue
        if price < 10:
            expected = "low"
        elif price < 15:
            expected = "medium"
        elif price < 25:
            expected = "high"
        else:
            expected = "very-high"
        if expected != tier_cost:
            misplaced.append(
                f"{sel_id} output=${price:.2f} is in <tier cost='{tier_cost}'> "
                f"but should be '{expected}'"
            )
    assert not misplaced, "Tier classification errors:\n  " + "\n  ".join(misplaced)
