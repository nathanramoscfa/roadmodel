# service/tests/conftest.py
"""Shared service test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test off the network: the app fetches main's catalog before
    each authenticated request (app/auth.py, app/live_data.py) unless ROADMODEL_LIVE_DATA is off. The
    live-data tests turn it back on with a fake transport."""
    monkeypatch.setenv("ROADMODEL_LIVE_DATA", "0")
