"""Deterministic cross-provider BACKUP guard (follow-up to #4).

Task #4 made the Step 7 BACKUP a HARD cross-provider requirement, but only in
PROMPT prose — and Gemini's instruction-adherence isn't perfect, so it can still
emit a same-maker backup (observed in prod: Fable 5 primary → Opus 4.8 backup,
both Anthropic — zero resilience). This suite covers the deterministic guard that
resolves each model's MAKER (`cost.model_provider`) and drops a same-maker backup
at `_base_to_payload`, mirroring the tier-ladder guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from roadmodel import cost  # noqa: E402
from roadmodel import recommend as recommend_module  # noqa: E402
from roadmodel.config import Config  # noqa: E402
from roadmodel.recommend import _backup_provider_guard  # noqa: E402

# --- cost.model_provider / same_provider -------------------------------------


def test_model_provider_resolves_maker_not_aggregator() -> None:
    # Anthropic models reachable via anthropic-api (and also Cursor's pool) resolve
    # to their MAKER, not the Cursor aggregator.
    assert cost.model_provider("Fable 5") == "anthropic"
    assert cost.model_provider("Opus 4.8") == "anthropic"
    assert cost.model_provider("GPT-5.5") == "openai"
    assert cost.model_provider("Gemini 3 Pro") == "google"


def test_model_provider_aggregator_only_model_falls_back_to_aggregator() -> None:
    # Cursor's own Composer models are reachable ONLY through Cursor, so the
    # aggregator IS the maker.
    assert cost.model_provider("Composer 2.5") == "cursor"


def test_model_provider_unknown_is_none() -> None:
    assert cost.model_provider("NotARealModel") is None


def test_same_provider_true_for_same_maker() -> None:
    # The exact prod bug: Fable 5 and Opus 4.8 are both Anthropic.
    assert cost.same_provider("Fable 5", "Opus 4.8") is True


def test_same_provider_false_cross_maker_and_unknown() -> None:
    assert cost.same_provider("Fable 5", "GPT-5.5") is False
    # Unknown on either side → False (fail safe: never assert an unprovable clash).
    assert cost.same_provider("Fable 5", "NotARealModel") is False


# --- _backup_provider_guard (detection) --------------------------------------


def test_guard_flags_same_maker_backup() -> None:
    guard = _backup_provider_guard("Fable 5", "Opus 4.8")
    assert guard["primary_provider"] == "anthropic"
    assert guard["backup_provider"] == "anthropic"
    assert guard["same_provider"] is True
    assert guard["ok"] is False


def test_guard_passes_cross_provider_backup() -> None:
    guard = _backup_provider_guard("Fable 5", "GPT-5.5")
    assert guard["same_provider"] is False
    assert guard["ok"] is True


def test_guard_fails_safe_on_unknown_provider() -> None:
    # Can't prove same maker → ok (keep the backup).
    guard = _backup_provider_guard("Fable 5", "NotARealModel")
    assert guard["same_provider"] is False
    assert guard["ok"] is True


# --- recommend_structured integration ----------------------------------------


def _config(tmp_path: Path) -> Config:
    ctx = tmp_path / "user-context.md"
    ctx.write_text("# ctx\n", encoding="utf-8")
    return Config(provider="anthropic", model=None, api_key="test-key", user_context_path=ctx)


def _fake_base_with(**fields: str):
    def _fake(prompt: str, config: Config, **_kwargs: object) -> dict[str, str]:
        base = {
            "model": "Fable 5",
            "platform": "Claude Code",
            "max_mode": "Off",
            "thinking": "Max",
            "conversation": "New",
            "rationale": "Fable 5 is S-tier.",
        }
        base.update(fields)
        return base

    return _fake


def test_recommend_structured_drops_same_provider_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fable 5 primary + Opus 4.8 backup (both Anthropic) → the backup is dropped
    and the guard decision is recorded, so the UI never shows a resilience-useless
    same-maker fallback."""
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with(backup="Opus 4.8"))
    payload = recommend_module.recommend_structured("audit this", _config(tmp_path))
    assert "backup" not in payload
    assert payload["backup_guard"]["same_provider"] is True
    assert payload["backup_guard"]["primary_provider"] == "anthropic"


