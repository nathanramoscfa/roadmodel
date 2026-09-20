# tests/test_local_aggregator_access.py
"""Phase 4.10 Step 1 — `ollama` (local) and `openrouter` (aggregator) access
methods.

Pins the whole feature end to end:

- the selector carries both `<method>` entries with the exact attribute values
  the roadmap specifies, every `supports-models` id is a catalogued model, the
  `local` billing type is defined, and the three `<access-selection>` rule
  changes (Step A0 pass / Step B drop / Step C $0 tier) plus the verbatim
  quantization caveat clause are present;
- `cost.model_provider` never returns an aggregator as the maker of a model
  that has a provider-direct method, and returns it only for a model reachable
  solely through the aggregator (fixture catalog);
- `cost._resolve_funding` returns `local` / `unfunded-local` from the
  user-context declaration and leaves every other billing type unchanged;
- `cost._parse_local_models` / `cost._local_runtime_present` parse the bundled
  example (No, empty) and a fixture that declares two tags;
- the cost panel renders `$0 — local hardware` for a funded local platform
  and never a per-token estimate, and OMITS an unfunded local platform;
- the bundled example context and the single-platform contract fixture
  (`tests/test_user_stack_contract.py`) declare neither method, so neither
  can be funded there.

Every monkeypatched mock is contract-validated against the real callable's
signature and return shape (feedback_monkeypatched_contract_validation).
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
UPDATE_DIR = REPO_ROOT / "update"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from test_user_stack_contract import USER_CONTEXT as SINGLE_PLATFORM_CONTEXT  # noqa: E402

from roadmodel import cli, cost  # noqa: E402
from roadmodel import recommend as recommend_module  # noqa: E402

SELECTOR_PATH = REPO_ROOT / "docs" / "model-selector.txt"
EXAMPLE_CONTEXT_PATH = REPO_ROOT / "docs" / "user-context.example.md"
FIXTURES = REPO_ROOT / "tests" / "fixtures"

# Anchor on the element ALONE on its line: the prose legitimately mentions
# `<access-methods>` etc. in backticks long before the real element opens.
_ACCESS_METHODS_RE = re.compile(
    r"(?m)^\s*<access-methods>\s*$(.*?)^\s*</access-methods>\s*$", re.DOTALL
)
_ACCESS_SELECTION_RE = re.compile(
    r"(?m)^\s*<access-selection>\s*$(.*?)^\s*</access-selection>\s*$", re.DOTALL
)
_OBJECTIVE_RE = re.compile(r"(?m)^\s*<objective>\s*$(.*?)^\s*</objective>\s*$", re.DOTALL)
_METHOD_RE = re.compile(r"<method\s+(.*?)/>", re.DOTALL)
_MODEL_ID_RE = re.compile(r'<model\s+id="([^"]+)"')
_ATTR_RE = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"', re.DOTALL)

CAVEAT_CLAUSE = (
    "local quantized weights run below the catalog tier ratings; "
    "treat coding and reasoning as one tier lower than listed"
)


def _selector() -> str:
    return SELECTOR_PATH.read_text(encoding="utf-8")


def _methods() -> dict[str, dict[str, str]]:
    block = _ACCESS_METHODS_RE.search(_selector())
    assert block, "<access-methods> block not found"
    out: dict[str, dict[str, str]] = {}
    for m in _METHOD_RE.finditer(block.group(1)):
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        out[attrs["id"]] = attrs
    return out


def _catalog_model_ids() -> set[str]:
    return set(_MODEL_ID_RE.findall(_selector()))


# --------------------------------------------------------------------------- #
# Selector: the two <method> entries
# --------------------------------------------------------------------------- #


def test_ollama_method_has_the_specified_attributes() -> None:
    m = _methods()["ollama"]
    assert m["name"] == "Ollama (local)"
    assert m["provider"] == "ollama"
    assert m["billing"] == "local"
    assert m["provider-jurisdiction"] == "local"
    assert m["requires"] == "ollama-local"
    assert m["exposes-max-mode"] == "no"
    assert m["exposes-thinking"] == "yes"
    assert m["exposes-orchestration"] == "no"
    # best-for states the hardware / quantization caveat and the thinking dial.
    best_for = m["best-for"]
    assert "quantiz" in best_for.lower()
    assert "reasoning_effort" in best_for
    assert "one tier below" in best_for


def test_openrouter_method_has_the_specified_attributes() -> None:
    m = _methods()["openrouter"]
    assert m["name"] == "OpenRouter"
    assert m["provider"] == "openrouter"
    assert m["billing"] == "per-token"
    assert m["provider-jurisdiction"] == "us"
    assert m["requires"] == "openrouter-api-key"
    assert m["exposes-max-mode"] == "no"
    assert m["exposes-thinking"] == "yes"
    assert m["exposes-orchestration"] == "no"
    best_for = m["best-for"]
    # Point-in-time snapshot, fee-inclusive floor, routing + jurisdiction note.
    assert "POINT-IN-TIME" in best_for
    assert "platform fee" in best_for
    assert "FLOOR" in best_for
    assert "Step 0b" in best_for


@pytest.mark.parametrize("method_id", ["ollama", "openrouter"])
def test_every_supports_models_id_is_catalogued(method_id: str) -> None:
    supports = [s.strip() for s in _methods()[method_id]["supports-models"].split(",") if s]
    assert supports, f"{method_id} supports-models is empty"
    assert len(supports) == len(set(supports)), f"{method_id} lists a model twice"
    unknown = sorted(set(supports) - _catalog_model_ids())
    assert not unknown, f"{method_id} supports-models references unknown models: {unknown}"


def test_ollama_supports_only_models_that_never_resolve_to_it_as_maker() -> None:
    """Every locally-runnable model is ALSO reachable through a provider-direct
    method or the Cursor pool, so the maker never resolves to `ollama` (the
    backup guard relies on that). Closed-weight models never appear here."""
    methods = _methods()
    elsewhere: set[str] = set()
    for mid, attrs in methods.items():
        if mid == "ollama":
            continue
        elsewhere.update(s.strip() for s in attrs["supports-models"].split(",") if s.strip())
    local = {s.strip() for s in methods["ollama"]["supports-models"].split(",") if s.strip()}
    assert local <= elsewhere, (
        f"ollama-only models would resolve to maker 'ollama': {local - elsewhere}"
    )
    assert all(cost.model_provider(mid) != "ollama" for mid in local)
    closed = {"claude-opus-5", "opus-4.8", "gpt-5.5", "gemini-3.1-pro", "composer-2.5", "codestral"}
    assert not (local & closed), f"closed-weight models listed on ollama: {local & closed}"


def test_local_billing_type_is_defined_in_the_preamble() -> None:
    block = _ACCESS_METHODS_RE.search(_selector())
    assert block
    preamble = block.group(1)[: block.group(1).find("<method")]
    assert "subscription-or-key, local)" in preamble
    assert re.search(r"^\s*- local — self-hosted weights", preamble, re.MULTILINE)
    assert "$0 per" in preamble and "quantization" in preamble


# --------------------------------------------------------------------------- #
# Selector: the access-selection rule changes
# --------------------------------------------------------------------------- #


def _access_selection() -> str:
    m = _ACCESS_SELECTION_RE.search(_selector())
    assert m
    return m.group(1)


def test_step_a0_admits_local_under_every_jurisdiction_list() -> None:
    body = _access_selection()
    a0 = body[body.find("Step A0 —") : body.find("Step A —")]
    assert 'provider-jurisdiction="local"' in a0
    assert "passes EVERY allowed-jurisdictions" in a0
    assert "`unknown` stays" in a0 and "forbidden" in a0


def test_step_b_drops_an_unfunded_local_method_with_a00_precedence() -> None:
    body = _access_selection()
    step_b = body[body.find("Step B —") : body.find("Step C —")]
    assert "EXCEPTION — `local` billing" in step_b
    assert "otherwise DROP it" in step_b
    assert "same precedence as the Step A00 operator list" in step_b
    assert "DISCLOSURE" in step_b
    # The guardrail below now yields to THREE hard filters.
    assert "There are THREE" in body and "Step B `local` exception" in body


def test_step_c_ranks_a_funded_local_method_in_the_zero_dollar_tier() -> None:
    body = _access_selection()
    step_c = body[body.find("Step C —") : body.find("Step D —")]
    tier_one = step_c[step_c.find("1. ") : step_c.find("2. ")]
    assert "FUNDED `local` method" in tier_one
    assert "$0" in tier_one


def test_local_pick_rationale_carries_the_verbatim_caveat_clause() -> None:
    body = _access_selection()
    assert body.count(CAVEAT_CLAUSE) == 1, "caveat clause must be stated verbatim, once"
    step_g = body[body.find("Step G —") : body.find("Guardrails:")]
    assert "quantization caveat clause" in step_g


def test_flat_funding_gate_treats_local_as_a_separate_funding_class() -> None:
    """Without this the gate would OPEN on a Max-funded Claude candidate and
    HOLD the tier, and a Cost-priority prompt could never reach a local pick."""
    obj = _OBJECTIVE_RE.search(_selector())
    assert obj
    text = obj.group(1)
    assert "LOCAL MODELS AND THE GATE" in text
    assert "DIFFERENT funding class" in text
    assert "the gate is CLOSED for it" in text
    assert "minimum-resource pick" in text


def test_selector_rules_reach_the_engine_prompt() -> None:
    system, _ = recommend_module.build_prompt(
        "Write a small CLI that renames files.", user_context_text=SINGLE_PLATFORM_CONTEXT
    )
    assert CAVEAT_CLAUSE in system
    assert "EXCEPTION — `local` billing" in system
    assert "LOCAL MODELS AND THE GATE" in system
    assert 'id="ollama"' in system and 'id="openrouter"' in system


# --------------------------------------------------------------------------- #
# Maker resolution with a per-token aggregator + local runtime
# --------------------------------------------------------------------------- #


def _write_fixture_catalog(tmp_path: Path) -> Path:
    """A catalog where `oss-test` is reachable direct (groq) + openrouter +
    ollama, `only-router-test` is reachable ONLY via openrouter, and
    `only-local-test` ONLY via ollama."""
    catalog: dict[str, Any] = {
        "models": [
            {
                "id": "oss-test",
                "name": "OSS Test",
                "input_price_per_1m": 0.1,
                "output_price_per_1m": 0.5,
                "jurisdiction": "us",
            },
            {
                "id": "only-router-test",
                "name": "Only Router",
                "input_price_per_1m": 1.0,
                "output_price_per_1m": 2.0,
                "jurisdiction": "us",
            },
            {
                "id": "only-local-test",
                "name": "Only Local",
                "input_price_per_1m": 1.0,
                "output_price_per_1m": 2.0,
                "jurisdiction": "us",
            },
            {
                "id": "opus-test",
                "name": "Opus Test",
                "input_price_per_1m": 5.0,
                "output_price_per_1m": 25.0,
                "jurisdiction": "us",
            },
        ],
        "access_methods": [
            {
                "id": "groq-test",
                "name": "Groq API",
                "provider": "groq",
                "billing": "per-token",
                "requires": "groq-api-key",
                "supports_models": ["oss-test"],
                "exposes_max_mode": "no",
                "exposes_thinking": "yes",
            },
            {
                "id": "anthropic-api-test",
                "name": "Anthropic API",
                "provider": "anthropic",
                "billing": "per-token",
                "requires": "anthropic-api-key",
                "supports_models": ["opus-test"],
                "exposes_max_mode": "no",
                "exposes_thinking": "yes",
            },
            {
                "id": "openrouter",
                "name": "OpenRouter",
                "provider": "openrouter",
                "billing": "per-token",
                "requires": "openrouter-api-key",
                "supports_models": ["oss-test", "only-router-test", "opus-test"],
                "exposes_max_mode": "no",
                "exposes_thinking": "yes",
            },
            {
                "id": "ollama",
                "name": "Ollama (local)",
                "provider": "ollama",
                "billing": "local",
                "requires": "ollama-local",
                "supports_models": ["oss-test", "only-local-test"],
                "exposes_max_mode": "no",
                "exposes_thinking": "yes",
            },
        ],
        "subscription_tiers": [],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


LOCAL_DECLARED_CONTEXT = """# User Context (fixture)

