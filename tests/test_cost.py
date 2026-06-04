# tests/test_cost.py
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel.cost import (  # noqa: E402
    SessionCostEstimate,
    canonical_model_name,
    canonical_platform_name,
    compare_alternatives,
    estimate_session_cost,
)
from roadmodel.errors import AlternativeRejectedError  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
FIXTURE_CATALOG = FIXTURES / "cost_catalog.json"
FIXTURE_USER_CONTEXT = FIXTURES / "cost_user_context.md"


@pytest.fixture(autouse=True)
def _fixture_catalog_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(FIXTURE_CATALOG))
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(FIXTURE_USER_CONTEXT))


def test_canonical_model_name_resolves_id_or_name_to_display() -> None:
    # #174: the recommender LLM emits the model as either the catalog id/slug
    # or the display name; canonicalize both to the display name so the header,
    # settings, and comparison table agree.
    assert canonical_model_name("opus-test") == "Opus Test"
    assert canonical_model_name("Opus Test") == "Opus Test"


def test_canonical_platform_name_resolves_id_or_name_to_display() -> None:
    assert canonical_platform_name("codex-test") == "Codex"
    assert canonical_platform_name("Codex") == "Codex"


def test_canonical_names_passthrough_and_never_raise_on_unknown() -> None:
    # A label that is neither an id nor a catalog name is returned unchanged
    # (never raises) so a catalog miss degrades gracefully (#174).
    assert canonical_model_name("totally-made-up-model") == "totally-made-up-model"
    assert canonical_platform_name("Totally Made Up Platform") == "Totally Made Up Platform"


def test_estimate_per_token_path() -> None:
    estimate = estimate_session_cost(
        "grok-test",
        "xai-api-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert isinstance(estimate, SessionCostEstimate)
    assert estimate.funding_source == "per-token"
    assert estimate.subscription_label is None
    assert math.isclose(estimate.input_usd, 3.0)
    assert math.isclose(estimate.output_usd, 15.0)
    assert math.isclose(estimate.total_usd, 18.0)
    assert estimate.notes == []


def test_estimate_subscription_included() -> None:
    estimate = estimate_session_cost(
        "opus-test",
        "claude-code-test",
        input_tokens=500_000,
        output_tokens=250_000,
    )

    assert estimate.funding_source == "subscription-included"
    assert estimate.subscription_label is not None
    assert "claude.ai Max" in estimate.subscription_label
    assert math.isclose(estimate.input_usd, 5.0)
    assert math.isclose(estimate.output_usd, 12.5)
    assert math.isclose(estimate.total_usd, 17.5)


def test_estimate_subscription_pool() -> None:
    estimate = estimate_session_cost(
        "gpt-test",
        "cursor-test",
        input_tokens=1_000_000,
        output_tokens=500_000,
    )

    assert estimate.funding_source == "subscription-pool"
    assert estimate.subscription_label is not None
    assert "Cursor Ultra" in estimate.subscription_label


def test_estimate_subscription_or_key() -> None:
    estimate = estimate_session_cost(
        "gpt-test",
        "codex-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert estimate.funding_source == "subscription-or-key"
    assert estimate.subscription_label is not None
    assert "ChatGPT Pro" in estimate.subscription_label


def test_max_mode_2x_input_applied() -> None:
    baseline = estimate_session_cost(
        "gpt-test",
        "cursor-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        max_mode=False,
    )
    with_max = estimate_session_cost(
        "gpt-test",
        "cursor-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        max_mode=True,
    )

    assert math.isclose(baseline.input_usd, 2.0)
    assert math.isclose(with_max.input_usd, 4.0)
    assert math.isclose(with_max.output_usd, baseline.output_usd)
    assert math.isclose(with_max.total_usd, baseline.total_usd + baseline.input_usd)
    assert "Max Mode 2x input pricing applied" in with_max.notes


def test_max_mode_no_op_outside_cursor() -> None:
    baseline = estimate_session_cost(
        "opus-test",
        "claude-code-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        max_mode=False,
    )
    with_max = estimate_session_cost(
        "opus-test",
        "claude-code-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        max_mode=True,
    )

    assert math.isclose(with_max.input_usd, baseline.input_usd)
    assert math.isclose(with_max.total_usd, baseline.total_usd)
    assert any("Max Mode" in note and "Cursor" in note for note in with_max.notes)


def test_fast_variant_rejected() -> None:
    with pytest.raises(AlternativeRejectedError) as excinfo:
        estimate_session_cost(
            "Opus Test Fast",
            "claude-code-test",
            input_tokens=1_000,
            output_tokens=1_000,
        )

    err = excinfo.value
    assert err.model_id == "Opus Test Fast"
    assert err.standard_id == "Opus Test"
    assert "Opus Test" in str(err)


def test_compare_default_alternatives_ranking() -> None:
    estimates = compare_alternatives(
        "opus-test",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert len(estimates) == 3
    platform_ids = [est.platform_id for est in estimates]
    assert len(set(platform_ids)) == 3
    assert set(platform_ids) == {"claude-code-test", "cursor-test", "anthropic-api-test"}

    totals = [est.total_usd for est in estimates]
    assert totals == sorted(totals)
    assert estimates[0].total_usd == min(totals)


def test_compare_custom_alternatives() -> None:
    requested = ["openai-api-test", "cursor-test", "codex-test"]
    estimates = compare_alternatives(
        "gpt-test",
        input_tokens=2_000_000,
        output_tokens=1_000_000,
        alternatives=requested,
    )

    assert [est.platform_id for est in estimates] == requested


def test_unknown_model() -> None:
    with pytest.raises(ValueError) as excinfo:
        estimate_session_cost(
            "no-such-model",
            "claude-code-test",
            input_tokens=1_000,
            output_tokens=1_000,
        )
    assert "no-such-model" in str(excinfo.value)


def test_unknown_platform() -> None:
    with pytest.raises(ValueError) as excinfo:
        estimate_session_cost(
            "opus-test",
            "no-such-platform",
            input_tokens=1_000,
            output_tokens=1_000,
        )
    assert "no-such-platform" in str(excinfo.value)
