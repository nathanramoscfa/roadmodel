# tests/test_cli.py
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel import recommend as recommend_module  # noqa: E402
from roadmodel import user_context as user_context_module  # noqa: E402
from roadmodel.cli import cli  # noqa: E402
from roadmodel.config import Config, load_config  # noqa: E402
from roadmodel.errors import MalformedResponseError  # noqa: E402

FIXTURE_RESPONSE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample_response.txt"
FIXTURE_USER_CONTEXT_PATH = REPO_ROOT / "tests" / "fixtures" / "sample_user_context.md"
FIXTURE_CATALOG_PATH = REPO_ROOT / "tests" / "fixtures" / "cost_catalog.json"
FIXTURE_COST_USER_CONTEXT_PATH = REPO_ROOT / "tests" / "fixtures" / "cost_user_context.md"

RESPONSE_GPT_TEST_CODEX = (
    "MODEL: GPT Test\n"
    "PLATFORM: Codex\n"
    "MAX MODE: Off\n"
    "THINKING: High\n"
    "CONVERSATION: New\n"
    "RATIONALE: Fixture rationale for structured CLI tests.\n"
)

RESPONSE_WITH_BACKUP = (
    "MODEL: Opus 4.8\n"
    "BACKUP: GPT-5.5\n"
    "PLATFORM: Claude Code\n"
    "MAX MODE: Off\n"
    "THINKING: High\n"
    "CONVERSATION: New\n"
    "RATIONALE: Fixture rationale with a backup model.\n"
)

# Output contract v2: the setting fields are PLATFORM-CONDITIONAL. Claude Code
# has no Max Mode, so the block emits no MAX MODE line at all; the reasoning
# LEVEL lives in EFFORT and THINKING is a two-position toggle.
RESPONSE_V2_CLAUDE_CODE = (
    "MODEL: Opus 4.8\n"
    "BACKUP: GPT-5.5\n"
    "PLATFORM: Claude Code\n"
    "EFFORT: Ultracode\n"
    "THINKING: On\n"
    "ORCHESTRATION: None\n"
    "CONVERSATION: New\n"
    "RATIONALE: v2 fixture — no MAX MODE line, effort carries the level.\n"
)


def _runner() -> CliRunner:
    return CliRunner()


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "ROADMODEL_PROVIDER",
        "ROADMODEL_USER_CONTEXT",
    ]:
        monkeypatch.delenv(key, raising=False)


def _set_isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_recommend_invokes_build_prompt_and_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sample_response = FIXTURE_RESPONSE_PATH.read_text(encoding="utf-8")
    user_context_text = FIXTURE_USER_CONTEXT_PATH.read_text(encoding="utf-8")
    context_path = tmp_path / "user-context.md"
    context_path.write_text(user_context_text, encoding="utf-8")

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

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
            self.calls.append(
                {"prompt": prompt, "system": system, "model": model, "api_key": api_key}
            )
            return sample_response

    adapter = FakeAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)

    config = Config(
        provider="anthropic",
        model=None,
        api_key="test-key",
        user_context_path=context_path,
    )
    parsed = recommend_module.recommend("build a SQL agent", config)
    # sample_response.txt is an output-contract-v2 Codex block: Codex exposes a
    # reasoning dial and NO Max Mode, so it emits EFFORT + THINKING and no MAX
    # MODE line. Only model / platform / conversation / rationale are required —
    # effort and thinking appear because the BLOCK carried them, and max_mode is
    # absent because the platform has no such dial (never "Off").
    assert set(parsed.keys()) == {
        "model",
        "platform",
        "effort",
        "thinking",
        "conversation",
        "rationale",
    }
    assert "max_mode" not in parsed
    assert adapter.calls, "provider adapter was not called"
    assert "<model-selector>" in str(adapter.calls[0]["system"])
    # The user prompt is wrapped as delimited input (classify-don't-execute, #187).
    assert (
        adapter.calls[0]["prompt"] == "<task-to-classify>\nbuild a SQL agent\n</task-to-classify>"
    )


