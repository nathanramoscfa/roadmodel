"""Schema and cross-doc consistency invariants on the committed docs.

Tier 2: structural invariants on each doc — every <model> element has
        all required attributes; every cost-scale provider table has
        the 7-column header.
Tier 3: cross-doc — every model in <model-options> with a fixed price
        appears in the cost-scale doc with matching prices and notes.

Catches: bot drift (e.g., dropping pricing-notes attribute), one-doc
updates that miss the other, and any schema change that wasn't
intentional.

Note: ``docs/model-selector.txt`` is XML-shaped but not strict XML — its body
text legitimately contains backticked references to its own tag names
(e.g., `<task-categories>` in the selection-algorithm). We parse with
regex rather than ElementTree to handle this without rewriting the doc.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
SELECTOR_MD_PATH = REPO_ROOT / "docs" / "model-selector.md"
COST_SCALE_PATH = REPO_ROOT / "docs" / "model-tier-cost-scale.md"
PROMPT_PATH = REPO_ROOT / "update" / "prompt.md"

REQUIRED_MODEL_ATTRS = (
    "id",
    "name",
    "jurisdiction",
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
VALID_JURISDICTIONS = {
    "us",
    "eu",
    "uk",
    "ca",
    "au",
    "jp",
    "kr",
    "cn",
    "ru",
    "unknown",
}
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
    "opus-4.8": "Claude Opus 4.8",
    "gpt-5.5": "GPT-5.5",
    "sonnet-4.6": "Claude 4.6 Sonnet",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.3-codex": "GPT-5.3 Codex",
    "gpt-5.2": "GPT-5.2",
    "gpt-5.1-codex": "GPT-5.1 Codex",
    "gpt-5": "GPT-5",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
    "gemini-3-pro": "Gemini 3 Pro",
    "gemini-3-flash": "Gemini 3 Flash",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "composer-2": "Composer 2",
    "composer-2.5": "Composer 2.5",
    # grok-4.3 is intentionally absent: xAI was delisted from Cursor's pricing
    # page 2026-07-14, so grok-4.3 is now provider-direct-only (xai-api), exempt
    # from cost-scale sync like DeepSeek. See update/build_catalog.py.
    "kimi-k2.5": "Kimi K2.5",
    "claude-4.5-haiku": "Claude 4.5 Haiku",
    "gpt-5.4-mini": "GPT-5.4 Mini",
    "gpt-5-mini": "GPT-5 Mini",
    "gpt-5.4-nano": "GPT-5.4 Nano",
}

_OPTIONS_RE = re.compile(r"<model-options>(.*?)</model-options>", re.DOTALL)
_TIER_RE = re.compile(r'<tier\s+cost="([^"]+)"\s*>(.*?)</tier>', re.DOTALL)
_MODEL_RE = re.compile(r"<model\s+([^>]+?)\s*/>", re.DOTALL)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_METHOD_RE = re.compile(r"<method\s+([^>]+?)\s*/>", re.DOTALL)
_ACCESS_METHODS_RE = re.compile(r"<access-methods>(.*?)</access-methods>", re.DOTALL)


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
        row = dict(zip(header_cells, cells, strict=True))
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


def test_every_model_jurisdiction_is_valid() -> None:
    """Every <model> jurisdiction attribute must use a known code from
    VALID_JURISDICTIONS. Catches typos and unmapped new providers that
    slipped past the auto-fill rule in update/prompt.md.
    """
    failures: list[str] = []
    for _, attrs in _parse_models():
        sel_id = attrs.get("id", "<unknown>")
        jurisdiction = attrs.get("jurisdiction", "")
        if jurisdiction not in VALID_JURISDICTIONS:
            failures.append(
                f"<model id='{sel_id}'> jurisdiction='{jurisdiction}' "
                f"not in {sorted(VALID_JURISDICTIONS)}"
            )
    assert not failures, "Jurisdiction code regressions:\n  " + "\n  ".join(failures)


def test_every_method_provider_jurisdiction_is_valid() -> None:
    """Every <method> provider-jurisdiction attribute must use a known
    code. Mirrors test_every_model_jurisdiction_is_valid for the
    access-methods block.
    """
    text = SELECTOR_PATH.read_text()
    access_match = _ACCESS_METHODS_RE.search(text)
    assert access_match, "<access-methods>...</access-methods> block not found"
    failures: list[str] = []
    for method_m in _METHOD_RE.finditer(access_match.group(1)):
        attrs = dict(_ATTR_RE.findall(method_m.group(1)))
        method_id = attrs.get("id", "<unknown>")
        jurisdiction = attrs.get("provider-jurisdiction", "")
        if jurisdiction not in VALID_JURISDICTIONS:
            failures.append(
                f"<method id='{method_id}'> provider-jurisdiction='{jurisdiction}' "
                f"not in {sorted(VALID_JURISDICTIONS)}"
            )
    assert not failures, "Method jurisdiction code regressions:\n  " + "\n  ".join(failures)


def test_no_routing_meta_models_in_options() -> None:
    """Routing meta-models (auto, premium) are NOT enumerated in
    <model-options> as of 2026-05-21 — see <jurisdiction-context>.
    Catches accidental re-addition by an Opus auto-add or hand-edit.
    """
    forbidden = {"auto", "premium"}
    ids = {attrs.get("id", "") for _, attrs in _parse_models()}
    leaked = forbidden & ids
    assert not leaked, (
        f"Routing meta-models re-introduced into <model-options>: {leaked}. "
        f"See update/prompt.md 'Routing meta-models' rule."
    )


def test_every_method_supports_models_references_valid_models() -> None:
    """Every model id in a <method> supports-models attribute must exist
    in <model-options>. Catches drift where the weekly cron's
    supports-models refresh adds a model that isn't catalog-tracked,
    or where editorial changes to <model-options> orphan a reference.
    """
    text = SELECTOR_PATH.read_text()
    access_match = _ACCESS_METHODS_RE.search(text)
    assert access_match, "<access-methods>...</access-methods> block not found"
    catalog_ids = {attrs.get("id", "") for _, attrs in _parse_models()}
    catalog_ids.discard("")
    failures: list[str] = []
    for method_m in _METHOD_RE.finditer(access_match.group(1)):
        attrs = dict(_ATTR_RE.findall(method_m.group(1)))
        method_id = attrs.get("id", "<unknown>")
        supports = [s.strip() for s in attrs.get("supports-models", "").split(",") if s.strip()]
        for model_id in supports:
            if model_id not in catalog_ids:
                failures.append(
                    f"<method id='{method_id}'> supports-models references unknown model '{model_id}'"
                )
    assert not failures, "supports-models referential integrity broken:\n  " + "\n  ".join(failures)


# --- Availability filter (Step 0a) invariants ---

_UNAVAILABLE_ID_RE = re.compile(r"^\s*-\s*`([a-z0-9.\-]+)`", re.MULTILINE)


def _element_body(tag: str) -> str:
    """Return the inner text of the real <tag>...</tag> block element.

    Anchors on the tag alone on its line, so inline backticked references to
    the same tag name (which the doc legitimately contains — see the module
    docstring) are never mistaken for the element itself.
    """
    text = SELECTOR_PATH.read_text()
    match = re.search(rf"(?m)^\s*<{tag}>\s*$(.*?)^\s*</{tag}>\s*$", text, re.DOTALL)
    assert match, f"<{tag}>...</{tag}> block element not found"
    return match.group(1)


def _unavailable_model_ids() -> list[str]:
    return _UNAVAILABLE_ID_RE.findall(_element_body("availability-context"))


def test_availability_context_lists_valid_model_ids() -> None:
    """Every model id flagged unavailable in <availability-context> must be a
    real <model-options> id; a typo would silently disable nothing."""
    unavailable = _unavailable_model_ids()
    assert unavailable, "<availability-context> lists no unavailable model ids"
    catalog_ids = {attrs.get("id", "") for _, attrs in _parse_models()}
    unknown = [i for i in unavailable if i not in catalog_ids]
    assert not unknown, f"<availability-context> references unknown model ids: {unknown}"


def test_unavailable_models_absent_from_selection_algorithm() -> None:
    """An unavailable model must not appear in <selection-algorithm>'s candidate
    enumerations, or it could be re-introduced as a pick despite the Step 0a
    availability filter."""
    unavailable = _unavailable_model_ids()
    algo = _element_body("selection-algorithm")
    leaked = [i for i in unavailable if i in algo]
    assert not leaked, (
        f"unavailable model id(s) {leaked} appear in <selection-algorithm> — "
        "remove them from the candidate lists so Step 0a stays consistent"
    )


def test_prompt_has_lifecycle_rules() -> None:
    """update/prompt.md must contain the Model lifecycle rules. Without
    them, a future refresh could silently remove a model when a costlier
    successor in the same series appears (e.g. drop GPT-5.4 because
    GPT-5.5 launched at 2x the price). This test guards against
    accidental deletion of those rules from the prompt.

    Sentinel phrases below are intentionally distinctive — they are
    headers and warning patterns that are unlikely to be reworded
    without an explicit rule rewrite.
    """
    prompt = PROMPT_PATH.read_text()
    required = [
        "Model lifecycle in",
        "Adding new models",
        "Removing models",
        "Same series",
        "Selection-algorithm guardrail sync",
        "superseded:",
        "discontinued by Cursor:",
    ]
    missing = [phrase for phrase in required if phrase not in prompt]
    assert not missing, (
        "update/prompt.md is missing Model lifecycle phrases: "
        f"{missing}. Restore them or this automation may silently drop "
        "a model when a costlier successor appears."
    )


def test_prompt_has_subscription_refresh_rules() -> None:
    """update/prompt.md must contain the Subscription tiers rebuild rules.
    Without them, the cron could rebuild the table without per-provider
    sanity guards, silently delete current tiers on a transient parse
    failure, or refresh the marker without evidence. This test guards
    against accidental deletion of those rules.
    """
    prompt = PROMPT_PATH.read_text()
    required = [
        "Subscription tiers",
        "web_search",
        "Provider → access-methods mapping",
        # The Annual column is EDITORIAL (issue #315): the cron must NOT fetch or
        # originate an annual price (a plausibly-shaped value is indistinguishable
        # from a hallucination). Guard the contract so a future prompt regen can't
        # re-introduce annual fetching — the deterministic carry-forward owns it.
        "Annual column (EDITORIAL — leave every cell verbatim)",
        "carry_forward_annual_column",
        "Rebuild procedure (per provider)",
        "Sanity guards",
        "subscription tier added:",
        "subscription tier removed:",
        "subscription price updated:",
        "subscription coverage updated:",
        "subscription tier refresh skipped",
        "subscription tier refresh halted",
        "subscription tier discovered with unmapped access surface (manual review required):",
        "subscription-tiers-reviewed:",
    ]
    missing = [phrase for phrase in required if phrase not in prompt]
    assert not missing, (
        "update/prompt.md is missing Subscription tiers rebuild phrases: "
        f"{missing}. Restore them or the cron may rebuild the table "
        "without sanity guards or refresh the marker without evidence."
    )


def test_backup_step_requires_different_provider() -> None:
    """Step 7 must state the cross-provider BACKUP rule as a HARD requirement
    (not a soft "prefer"). The backup exists so a single provider's outage or
    access block can't take out both picks; a same-provider fallback defeats
    that. This guards against a refresh silently softening the rule back to a
    preference (the Fable 5 -> Opus 4.8, both Anthropic, regression class).
    """
    text = SELECTOR_PATH.read_text()
    # The Step 7 block, isolated so we assert on the backup rule specifically.
    assert "Name a backup model" in text, "Step 7 backup section is missing"
    required = [
        "MUST be from a DIFFERENT provider/family",
        "HARD requirement",
        "NEVER acceptable",
        # The option-A fallback: drop tier rather than name no backup.
        "DROP the",
    ]
    missing = [phrase for phrase in required if phrase not in text]
    assert not missing, (
        "docs/model-selector.txt Step 7 is missing the hard cross-provider "
        f"BACKUP phrases: {missing}. The backup must be a different "
        "provider/family than the primary (hard rule), dropping tier if "
        "needed to stay cross-provider."
    )
    # The old soft phrasing must not creep back in.
    assert "Prefer a model from a DIFFERENT provider" not in text, (
        "Step 7 still contains the SOFT 'Prefer a model from a DIFFERENT "
        "provider' phrasing — the cross-provider backup rule must be HARD."
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


def test_roadmodel_catalog_md_in_sync_with_bundled_txt() -> None:
    """``docs/model-selector.md`` is auto-generated from ``docs/model-selector.txt``
    by update/render_md.py. Fail if the committed .md does not match what
    the renderer would produce from the current .txt.

    Catches: a hand-edit to the .md, or a .txt change that wasn't followed
    by `python update/render_md.py`.
    """
    sys.path.insert(0, str(REPO_ROOT / "update"))
    try:
        from render_md import render
    finally:
        sys.path.pop(0)
    expected = render(SELECTOR_PATH.read_text())
    actual = SELECTOR_MD_PATH.read_text()
    assert actual == expected, (
        "docs/model-selector.md is out of sync with docs/model-selector.txt. "
        "Regenerate with: python update/render_md.py"
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
