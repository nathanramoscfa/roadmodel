"""The launch-table collector (update/collect_launch_tables.py).

For a catalog model Artificial Analysis has not measured, Opus reads the
vendor's own launch materials and transcribes its comparison table; the reply
is kept only once roadmodel.estimate.check_launch_tables accepts it. Spend is
bounded per model: MAX_ATTEMPTS tries, RETRY_DAYS apart, MAX_MODELS_PER_RUN a
run. The fake client answers with real SDK Message objects, so the replies it
returns keep the shape the API sends.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from anthropic import APIConnectionError
from anthropic.types import Message

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "update"))

import collect_launch_tables as collector  # noqa: E402

from roadmodel import estimate  # noqa: E402

INDEX = estimate.INDEX_KEY
TODAY = dt.date(2026, 11, 16)


def _bench() -> dict[str, Any]:
    return {
        mid: {"release_date": date, "aa_name": name, "evaluations": {INDEX: index}}
        for mid, name, date, index in (
            ("old-a", "Old A (Max)", "2026-01-01", 40.0),
            ("old-b", "Old B (Max)", "2026-02-01", 50.0),
            ("old-c", "Old C (Max)", "2026-03-01", 60.0),
        )
    }


def _catalog(*ids: str) -> dict[str, Any]:
    return {"models": [{"id": i, "name": i.replace("-", " ").title()} for i in ids]}


def _table(model: str = "new-x") -> dict[str, Any]:
    return {
        "source": "https://vendor.example/launch",
        "columns": [model, "old-a", "old-b", "old-c", None],
        "rows": [
            {"benchmark": f"Bench {i}", "values": [55 + i, 40 + i, 50 + i, 60 + i, 70]}
            for i in range(3)
        ],
    }


def _message(text: str, stop: str = "end_turn") -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }
    )


class FakeClient:
    """Answers each streamed request with the next reply; records requests."""

    def __init__(self, *replies: Message | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    @contextmanager
    def stream(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply

        class _Stream:
            def get_final_message(self) -> Message:
                return reply  # type: ignore[return-value]

        yield _Stream()


def test_only_unmeasured_models_without_a_usable_table_are_due() -> None:
    bench = _bench()
    catalog = _catalog("old-a", "new-x", "new-y", "new-z", "new-w")
    tables = {
        # A usable table: estimated, so not due.
        "new-y": {"release_date": "2026-06-01", "tables": [_table("new-y")]},
        # Found nothing two days ago: not due yet.
        "new-z": {
            "release_date": "2026-06-01",
            "tables": [],
            "checked_on": "2026-11-14",
            "attempts": 1,
        },
        # Out of tries.
        "new-w": {
            "release_date": "2026-06-01",
            "tables": [],
            "checked_on": "2026-10-01",
            "attempts": collector.MAX_ATTEMPTS,
        },
    }
    assert collector.due(catalog, bench, tables, TODAY) == ["new-x"]
    tables["new-z"]["checked_on"] = "2026-11-09"  # a week on, it is tried again
    assert collector.due(catalog, bench, tables, TODAY) == ["new-x", "new-z"]
    many = _catalog(*[f"new-{i}" for i in range(5)])
    assert len(collector.due(many, bench, {}, TODAY)) == collector.MAX_MODELS_PER_RUN


def test_the_reply_is_parsed_from_plain_fenced_or_wrapped_json() -> None:
    doc = {"release_date": "2026-11-09", "tables": []}
    text = json.dumps(doc)
    assert collector.parse(text) == doc
    assert collector.parse(f"Here it is:\n```json\n{text}\n```") == doc
    assert collector.parse(f"I found the table. {text} Done.") == doc
    with pytest.raises(ValueError):
        collector.parse("no table here")


def test_the_request_limits_fetching_to_vendor_domains_and_blocks_artificial_analysis() -> None:
    client = FakeClient(_message(json.dumps({"release_date": "2026-11-09", "tables": [_table()]})))
    ids = collector.roster(_catalog("new-x"), _bench())
    entry = collector.collect(client, "new-x", "New X", ids, None)
    assert entry["tables"] == [_table()] and entry["attempts"] == 1
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["max_tokens"] == collector.MAX_TOKENS
    search, fetch = req["tools"]
    assert search["type"].startswith("web_search_") and search["blocked_domains"] == [
        "artificialanalysis.ai"
    ]
    assert (
        fetch["type"].startswith("web_fetch_")
        and "artificialanalysis.ai" not in fetch["allowed_domains"]
    )
    assert {"anthropic.com", "deepmind.google", "huggingface.co"} <= set(fetch["allowed_domains"])
    assert search["max_uses"] == collector.SEARCH_USES and fetch["max_uses"] == collector.FETCH_USES
    # Every roster id reaches the request, with the name a vendor would print.
    assert "old-a: Old A (Max)" in req["messages"][0]["content"]


def test_an_unfinished_turn_or_a_reply_without_json_is_a_try_that_found_nothing() -> None:
    ids = collector.roster(_catalog("new-x"), _bench())
    prior = {"release_date": "2026-11-01", "tables": [], "attempts": 2}
    for reply in (_message("sorry, nothing", "end_turn"), _message("{", "max_tokens")):
        entry = collector.collect(FakeClient(reply), "new-x", "New X", ids, prior)
        assert entry["tables"] == [] and entry["attempts"] == 3
        assert entry["release_date"] == "2026-11-01"


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: FakeClient, catalog: dict[str, Any]
) -> dict[str, Any]:
    tables, bench, cat = (
        tmp_path / "launch-tables.json",
        tmp_path / "benchmarks.json",
        tmp_path / "catalog.json",
    )
    tables.write_text(json.dumps({"schema_version": 1, "about": "x", "models": {}}))
    bench.write_text(json.dumps({"models": _bench()}))
    cat.write_text(json.dumps(catalog))
    monkeypatch.setattr(collector, "TABLES", tables)
    monkeypatch.setattr(collector, "BENCHMARKS", bench)
    monkeypatch.setattr(collector, "CATALOG", cat)
    monkeypatch.setattr(collector, "ERRORS", tmp_path / "errors.txt")
    monkeypatch.setattr(collector, "_today", lambda: TODAY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: client)
    assert collector.main([]) == 0
    return dict(json.loads(tables.read_text())["models"])


def test_a_run_keeps_a_good_table_and_records_a_refused_one_as_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = {"release_date": "2026-11-09", "tables": [_table("new-x")]}
    bad_table = {**_table("new-y"), "columns": ["new-y", "made-up-id", "old-b", "old-c", None]}
    bad = {"release_date": "2026-11-10", "tables": [bad_table]}
    client = FakeClient(_message(json.dumps(good)), _message(json.dumps(bad)))
    models = _run(tmp_path, monkeypatch, client, _catalog("old-a", "new-x", "new-y"))
    assert models["new-x"]["tables"] == [_table("new-x")]
    assert estimate.estimate("new-x", models["new-x"], _bench()) is not None
    # An id outside the roster: the transcription is refused, the try counted.
    assert models["new-y"] == {
        "release_date": "2026-11-10",
        "tables": [],
        "checked_on": "2026-11-16",
        "attempts": 1,
    }
    assert (tmp_path / "errors.txt").read_text() == ""


def test_an_api_error_is_reported_and_not_counted_as_a_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    models = _run(tmp_path, monkeypatch, FakeClient(error), _catalog("new-x"))
    assert models == {}
    assert "new-x: APIConnectionError" in (tmp_path / "errors.txt").read_text()


def test_a_model_that_left_the_catalog_loses_its_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tables = tmp_path / "launch-tables.json"
    monkeypatch.setattr(collector, "TABLES", tables)
    gone = {"release_date": "2026-01-01", "tables": []}
    tables.write_text(json.dumps({"schema_version": 1, "about": "x", "models": {"gone": gone}}))
    # No model is due, so no request is made.
    models = _run_existing(tmp_path, monkeypatch)
    assert "gone" not in models


def _run_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    bench, cat = tmp_path / "benchmarks.json", tmp_path / "catalog.json"
    bench.write_text(json.dumps({"models": _bench()}))
    cat.write_text(json.dumps(_catalog("old-a")))
    monkeypatch.setattr(collector, "BENCHMARKS", bench)
    monkeypatch.setattr(collector, "CATALOG", cat)
    monkeypatch.setattr(collector, "ERRORS", tmp_path / "errors.txt")
    monkeypatch.setattr(collector, "_today", lambda: TODAY)
    assert collector.main([]) == 0
    return dict(json.loads(collector.TABLES.read_text())["models"])


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda t: t["columns"].__setitem__(1, "unknown-id"), "launch_tables_column"),
        (lambda t: t["columns"].__setitem__(0, "old-a"), "launch_tables_own_column"),
        (lambda t: t["rows"][0]["values"].__setitem__(1, 140), "launch_tables_value"),
        (lambda t: t["rows"][0]["values"].__setitem__(1, True), "launch_tables_value"),
        (lambda t: t["rows"][0].__setitem__("benchmark", "<b>x</b>"), "launch_tables_row"),
        (lambda t: t["rows"][0].__setitem__("note", "extra"), "launch_tables_row"),
        (lambda t: t.__setitem__("source", "http://vendor.example"), "launch_tables_source"),
        (lambda t: t["rows"][0]["values"].pop(), "launch_tables_row"),
    ],
)
def test_the_table_check_refuses_anything_but_typed_data(change: Any, error: str) -> None:
    table = _table()
    change(table)
    doc = {
        "schema_version": 1,
        "about": "x",
        "models": {"new-x": {"release_date": "2026-11-09", "tables": [table]}},
    }
    with pytest.raises(ValueError, match=error):
        estimate.check_launch_tables(doc, {"old-a", "old-b", "old-c", "new-x"}, {"new-x"})


def test_the_committed_launch_tables_pass_the_check() -> None:
    doc = json.loads((REPO / "update" / "launch-tables.json").read_text())
    catalog = {m["id"] for m in json.loads((REPO / "docs" / "catalog.json").read_text())["models"]}
    bench = json.loads((REPO / "docs" / "benchmarks.json").read_text())["models"]
    estimate.check_launch_tables(doc, catalog | set(bench), catalog)
