"""Live global adapters preserve client customizations and never snapshot rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "agent_rules.py"


@pytest.fixture(scope="module")
def rules() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agent_rules", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(home: Path, relative: str, text: str) -> Path:
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _snapshot(home: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(home)): path.read_bytes() for path in home.rglob("*") if path.is_file()
    }


def test_unique_client_rules_and_canonical_source_are_preserved(
    rules: ModuleType, tmp_path: Path
) -> None:
    source = _write(tmp_path, ".claude/CLAUDE.md", "# Canonical\nShared rule A.\n")
    source_bytes = source.read_bytes()
    own_rules = "# Codex custom rules\r\nKeep this content exactly.\r\n\r\n"
    target = _write(tmp_path, ".codex/AGENTS.md", own_rules)
    _, ok = rules.sync_global_rules(tmp_path, ["claude", "codex", "antigravity", "opencode"])
    assert ok
    assert source.read_bytes() == source_bytes
    adapter = target.read_bytes().decode("utf-8")
    assert adapter.endswith(own_rules)
    assert "Shared rule A." not in adapter
    assert "~/.claude/CLAUDE.md" in adapter
    assert ".roadmodel/context.json" in adapter and ".roadmodel/HANDOFF.md" in adapter
    assert ".agents/shared-context.md" in adapter and "scoped Claude rules" in adapter
    assert "MEMORY.md" in adapter and "paths" in adapter
    assert (
        "@[Shared global rules](~/.claude/CLAUDE.md)"
        in (tmp_path / ".gemini/GEMINI.md").read_text()
    )
    opencode = (tmp_path / ".config/opencode/AGENTS.md").read_text()
    assert ".agents/shared-context.md" in opencode
    assert "original project rules, scoped Claude rules" in opencode


def test_identical_duplicate_becomes_live_adapter_with_exact_backup(
    rules: ModuleType, tmp_path: Path
) -> None:
    body = "# Global\nA shared rule.\n"
    _write(tmp_path, ".claude/CLAUDE.md", body)
    target = _write(tmp_path, ".codex/AGENTS.md", body)
    report, ok = rules.sync_global_rules(tmp_path, ["codex"])
    assert ok
    assert "A shared rule." not in target.read_text()
    backups = list(target.parent.glob("AGENTS.md.roadmodel-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == body
    assert any(str(backups[0]) in line for line in report)


def test_second_run_is_noop_and_check_detects_source_edits_live(
    rules: ModuleType, tmp_path: Path
) -> None:
    source = _write(tmp_path, ".claude/CLAUDE.md", "Original source\n")
    agents = ["claude", "codex", "antigravity", "opencode"]
    assert rules.sync_global_rules(tmp_path, agents)[1]
    target = tmp_path / ".codex/AGENTS.md"
    before = _snapshot(tmp_path)
    mtime = target.stat().st_mtime_ns
    assert rules.sync_global_rules(tmp_path, agents)[1]
    assert _snapshot(tmp_path) == before
    assert target.stat().st_mtime_ns == mtime
    source.write_text("New rule becomes available immediately\n")
    assert rules.sync_global_rules(tmp_path, agents, check=True)[1]
    assert target.stat().st_mtime_ns == mtime
    assert "New rule" not in target.read_text()


@pytest.mark.parametrize("mode", ["dry_run", "check"])
def test_preview_modes_never_write_or_backup(rules: ModuleType, tmp_path: Path, mode: str) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Source rule\n")
    _write(tmp_path, ".codex/AGENTS.md", "Source rule\n")
    before = _snapshot(tmp_path)
    report, ok = rules.sync_global_rules(
        tmp_path, ["codex", "antigravity", "opencode"], **{mode: True}
    )
    assert ok is (mode == "dry_run")
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / ".gemini").exists()
    assert any("DRIFT" in line or "would" in line for line in report)


def test_missing_canonical_source_reports_gap_then_recovers_when_added(
    rules: ModuleType, tmp_path: Path
) -> None:
    report, ok = rules.sync_global_rules(tmp_path, ["codex", "antigravity"])
    assert not ok
    assert any("FAILED to read" in line and "CLAUDE.md" in line for line in report)
    assert not (tmp_path / ".claude").exists()
    target = tmp_path / ".codex/AGENTS.md"
    adapter_before = target.read_bytes()
    _write(tmp_path, ".claude/CLAUDE.md", "Newly introduced shared rules\n")
    report, ok = rules.sync_global_rules(tmp_path, ["codex", "antigravity"], check=True)
    assert ok
    assert target.read_bytes() == adapter_before


def test_unreadable_source_is_not_claimed_current(rules: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / ".claude/CLAUDE.md"
    source.mkdir(parents=True)
    report, ok = rules.sync_global_rules(tmp_path, ["codex"], dry_run=True)
    assert not ok
    assert any("FAILED to read" in line for line in report)
    assert not (tmp_path / ".codex").exists()


def test_preserves_text_on_both_sides_of_existing_block(rules: ModuleType, tmp_path: Path) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    original = f"before\n\n{rules.START}\nold adapter\n{rules.END}\n\nafter\n"
    target = _write(tmp_path, ".codex/AGENTS.md", original)
    assert rules.sync_global_rules(tmp_path, ["codex"])[1]
    body = target.read_text()
    assert body.startswith("before\n\n")
    assert body.endswith("\n\nafter\n")
    assert "old adapter" not in body
    assert body.count(rules.START) == 1


@pytest.mark.parametrize("damage", ["start_only", "duplicate", "reversed"])
def test_damaged_blocks_are_reported_without_discarding_user_content(
    rules: ModuleType, tmp_path: Path, damage: str
) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    blocks = {
        "start_only": rules.START,
        "duplicate": f"{rules.START}{rules.END}{rules.START}{rules.END}",
        "reversed": f"{rules.END}{rules.START}",
    }
    target = _write(tmp_path, ".codex/AGENTS.md", "user text\n" + blocks[damage])
    original = target.read_bytes()
    report, ok = rules.sync_global_rules(tmp_path, ["codex"])
    assert not ok
    assert target.read_bytes() == original
    assert any("damaged or duplicate" in line for line in report)


def test_codex_effective_override_is_maintained(rules: ModuleType, tmp_path: Path) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    base = _write(tmp_path, ".codex/AGENTS.md", "Inactive base\n")
    override = _write(tmp_path, ".codex/AGENTS.override.md", "Active custom rule\n")
    assert rules.sync_global_rules(tmp_path, ["codex"])[1]
    assert base.read_text() == "Inactive base\n"
    assert "Active custom rule" in override.read_text()
    assert rules.START in override.read_text()


def test_empty_codex_override_does_not_shadow_base(rules: ModuleType, tmp_path: Path) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    override = _write(tmp_path, ".codex/AGENTS.override.md", "")
    assert rules.sync_global_rules(tmp_path, ["codex"])[1]
    assert override.read_text() == ""
    assert rules.START in (tmp_path / ".codex/AGENTS.md").read_text()


def test_modular_scoped_rules_are_not_flattened(rules: ModuleType, tmp_path: Path) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    rule = _write(
        tmp_path,
        ".claude/rules/nested/python.md",
        '---\npaths: ["**/*.py"]\n---\nOnly Python applies here.\n',
    )
    before = rule.read_bytes()
    report, ok = rules.sync_global_rules(tmp_path, ["antigravity"])
    assert ok and rule.read_bytes() == before
    assert any("1 modular rule(s)" in line for line in report)
    target = (tmp_path / ".gemini/GEMINI.md").read_text()
    assert "Only Python applies here." not in target
    assert "with `paths` apply only" in target


def test_symlink_to_source_is_never_written_through(rules: ModuleType, tmp_path: Path) -> None:
    source = _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    target = tmp_path / ".codex/AGENTS.md"
    target.parent.mkdir()
    try:
        target.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    report, ok = rules.sync_global_rules(tmp_path, ["codex"])
    assert ok and target.is_symlink()
    assert source.read_text() == "Canonical\n"
    assert any("live source symlink" in line for line in report)


def test_other_symlink_is_reported_without_mutating_target(
    rules: ModuleType, tmp_path: Path
) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    actual = _write(tmp_path, "somewhere/rules.md", "Managed elsewhere\n")
    target = tmp_path / ".codex/AGENTS.md"
    target.parent.mkdir()
    try:
        target.symlink_to(actual)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    report, ok = rules.sync_global_rules(tmp_path, ["codex"])
    assert not ok and target.is_symlink()
    assert actual.read_text() == "Managed elsewhere\n"
    assert any("symlink target is not" in line for line in report)


def test_settings_and_model_permissions_are_never_touched(
    rules: ModuleType, tmp_path: Path
) -> None:
    _write(tmp_path, ".claude/CLAUDE.md", "Canonical\n")
    settings = _write(tmp_path, ".codex/config.toml", 'model = "keep-me"\n')
    opencode = _write(tmp_path, ".config/opencode/opencode.jsonc", "// leave exactly\n{}\n")
    assert rules.sync_global_rules(tmp_path, ["codex", "opencode"])[1]
    assert settings.read_text() == 'model = "keep-me"\n'
    assert opencode.read_text() == "// leave exactly\n{}\n"