class _CapturingAdapter:
    """Provider adapter stub that records the system prompt it was handed."""

    def __init__(self) -> None:
        self.system: str | None = None

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
        self.system = system
        return RESPONSE_GPT_TEST_CODEX


def test_recommend_user_context_text_overrides_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A supplied user_context_text is used verbatim AND skips the on-disk file
    read (Phase 4.8 T2b). Proven by pointing user_context_path at a nonexistent
    file: the file read would raise UserContextNotFoundError, so a clean parse
    means the override short-circuited it; the marker proves the text is used."""
    adapter = _CapturingAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    config = Config(
        provider="anthropic",
        model=None,
        api_key="test-key",
        user_context_path=tmp_path / "does-not-exist.md",
    )

    parsed = recommend_module.recommend(
        "build a SQL agent",
        config,
        user_context_text="OVERRIDE_CONTEXT_MARKER",
    )

    # LEGACY ACCEPTANCE: RESPONSE_GPT_TEST_CODEX is a v1 block (MAX MODE always
    # present, THINKING carrying the effort level) — the shape still arriving
    # from cached responses, older releases and exported planning kits — so
    # max_mode/thinking appear here where the v2 fixture yields effort/thinking.
    assert set(parsed.keys()) == {
        "model",
        "platform",
        "max_mode",
        "thinking",
        "conversation",
        "rationale",
    }
    assert adapter.system is not None
    assert "OVERRIDE_CONTEXT_MARKER" in adapter.system


def test_recommend_reads_user_context_file_when_no_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no override (user_context_text=None, the default) behavior is
    unchanged: the file at config.user_context_path is read into the prompt."""
    adapter = _CapturingAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    context_path = tmp_path / "user-context.md"
    context_path.write_text("FILE_CONTEXT_MARKER\n", encoding="utf-8")
    config = Config(
        provider="anthropic",
        model=None,
        api_key="test-key",
        user_context_path=context_path,
    )

    recommend_module.recommend("build a SQL agent", config)

    assert adapter.system is not None
    assert "FILE_CONTEXT_MARKER" in adapter.system


def test_recommend_structured_threads_user_context_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """recommend_structured forwards user_context_text to recommend so the
    override reaches the prompt — proven again against a missing file path."""
    adapter = _CapturingAdapter()
    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", adapter)
    config = Config(
        provider="anthropic",
        model=None,
        api_key="test-key",
        user_context_path=tmp_path / "does-not-exist.md",
    )

    payload = recommend_module.recommend_structured(
        "build a SQL agent",
        config,
        user_context_text="STRUCTURED_OVERRIDE_MARKER",
    )

    assert payload["model"]
    assert adapter.system is not None
    assert "STRUCTURED_OVERRIDE_MARKER" in adapter.system