## Active API keys

| Provider   | Key present | Notes |
| ---------- | ----------- | ----- |
| Anthropic  | No          |       |
| OpenRouter | Yes         | aggregator key |

## Local models (Ollama)

Prose the operator may edit freely.

| Runtime          | Present |
| ---------------- | ------- |
| Ollama installed | Yes     |

| Catalog model id | Tag pulled        | Quantization | Notes |
| ---------------- | ----------------- | ------------ | ----- |
| oss-test         | oss-test:20b      | MXFP4        | fits  |
| `only-local-test` | `only-local:7b-q4` | Q4_K_M     | also fits |
<!-- | commented-out-model | nope:1b | Q2 | must be ignored | -->

## Budget priority and speed posture

**Budget priority:** `cheap`
"""


@pytest.fixture
def fixture_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    catalog = _write_fixture_catalog(tmp_path)
    ctx = tmp_path / "user-context.md"
    ctx.write_text(LOCAL_DECLARED_CONTEXT, encoding="utf-8")
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(ctx))
    return ctx


def test_aggregator_set_contains_openrouter_and_the_local_runtime() -> None:
    assert "openrouter" in cost._AGGREGATOR_PROVIDERS
    assert "ollama" in cost._AGGREGATOR_PROVIDERS
    assert "cursor" in cost._AGGREGATOR_PROVIDERS


def test_model_provider_never_returns_openrouter_for_a_direct_model(fixture_env: Path) -> None:
    assert cost.model_provider("oss-test") == "groq"
    assert cost.model_provider("opus-test") == "anthropic"


def test_model_provider_returns_openrouter_only_for_router_only_models(fixture_env: Path) -> None:
    assert cost.model_provider("only-router-test") == "openrouter"
    assert cost.model_provider("only-local-test") == "ollama"


def test_real_catalog_makers_are_never_openrouter_or_ollama() -> None:
    """On the shipped catalog every model has a provider-direct method (or is
    Cursor-only), so the aggregator can never surface as a maker."""
    catalog = json.loads((REPO_ROOT / "docs" / "catalog.json").read_text(encoding="utf-8"))
    makers = {m["id"]: cost.model_provider(m["id"]) for m in catalog["models"]}
    bad = {mid: mk for mid, mk in makers.items() if mk in {"openrouter", "ollama"}}
    assert not bad, bad
    assert None not in makers.values(), [mid for mid, mk in makers.items() if mk is None]
    # Cursor-only / aggregator-only models keep the pre-4.10 answer (`cursor`),
    # so Kimi-vs-Kimi is still a same-maker collision for the backup guard.
    assert makers["kimi-k3"] == makers["kimi-k2.7-code"] == "cursor"
    assert cost.same_provider("kimi-k3", "kimi-k2.7-code")


def test_conformance_gate_aggregator_set_mirrors_cost_module() -> None:
    """update/validate_catalog_conformance.py re-implements the maker rule so
    update/ stays standalone; pin the two sets together."""
    src = (UPDATE_DIR / "validate_catalog_conformance.py").read_text(encoding="utf-8")
    m = re.search(r"aggregators = \{([^}]*)\}", src)
    assert m
    gate_set = {s.strip().strip("\"'") for s in m.group(1).split(",") if s.strip()}
    assert gate_set == set(cost._AGGREGATOR_PROVIDERS)


def test_backup_substitution_skips_local_only_candidates(fixture_env: Path) -> None:
    """A model reachable only via a local runtime the user may not have is
    never proposed as the cross-provider backup."""
    backup = cost.suggest_cross_provider_backup("opus-test", allowed_jurisdictions=["us"])
    assert backup != "Only Local"
    # The router-only model is still a legitimate (per-token) substitute.
    assert backup in {"OSS Test", "Only Router"}


# --------------------------------------------------------------------------- #
# Funding resolution for `local`
# --------------------------------------------------------------------------- #


def _method(fixture_env: Path, method_id: str) -> dict[str, Any]:
    return cost._resolve_method(method_id, cost._load_catalog())


def test_resolve_funding_local_when_runtime_present_and_model_pulled(fixture_env: Path) -> None:
    catalog = cost._load_catalog()
    text = fixture_env.read_text(encoding="utf-8")
    method = cost._with_model(_method(fixture_env, "ollama"), "oss-test")
    assert cost._resolve_funding(method, catalog, text) == ("local", None)


def test_resolve_funding_unfunded_local_when_model_not_pulled(fixture_env: Path) -> None:
    catalog = cost._load_catalog()
    text = fixture_env.read_text(encoding="utf-8")
    method = cost._with_model(_method(fixture_env, "ollama"), "opus-test")
    assert cost._resolve_funding(method, catalog, text) == ("unfunded-local", None)


def test_resolve_funding_unfunded_local_when_runtime_absent(fixture_env: Path) -> None:
    catalog = cost._load_catalog()
    text = fixture_env.read_text(encoding="utf-8").replace(
        "| Ollama installed | Yes     |", "| Ollama installed | No |"
    )
    method = cost._with_model(_method(fixture_env, "ollama"), "oss-test")
    assert cost._resolve_funding(method, catalog, text) == ("unfunded-local", None)
    # No section at all → unfunded too.
    assert cost._resolve_funding(method, catalog, "# nothing here\n") == ("unfunded-local", None)


def test_resolve_funding_other_billing_types_unchanged(fixture_env: Path) -> None:
    """The `local` branch must not touch the per-token / subscription paths."""
    monkeypatch_free_catalog = json.loads(
        (FIXTURES / "cost_catalog.json").read_text(encoding="utf-8")
    )
    text = (FIXTURES / "cost_user_context.md").read_text(encoding="utf-8")
    by_id = {m["id"]: m for m in monkeypatch_free_catalog["access_methods"]}
    assert cost._resolve_funding(by_id["xai-api-test"], monkeypatch_free_catalog, text) == (
        "per-token",
        None,
    )
    assert (
        cost._resolve_funding(by_id["claude-code-test"], monkeypatch_free_catalog, text)[0]
        == "subscription-included"
    )
    assert (
        cost._resolve_funding(by_id["cursor-test"], monkeypatch_free_catalog, text)[0]
        == "subscription-pool"
    )
    assert (
        cost._resolve_funding(by_id["codex-test"], monkeypatch_free_catalog, text)[0]
        == "subscription-or-key"
    )
    # OpenRouter is a plain per-token method: funded like any other key.
    assert cost._resolve_funding(
        _method(fixture_env, "openrouter"), cost._load_catalog(), text
    ) == ("per-token", None)


# --------------------------------------------------------------------------- #
# The user-context parsers
# --------------------------------------------------------------------------- #


def test_parsers_on_the_bundled_example_declare_nothing() -> None:
    text = EXAMPLE_CONTEXT_PATH.read_text(encoding="utf-8")
    assert "## Local models (Ollama)" in text
    assert "| Ollama installed | No" in text
    assert cost._local_runtime_present(text) is False
    assert cost._parse_local_models(text) == {}
    keys = cost._parse_active_api_keys(text)
    assert keys.get("openrouter") is False, "example must ship the OpenRouter row as No"


def test_parsers_on_a_fixture_declaring_two_tags() -> None:
    assert cost._local_runtime_present(LOCAL_DECLARED_CONTEXT) is True
    assert cost._parse_local_models(LOCAL_DECLARED_CONTEXT) == {
        "oss-test": "oss-test:20b",
        "only-local-test": "only-local:7b-q4",
    }
    assert cost._parse_active_api_keys(LOCAL_DECLARED_CONTEXT)["openrouter"] is True


def test_parsers_tolerate_prose_edits_and_reject_junk() -> None:
    """The file is untrusted text: header rows, separator rows, commented
    rows, odd casing and stray whitespace never produce a model, and nothing
    that is not a bounded catalog-id shape is accepted."""
    text = LOCAL_DECLARED_CONTEXT.replace(
        "| Ollama installed | Yes     |", "|  OLLAMA  Installed | y |"
    )
    text += "| ../../etc/passwd | tag | q | path-shaped ids are rejected |\n"
    text += "| Model With Spaces | tag | q | rejected |\n"
    text += "| a-very-long-" + "x" * 80 + " | tag | q | rejected |\n"
    assert cost._local_runtime_present(text) is True
    assert set(cost._parse_local_models(text)) == {"oss-test", "only-local-test"}


def test_single_platform_contract_fixture_declares_neither_method() -> None:
    """tests/test_user_stack_contract.py's operator has no Ollama and no
    OpenRouter key, so neither method can be funded for that stack."""
    assert cost._local_runtime_present(SINGLE_PLATFORM_CONTEXT) is False
    assert cost._parse_local_models(SINGLE_PLATFORM_CONTEXT) == {}
    assert not cost._parse_active_api_keys(SINGLE_PLATFORM_CONTEXT).get("openrouter", False)


# --------------------------------------------------------------------------- #
# Cost panel
# --------------------------------------------------------------------------- #


def test_estimate_for_a_funded_local_platform_is_zero_with_the_label(fixture_env: Path) -> None:
    est = cost.estimate_session_cost(
        "oss-test", "ollama", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert est.funding_source == "local"
    assert est.total_usd == 0.0 and est.input_usd == 0.0 and est.output_usd == 0.0
    assert est.subscription_label is None
    assert any(cost.LOCAL_COST_LABEL in n for n in est.notes)


def test_estimate_for_an_unfunded_local_platform_is_flagged_not_reachable(
    fixture_env: Path,
) -> None:
    est = cost.estimate_session_cost("opus-test", "ollama", input_tokens=10, output_tokens=10)
    assert est.funding_source == "unfunded-local"
    assert est.total_usd == 0.0
    assert any("Not reachable" in n for n in est.notes)


def test_panel_renders_local_hardware_and_no_per_token_estimate(fixture_env: Path) -> None:
    est = cost.estimate_session_cost(
        "oss-test", "ollama", input_tokens=1_000_000, output_tokens=1_000_000
    )
    line = cli._session_cost_estimate_line(asdict(est))
    assert line == f"Session cost estimate: {cost.LOCAL_COST_LABEL} (no per-token estimate)"
    assert "$0.00" not in line
    table = cli._ascii_cost_table([asdict(est)])
    assert cost.LOCAL_COST_LABEL in table and "$0.00" not in table
    text = cli._format_cost_command_text(est)
    assert text.startswith(f"Total {cost.LOCAL_COST_LABEL} (local)")


def test_comparison_panel_includes_funded_local_and_omits_unfunded_local(fixture_env: Path) -> None:
    ranked = cost.compare_alternatives_funding_rank(
        "oss-test", input_tokens=1000, output_tokens=1000
    )
    platforms = [(e.platform_id, e.funding_source) for e in ranked]
    assert ("ollama", "local") in platforms
    assert platforms[0] == ("ollama", "local"), "a funded local method ranks with the $0 tier"

    ranked = cost.compare_alternatives_funding_rank(
        "opus-test", input_tokens=1000, output_tokens=1000
    )
    assert all(e.platform_id != "ollama" for e in ranked), "unfunded-local rows are omitted"
    # The catalog still reaches opus-test through OpenRouter (an unfunded/funded
    # per-token row is kept — Step B never drops a per-token method).
    assert any(e.platform_id == "openrouter" for e in ranked)


def test_pricing_tier_is_model_based_for_a_local_pick(fixture_env: Path) -> None:
    """The ladder guard keeps resolving tiers for a local pick — the model keeps
    its hosted price."""
    assert cost.pricing_tier("oss-test") == "low"
    assert cost.pricing_tier("opus-test") == "very-high"


# --------------------------------------------------------------------------- #
# Recommendation payload carries the local platform (mock contract-validated)
# --------------------------------------------------------------------------- #


LOCAL_BLOCK = """MODEL: OSS Test
BACKUP: Opus Test
PLATFORM: Ollama (local)
EFFORT: Low
THINKING: On
CONVERSATION: New
RATIONALE: TASK: Bounded coding. PICK: OSS Test clears the bar; local quantized weights run below the catalog tier ratings; treat coding and reasoning as one tier lower than listed. EFFORT: Low effort suits a bounded edit.
"""


class _FakeAdapter:
    """Provider stub replaying a canned block; mirrors ProviderAdapter.recommend."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def recommend(
        self,
        prompt: str,
        system: str,
        *,
        model: str | None = None,
        api_key: str,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        temperature: float | None = None,
    ) -> str:
        self.calls.append({"prompt": prompt, "system": system, "model": model})
        return self.response


