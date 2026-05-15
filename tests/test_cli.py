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
            self, prompt: str, system: str, *, model: str | None = None, api_key: str
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
    assert set(parsed.keys()) == {
        "model",
        "platform",
        "max_mode",
        "thinking",
        "conversation",
        "rationale",
    }
    assert adapter.calls, "provider adapter was not called"
    assert "<model-selector>" in str(adapter.calls[0]["system"])
    assert "build a SQL agent" == adapter.calls[0]["prompt"]


def test_recommend_no_key_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_provider_env(monkeypatch)
    _set_isolated_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    result = _runner().invoke(cli, ["recommend", "build a SQL agent"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.stderr
    assert "OPENAI_API_KEY" in result.stderr
    assert "GOOGLE_API_KEY" in result.stderr


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
            self, prompt: str, system: str, *, model: str | None = None, api_key: str
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
            self, prompt: str, system: str, *, model: str | None = None, api_key: str
        ) -> str:
            return sample_response

    monkeypatch.setitem(recommend_module.PROVIDER_ADAPTERS, "anthropic", StaticAdapter())

    result = _runner().invoke(cli, ["recommend", "build a SQL agent"])
    assert result.exit_code == 0
    assert "placeholder" in result.stderr.lower()
    assert "MODEL:" in result.stdout


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