def test_recommend_structured_keeps_cross_provider_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fable 5 primary + GPT-5.5 backup (Anthropic vs OpenAI) → kept, no guard
    key (back-compatible with the pre-guard shape)."""
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with(backup="GPT-5.5"))
    payload = recommend_module.recommend_structured("audit this", _config(tmp_path))
    assert payload["backup"] == "GPT-5.5"
    assert "backup_guard" not in payload


def test_recommend_structured_no_backup_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with())
    payload = recommend_module.recommend_structured("audit this", _config(tmp_path))
    assert "backup" not in payload
    assert "backup_guard" not in payload


# --- cost.suggest_cross_provider_backup (0.2.20 substitution) ----------------


def test_suggest_cross_provider_picks_comparable_tier() -> None:
    # Anthropic very-high primary → an OpenAI very-high backup (us).
    assert cost.suggest_cross_provider_backup("Fable 5", allowed_jurisdictions=["us"]) == "GPT-5.5"
    assert cost.suggest_cross_provider_backup("Opus 4.8", allowed_jurisdictions=["us"]) == "GPT-5.5"


def test_suggest_cross_provider_respects_jurisdiction() -> None:
    # EU-only / CN-only users get a region-valid cross-provider fallback, never a
    # us-only model.
    eu = cost.suggest_cross_provider_backup("Opus 4.8", allowed_jurisdictions=["eu"])
    cn = cost.suggest_cross_provider_backup("Opus 4.8", allowed_jurisdictions=["cn"])
    assert eu is not None and cost.model_provider(eu) != "anthropic"
    assert cn is not None and cost.model_provider(cn) != "anthropic"


def test_suggest_cross_provider_excludes_unavailable() -> None:
    # Bench the top us cross-provider options → the next available one is chosen.
    picked = cost.suggest_cross_provider_backup(
        "Fable 5", allowed_jurisdictions=["us"], unavailable_models=["gpt-5.5", "gemini-3-pro"]
    )
    assert picked is not None
    assert cost.model_provider(picked) != "anthropic"


def test_suggest_cross_provider_none_without_jurisdiction() -> None:
    # No allowed jurisdictions → None (a region-invalid substitute is worse than
    # dropping).
    assert cost.suggest_cross_provider_backup("Fable 5", allowed_jurisdictions=[]) is None


# --- recommend_structured substitution wiring --------------------------------


def test_recommend_structured_substitutes_same_provider_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With the user's jurisdictions supplied, a same-maker backup (Fable 5 →
    Opus 4.8, both Anthropic) is SUBSTITUTED with a cross-provider model rather
    than dropped — 0.2.17 option A ("a weaker cross-provider backup beats none")."""
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with(backup="Opus 4.8"))
    payload = recommend_module.recommend_structured(
        "audit this", _config(tmp_path), allowed_jurisdictions=["us"]
    )
    assert payload["backup"] == "GPT-5.5"
    assert cost.model_provider(payload["backup"]) != "anthropic"
    guard = payload["backup_guard"]
    assert guard["action"] == "substituted"
    assert guard["original_backup"] == "Opus 4.8"
    assert guard["substitute"] == "GPT-5.5"


def test_recommend_structured_drops_when_no_jurisdiction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without jurisdictions (CLI/older caller), the guard still DROPS a same-maker
    backup — a substitute could be region-invalid, so dropping stays the safe path."""
    monkeypatch.setattr(recommend_module, "recommend", _fake_base_with(backup="Opus 4.8"))
    payload = recommend_module.recommend_structured("audit this", _config(tmp_path))
    assert "backup" not in payload
    assert payload["backup_guard"]["action"] == "dropped"
    assert payload["backup_guard"]["original_backup"] == "Opus 4.8"