def test_fake_adapter_matches_the_real_adapter_contract() -> None:
    """Contract-validate the mock against the real anthropic adapter's
    `recommend` signature (names, kinds, defaults) and return shape."""
    real = recommend_module.PROVIDER_ADAPTERS["anthropic"]
    real_params = inspect.signature(real.recommend).parameters
    fake_params = inspect.signature(_FakeAdapter("x").recommend).parameters
    assert list(real_params) == list(fake_params)
    for name, real_p in real_params.items():
        fake_p = fake_params[name]
        assert real_p.kind == fake_p.kind, name
        assert real_p.default == fake_p.default, name
    assert isinstance(_FakeAdapter("x").recommend("u", "s", api_key="k"), str)


def test_structured_payload_carries_the_local_platform_and_zero_cost(
    fixture_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from roadmodel.config import Config

    adapter = _FakeAdapter(LOCAL_BLOCK)
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    config = Config(
        provider="anthropic", model=None, api_key="test-key", user_context_path=fixture_env
    )
    payload = recommend_module.recommend_structured(
        "Rename a variable across three files.",
        config,
        allowed_jurisdictions=["us"],
        input_tokens=10_000,
        output_tokens=2_000,
    )
    assert payload["platform"] == "Ollama (local)"
    assert set(payload["settings"]) == {"effort", "thinking"}, "no phantom Max Mode / orchestration"
    assert CAVEAT_CLAUSE in payload["rationale"]
    est = payload["session_cost_estimate"]
    assert est["funding_source"] == "local" and est["total_usd"] == 0.0
    # Backup guard: Opus Test (anthropic) is a different maker from groq → kept.
    assert payload["backup"] == "Opus Test"


def test_cost_panel_prices_against_the_cli_user_context_not_the_env_default(
    fixture_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: the cost panel used to read the env/default user-context and
    could show a `--user-context`-funded local platform as `unfunded-local`
    (observed in the Phase 4.10 real run). recommend_structured now prices
    funding against the SAME file the recommendation was made from."""
    from roadmodel.config import Config

    # Env points at a context that declares NO local runtime...
    bare = tmp_path / "bare-context.md"
    bare.write_text(
        "# User Context\n\n## Active API keys\n\n| Provider | Key present |\n| - | - |\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(bare))
    # ...while the CLI-resolved config path is the one declaring Ollama + oss-test.
    adapter = _FakeAdapter(LOCAL_BLOCK)
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    config = Config(
        provider="anthropic", model=None, api_key="test-key", user_context_path=fixture_env
    )
    payload = recommend_module.recommend_structured(
        "Rename a variable.", config, input_tokens=1000, output_tokens=100
    )
    assert payload["session_cost_estimate"]["funding_source"] == "local"
    assert cost.estimate_session_cost(
        "oss-test", "ollama", input_tokens=1, output_tokens=1
    ).funding_source == ("unfunded-local"), (
        "the env default alone still says unfunded — the fix is the pass-through"
    )
