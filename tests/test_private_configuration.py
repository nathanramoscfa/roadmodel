"""Local operator configuration stays outside public automation templates."""

from __future__ import annotations

import importlib.util
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gate_watcher", ROOT / "scripts/gate-alert-watcher.py"
)
assert SPEC is not None and SPEC.loader is not None
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


@pytest.mark.parametrize("override", [None, "", "override@example.test"])
def test_alert_recipient_is_private_configuration(
    monkeypatch: pytest.MonkeyPatch, override: str | None
) -> None:
    if override is None:
        monkeypatch.delenv("GATE_ALERT_EMAIL", raising=False)
    else:
        monkeypatch.setenv("GATE_ALERT_EMAIL", override)
    monkeypatch.delenv("GATE_ALERT_NO_MAIL", raising=False)
    monkeypatch.setattr(watcher, "_env_or_keychain", lambda name: "https://example.test")
    monkeypatch.setattr(watcher, "_keychain", lambda name: "configured@example.test")
    events = iter(['{"attempts":3}', None])
    monkeypatch.setattr(watcher, "_rpop", lambda base, token: next(events))
    monkeypatch.setattr(watcher, "notify", lambda title, body: None)
    recipients: list[str] = []
    monkeypatch.setattr(
        watcher, "send_mail", lambda recipient, subject, body: recipients.append(recipient)
    )
    assert watcher.main() == 0
    assert recipients == ([] if override == "" else [override or "configured@example.test"])


def test_launchd_templates_resolve_home_without_embedding_an_account() -> None:
    for name in ["gate-alert-watcher", "roll-pool-status"]:
        path = ROOT / "scripts" / f"com.roadmodel.{name}.plist"
        data = plistlib.loads(path.read_bytes())
        argv = data["ProgramArguments"]
        assert argv[:2] == ["/bin/sh", "-c"]
        assert '"$HOME/roadmodel/scripts/' in argv[2]
        assert "/Users/" not in path.read_text()
        subprocess.run(["/bin/sh", "-n", "-c", argv[2]], check=True)


def test_alert_watcher_has_no_literal_recipient() -> None:
    text = (ROOT / "scripts/gate-alert-watcher.py").read_text()
    assert re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text) is None