def test_recommend_no_key_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    result = _runner().invoke(cli, ["recommend", "build a SQL agent"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.stderr
    assert "OPENAI_API_KEY" in result.stderr
    assert "GOOGLE_API_KEY" in result.stderr


def test_recommend_explicit_provider_missing_key_names_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")

    result = _runner().invoke(cli, ["recommend", "--provider", "openai", "build a SQL agent"])
    assert result.exit_code == 2
    assert "OPENAI_API_KEY" in result.stderr
    assert "'openai'" in result.stderr
    assert "ANTHROPIC_API_KEY" not in result.stderr
    assert "GOOGLE_API_KEY" not in result.stderr


def test_recommend_missing_file_exits_2_with_path(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.txt"
    result = _runner().invoke(cli, ["recommend", "--file", str(missing)])
    assert result.exit_code == 2
    assert "Unexpected error" not in result.stderr
    assert "does not exist" in result.stderr
    assert str(missing) in result.stderr


def test_recommend_first_run_bootstraps_user_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    default_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"

    class FailingAdapter:
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
            raise AssertionError("Provider must not be called before first-run bootstrap.")

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", FailingAdapter())

    result = _runner().invoke(cli, ["recommend", "build a SQL agent"])
    assert result.exit_code == 6
    assert default_path.exists()
    assert str(default_path) in result.stderr


def test_recommend_unedited_user_context_warns_but_proceeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")

    context_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        (REPO_ROOT / "docs" / "user-context.example.md").read_text(), encoding="utf-8"
    )

    sample_response = FIXTURE_RESPONSE_PATH.read_text(encoding="utf-8")

    class StaticAdapter:
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
            return sample_response

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", StaticAdapter())

    result = _runner().invoke(cli, ["recommend", "build a SQL agent"])
    assert result.exit_code == 0
    assert "placeholder" in result.stderr.lower()
    assert "GPT-5.3 Codex" in result.stdout


def test_recommend_forwards_engine_params_to_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The --thinking-budget / --max-output-tokens / --temperature flags must
    # reach the provider adapter so local dogfooding can mirror prod's tuned
    # engine params (free tier thinking_budget=0; frontier 512 + caps). The
    # zero values matter: thinking_budget=0 (thinking off) and temperature=0.0
    # (deterministic) are meaningful, not "unset".
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")

    context_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        (REPO_ROOT / "docs" / "user-context.example.md").read_text(), encoding="utf-8"
    )
    sample_response = FIXTURE_RESPONSE_PATH.read_text(encoding="utf-8")
    captured: dict[str, object] = {}

    class RecordingAdapter:
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
            captured["max_output_tokens"] = max_output_tokens
            captured["thinking_budget"] = thinking_budget
            captured["temperature"] = temperature
            return sample_response

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", RecordingAdapter())

    result = _runner().invoke(
        cli,
        [
            "recommend",
            "--thinking-budget",
            "0",
            "--max-output-tokens",
            "256",
            "--temperature",
            "0",
            "build a SQL agent",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {
        "max_output_tokens": 256,
        "thinking_budget": 0,
        "temperature": 0.0,
    }


def test_catalog_show_bytes_match_source() -> None:
    result = _runner().invoke(cli, ["catalog", "show"])
    expected = (REPO_ROOT / "docs" / "model-selector.txt").read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert result.stdout == expected


def test_catalog_show_tier_cost_scale_bytes_match_source() -> None:
    result = _runner().invoke(cli, ["catalog", "show", "--doc", "tier-cost-scale"])
    expected = (REPO_ROOT / "docs" / "model-tier-cost-scale.md").read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert result.stdout == expected


def test_context_show_bytes_match_resolved_path(tmp_path: Path) -> None:
    context_path = tmp_path / "ctx.md"
    expected = "# sample context\nvalue: 1\n"
    context_path.write_text(expected, encoding="utf-8")
    result = _runner().invoke(cli, ["context", "show", "--user-context", str(context_path)])
    assert result.exit_code == 0
    assert result.stdout == expected


def test_context_init_creates_file_and_respects_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_isolated_home(monkeypatch, tmp_path)
    target = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    template_text = (REPO_ROOT / "docs" / "user-context.example.md").read_text(encoding="utf-8")

    create_result = _runner().invoke(cli, ["context", "init"])
    assert create_result.exit_code == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == template_text

    no_force_result = _runner().invoke(cli, ["context", "init"])
    assert no_force_result.exit_code != 0
    assert "already exists" in no_force_result.stderr

    target.write_text("modified\n", encoding="utf-8")
    force_result = _runner().invoke(cli, ["context", "init", "--force"])
    assert force_result.exit_code == 0
    assert target.read_text(encoding="utf-8") == template_text


def test_parse_response_json_path() -> None:
    """The JSON path, v1 shape (max_mode + an effort-carrying thinking)."""
    payload = json.dumps(
        {
            "model": "GPT-5.3 Codex",
            "platform": "Codex",
            "max_mode": "Off",
            "thinking": "High",
            "conversation": "New",
            "rationale": "test rationale",
        }
    )
    parsed = recommend_module.parse_response(payload)
    assert parsed["model"] == "GPT-5.3 Codex"
    assert parsed["platform"] == "Codex"


def test_parse_response_json_path_v2_shape() -> None:
    """The JSON path must stay consistent with the regex path: the four
    always-on fields are enough, and an explicit `effort` is carried through."""
    payload = json.dumps(
        {
            "model": "Opus 4.8",
            "platform": "Claude Code",
            "effort": "Max",
            "thinking": "On",
            "conversation": "New",
            "rationale": "test rationale",
        }
    )
    parsed = recommend_module.parse_response(payload)
    assert parsed["effort"] == "Max"
    assert parsed["thinking"] == "On"
    assert "max_mode" not in parsed


def test_parse_response_json_path_requires_the_four_always_on_fields() -> None:
    """A JSON payload missing a required field must NOT be accepted just because
    the setting fields became optional (it falls through to the regex path and
    then raises)."""
    payload = json.dumps(
        {"model": "Opus 4.8", "platform": "Claude Code", "effort": "Max", "thinking": "On"}
    )
    with pytest.raises(MalformedResponseError):
        recommend_module.parse_response(payload)


def test_recommend_parses_a_v2_block_with_no_max_mode_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end through `recommend`: a v2 Claude Code block omits MAX MODE
    entirely and must yield the v2 key set — no max_mode key, effort holding the
    level, thinking holding the toggle."""

    class V2Adapter:
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
            return RESPONSE_V2_CLAUDE_CODE

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", V2Adapter())
    context_path = tmp_path / "user-context.md"
    context_path.write_text("# ctx\n", encoding="utf-8")
    config = Config(
        provider="anthropic",
        model=None,
        api_key="test-key",
        user_context_path=context_path,
    )

    parsed = recommend_module.recommend("build a SQL agent", config)
    assert set(parsed.keys()) == {
        "model",
        "backup",
        "platform",
        "effort",
        "thinking",
        "conversation",
        "rationale",
    }
    assert parsed["effort"] == "Ultracode"
    assert parsed["thinking"] == "On"


def test_parse_response_regex_path() -> None:
    text = FIXTURE_RESPONSE_PATH.read_text(encoding="utf-8")
    parsed = recommend_module.parse_response(text)
    assert parsed["model"] == "GPT-5.3 Codex"
    assert parsed["platform"] == "Codex"


def test_parse_response_regex_with_prompt_label() -> None:
    text = "PROMPT: Step 4 annotation\n" + FIXTURE_RESPONSE_PATH.read_text(encoding="utf-8")
    parsed = recommend_module.parse_response(text)
    assert parsed["conversation"] == "New"


def test_parse_response_malformed() -> None:
    with pytest.raises(MalformedResponseError):
        recommend_module.parse_response("not a six-field response")


@pytest.mark.parametrize(
    ("name", "cli_provider", "env", "toml_text", "expected_provider", "expected_key"),
    [
        (
            "cli_provider",
            "openai",
            {"OPENAI_API_KEY": "openai-env", "ANTHROPIC_API_KEY": "anthropic-env"},
            "",
            "openai",
            "openai-env",
        ),
        (
            "env_provider",
            None,
            {
                "ROADMODEL_PROVIDER": "google",
                "GOOGLE_API_KEY": "google-env",
                "ANTHROPIC_API_KEY": "a",
            },
            "",
            "google",
            "google-env",
        ),
        (
            "first_present_key",
            None,
            {"ANTHROPIC_API_KEY": "anthropic-env", "OPENAI_API_KEY": "openai-env"},
            "",
            "anthropic",
            "anthropic-env",
        ),
        (
            "config_fallback_key",
            None,
            {"ROADMODEL_PROVIDER": "openai"},
            '[providers.openai]\napi_key = "openai-from-config"\n',
            "openai",
            "openai-from-config",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_config_provider_precedence(
    name: str,
    cli_provider: str | None,
    env: dict[str, str],
    toml_text: str,
    expected_provider: str,
    expected_key: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del name  # used for param ids above
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    config_path = tmp_path / "xdg" / "roadmodel" / "config.toml"
    if toml_text:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(toml_text, encoding="utf-8")

    resolved_user_context = tmp_path / "resolved-user-context.md"
    monkeypatch.setattr(
        "roadmodel.config.user_context.resolve",
        lambda *, cli_path: resolved_user_context,
    )

    loaded = load_config(cli_provider=cli_provider, cli_model=None, cli_user_context=None)
    assert loaded.provider == expected_provider
    assert loaded.api_key == expected_key
    assert loaded.user_context_path == resolved_user_context


@pytest.mark.parametrize(
    ("case_name", "setup"),
    [
        ("cli_overrides", "cli"),
        ("env_overrides", "env"),
        ("xdg_home", "xdg"),
        ("standard_home", "home"),
        ("no_repo_walk_fallback", "no_repo_walk"),
    ],
)
def test_user_context_resolve_precedence(
    case_name: str,
    setup: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del case_name
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    cli_path = tmp_path / "cli-context.md"
    env_path = tmp_path / "env-context.md"
    xdg_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    home_path = tmp_path / "home" / ".config" / "roadmodel" / "user-context.md"

    if setup == "cli":
        cli_path.write_text("cli", encoding="utf-8")
        resolved = user_context_module.resolve(cli_path=cli_path)
        assert resolved == cli_path
        return

    if setup == "env":
        env_path.write_text("env", encoding="utf-8")
        monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(env_path))
        resolved = user_context_module.resolve(cli_path=None)
        assert resolved == env_path
        return

    if setup == "xdg":
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        xdg_path.parent.mkdir(parents=True, exist_ok=True)
        xdg_path.write_text("xdg", encoding="utf-8")
        resolved = user_context_module.resolve(cli_path=None)
        assert resolved == xdg_path
        return

    if setup == "home":
        home_path.parent.mkdir(parents=True, exist_ok=True)
        home_path.write_text("home", encoding="utf-8")
        resolved = user_context_module.resolve(cli_path=None)
        assert resolved == home_path
        return

    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    repo_context_path = repo_root / "docs" / "user-context.md"
    repo_context_path.parent.mkdir(parents=True, exist_ok=True)
    repo_context_path.write_text("repo", encoding="utf-8")
    work_dir = repo_root / "nested" / "dir"
    work_dir.mkdir(parents=True)
    monkeypatch.chdir(work_dir)
    resolved = user_context_module.resolve(cli_path=None)
    assert resolved == home_path
    assert resolved != repo_context_path


def test_config_repr_masks_api_key() -> None:
    config = Config(
        provider="anthropic",
        model=None,
        api_key="sk-ant-very-secret-token-abcdef123456",
        user_context_path=Path("/tmp/uc.md"),
    )
    rendered = repr(config)
    assert "sk-ant-very-secret-token-abcdef123456" not in rendered
    assert "sk-a***" in rendered

    empty_config = Config(
        provider="anthropic",
        model=None,
        api_key="",
        user_context_path=Path("/tmp/uc.md"),
    )
    assert "<empty>" in repr(empty_config)


def test_user_context_bootstrap_creates_0o600(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "config" / "roadmodel" / "user-context.md"
    user_context_module.bootstrap(target)
    assert target.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    parent_mode = target.parent.stat().st_mode & 0o777
    assert parent_mode == 0o700, f"expected parent 0o700, got {oct(parent_mode)}"

    target.chmod(0o644)
    user_context_module.bootstrap(target)
    overwrite_mode = target.stat().st_mode & 0o777
    assert overwrite_mode == 0o600, f"expected 0o600 after overwrite, got {oct(overwrite_mode)}"


def _cost_fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADMODEL_CATALOG_PATH", str(FIXTURE_CATALOG_PATH))
    monkeypatch.setenv("ROADMODEL_USER_CONTEXT", str(FIXTURE_COST_USER_CONTEXT_PATH))


def test_recommend_structured_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    _cost_fixture_env(monkeypatch)

    context_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        FIXTURE_COST_USER_CONTEXT_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    class StaticAdapter:
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
            return RESPONSE_GPT_TEST_CODEX

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", StaticAdapter())

    result = _runner().invoke(
        cli,
        ["recommend", "--output", "json", "build a SQL agent"],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "model",
        "platform",
        "settings",
        "rationale",
        "conversation",
        "session_cost_estimate",
        "comparison_table",
    }
    assert payload["session_cost_estimate"] is None
    assert payload["comparison_table"] is None
    assert payload["settings"] == {"intelligence": "High"}

    with_tokens = _runner().invoke(
        cli,
        [
            "recommend",
            "--output",
            "json",
            "--input-tokens",
            "1000000",
            "--output-tokens",
            "500000",
            "build a SQL agent",
        ],
    )
    assert with_tokens.exit_code == 0, with_tokens.stderr
    full = json.loads(with_tokens.stdout)
    assert full["session_cost_estimate"] is not None
    assert full["session_cost_estimate"]["total_usd"] == 7.0
    assert full["comparison_table"] is not None
    assert len(full["comparison_table"]) == 3


def test_recommend_text_output_shows_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default (structured) CLI text output renders the BACKUP model when the
    selector emits one — parity with the web app's "Backup if unavailable" line.
    The no-backup fixtures above never render the line (it's absent-safe)."""
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    _cost_fixture_env(monkeypatch)

    context_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        FIXTURE_COST_USER_CONTEXT_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    class BackupAdapter:
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
            return RESPONSE_WITH_BACKUP

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", BackupAdapter())

    text = _runner().invoke(cli, ["recommend", "build a SQL agent"])
    assert text.exit_code == 0, text.stderr
    assert "Backup if unavailable: GPT-5.5" in text.stdout

    js = _runner().invoke(cli, ["recommend", "--output", "json", "build a SQL agent"])
    assert js.exit_code == 0, js.stderr
    assert json.loads(js.stdout)["backup"] == "GPT-5.5"


def test_recommend_legacy_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")

    context_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        FIXTURE_USER_CONTEXT_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    class StaticAdapter:
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
            return RESPONSE_GPT_TEST_CODEX

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", StaticAdapter())

    result = _runner().invoke(cli, ["recommend", "--legacy", "build a SQL agent"])
    assert result.exit_code == 0
    assert result.stdout.strip() == RESPONSE_GPT_TEST_CODEX.strip()


def test_recommend_json_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")

    context_path = tmp_path / "xdg" / "roadmodel" / "user-context.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        FIXTURE_USER_CONTEXT_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    class StaticAdapter:
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
            return RESPONSE_GPT_TEST_CODEX

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", StaticAdapter())

    result = _runner().invoke(
        cli,
        ["recommend", "--output", "json", "build a SQL agent"],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["model"] == "GPT Test"


def test_cost_subcommand_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _cost_fixture_env(monkeypatch)
    result = _runner().invoke(
        cli,
        [
            "cost",
            "--model",
            "gpt-test",
            "--platform",
            "codex-test",
            "--input-tokens",
            "1000000",
            "--output-tokens",
            "1000000",
        ],
    )
    assert result.exit_code == 0
    assert "$12.00" in result.stdout
    assert "subscription" in result.stdout.lower()


def test_cost_subcommand_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _cost_fixture_env(monkeypatch)
    result = _runner().invoke(
        cli,
        [
            "cost",
            "--model",
            "gpt-test",
            "--platform",
            "codex-test",
            "--input-tokens",
            "500000",
            "--output-tokens",
            "250000",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["model_id"] == "gpt-test"
    assert data["platform_id"] == "codex-test"
    assert data["total_usd"] == 3.5


def test_cost_unknown_model_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    _cost_fixture_env(monkeypatch)
    result = _runner().invoke(
        cli,
        [
            "cost",
            "--model",
            "no-such-model",
            "--platform",
            "codex-test",
            "--input-tokens",
            "1",
            "--output-tokens",
            "1",
        ],
    )
    assert result.exit_code == 4
    assert "no-such-model" in result.stderr


def test_cost_fast_variant_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _cost_fixture_env(monkeypatch)
    result = _runner().invoke(
        cli,
        [
            "cost",
            "--model",
            "Opus Test Fast",
            "--platform",
            "claude-code-test",
            "--input-tokens",
            "1000",
            "--output-tokens",
            "1000",
        ],
    )
    assert result.exit_code == 4
    assert "Opus Test" in result.stderr


# --- export-kit -----------------------------------------------------------


def _export_kit_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate HOME/XDG so resolve() never picks up the real ~/.config copy."""
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)


def test_export_kit_writes_full_kit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _export_kit_env(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    uc = tmp_path / "user-context.md"
    uc.write_text("# User Context\n\nMY_REAL_SUBS_MARKER\n", encoding="utf-8")

    result = _runner().invoke(cli, ["export-kit", str(project), "--user-context", str(uc)])
    assert result.exit_code == 0, result.output

    planning = project / "planning"
    for rel in [
        "model-selector.txt",
        "model-tier-cost-scale.md",
        "HOW-TO-USE.md",
        "user-context.md",
        "templates/project-roadmap-template.md",
        "templates/phase-roadmap-template.md",
    ]:
        assert (planning / rel).is_file(), f"missing {rel}"

    assert "<model-selector>" in (planning / "model-selector.txt").read_text(encoding="utf-8")
    assert "MY_REAL_SUBS_MARKER" in (planning / "user-context.md").read_text(encoding="utf-8")
    assert "you are the engine" in (planning / "HOW-TO-USE.md").read_text(encoding="utf-8").lower()


def test_export_kit_seeds_template_when_no_user_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _export_kit_env(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    missing = tmp_path / "nope" / "user-context.md"

    result = _runner().invoke(cli, ["export-kit", str(project), "--user-context", str(missing)])
    assert result.exit_code == 0, result.output

    uc_out = project / "planning" / "user-context.md"
    assert uc_out.is_file()
    assert "User Context" in uc_out.read_text(encoding="utf-8")
    assert "TEMPLATE" in result.output


def test_export_kit_custom_dest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _export_kit_env(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    uc = tmp_path / "uc.md"
    uc.write_text("# User Context\n", encoding="utf-8")

    result = _runner().invoke(
        cli, ["export-kit", str(project), "--dest", "kit", "--user-context", str(uc)]
    )
    assert result.exit_code == 0, result.output
    assert (project / "kit" / "model-selector.txt").is_file()
    assert not (project / "planning").exists()


def test_export_kit_preserves_user_context_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _export_kit_env(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    uc1 = tmp_path / "uc1.md"
    uc1.write_text("# User Context\n\nFIRST\n", encoding="utf-8")
    uc2 = tmp_path / "uc2.md"
    uc2.write_text("# User Context\n\nSECOND\n", encoding="utf-8")

    _runner().invoke(cli, ["export-kit", str(project), "--user-context", str(uc1)])
    uc_out = project / "planning" / "user-context.md"
    assert "FIRST" in uc_out.read_text(encoding="utf-8")

    # Second run without --force keeps the existing kit user-context.
    _runner().invoke(cli, ["export-kit", str(project), "--user-context", str(uc2)])
    assert "FIRST" in uc_out.read_text(encoding="utf-8")

    # With --force it is overwritten.
    _runner().invoke(cli, ["export-kit", str(project), "--user-context", str(uc2), "--force"])
    assert "SECOND" in uc_out.read_text(encoding="utf-8")


def test_export_kit_missing_target_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _export_kit_env(monkeypatch, tmp_path)
    result = _runner().invoke(cli, ["export-kit", str(tmp_path / "does-not-exist")])
    assert result.exit_code != 0
