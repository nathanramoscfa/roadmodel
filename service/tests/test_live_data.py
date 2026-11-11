# service/tests/test_live_data.py
"""Main's catalog, fetched by the service (app/live_data.py), with no network.

The guarantees under test:

- a whole, well-formed set from main is published as a new directory and
  ROADMODEL_DATA_DIR points the package at it;
- a set that fails a check (shape, size, hash, a schema the package does not
  read), an HTTP error, a redirect or an unreachable host publishes nothing
  and leaves the last good set, or the bundled data, in place;
- a request on a cold instance waits for the first download; a later one
  starts the next download only past the refresh interval (or the shorter
  retry interval after a failure);
- ROADMODEL_LIVE_DATA=0, or a ROADMODEL_DATA_DIR the deployment set itself,
  turns it off;
- /healthz says which catalog the package reads, and a request never fails
  because the download did.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from roadmodel import data_files  # type: ignore[import-untyped]

from app import funding, live_data

DOCS = Path(__file__).resolve().parents[2] / "docs"
_TOKEN = "test-internal-token"


def _main_set() -> dict[str, bytes]:
    return {name: (DOCS / name).read_bytes() for name in live_data.FILES}


def _with_catalog(files: dict[str, bytes], **changes: object) -> dict[str, bytes]:
    catalog = json.loads(files["catalog.json"])
    catalog.update(changes)
    return {**files, "catalog.json": json.dumps(catalog).encode("utf-8")}


def _rehash(files: dict[str, bytes]) -> dict[str, bytes]:
    """The set with catalog.json recording the hashes of its own selector and
    tier-cost scale, as update/build_catalog.py writes it."""
    hashes = {name: hashlib.sha256(files[name]).hexdigest() for name in live_data._HASHED}
    return _with_catalog(files, source_doc_sha256=hashes)


class _GitHub:
    """A fake raw.githubusercontent.com: serves a set and counts requests."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.requests: list[httpx.Request] = []
        self.fail: Callable[[httpx.Request], httpx.Response] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            return self.fail(request)
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=self.files[name])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[_GitHub]:
    fake = _GitHub(_main_set())
    monkeypatch.setenv("ROADMODEL_LIVE_DATA", "1")
    # Registered, then removed: the env var the module sets is undone after.
    monkeypatch.setenv("ROADMODEL_DATA_DIR", "unset")
    monkeypatch.delenv("ROADMODEL_DATA_DIR")
    monkeypatch.setattr(live_data, "_STATE", live_data._State())
    live_data._STATE.root = tmp_path / "live"
    live_data._STATE.root.mkdir()
    monkeypatch.setattr(live_data, "_client", fake.client)
    data_files.reset()
    yield fake
    data_files.reset()


def _sets() -> list[Path]:
    root = live_data._STATE.root
    assert root is not None
    return sorted(root.iterdir())


def test_a_good_set_is_published_and_read(github: _GitHub) -> None:
    github.files = _with_catalog(github.files, generated_at_utc="2099-01-01T00:00:00Z")
    assert live_data.refresh() is True

    published = Path(live_data._STATE.published or "")
    assert os.environ["ROADMODEL_DATA_DIR"] == str(published)
    assert _sets() == [published]
    for name, raw in github.files.items():
        assert (published / name).read_bytes() == raw
    # The package and the service's own catalog reader both read it now.
    assert data_files.override_dir() == published
    assert funding.load_catalog()["generated_at_utc"] == "2099-01-01T00:00:00Z"
    assert live_data.status()["source"] == "live"
    assert live_data.status()["catalog_generated_at"] == "2099-01-01T00:00:00Z"


def test_it_asks_one_fixed_https_host_for_each_file(github: _GitHub) -> None:
    assert live_data.refresh() is True
    urls = {str(r.url) for r in github.requests}
    assert urls == {
        f"https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main/docs/{name}"
        for name in live_data.FILES
    }
    assert all(r.method == "GET" and "authorization" not in r.headers for r in github.requests)


def _no_options(files: dict[str, bytes]) -> dict[str, bytes]:
    selector = files["model-selector.txt"].replace(b"<model-options>", b"<options>")
    return _rehash({**files, "model-selector.txt": selector})


def _stale_selector(files: dict[str, bytes]) -> dict[str, bytes]:
    # A selector from another commit than the catalog (a push mid-download).
    return {**files, "model-selector.txt": files["model-selector.txt"] + b"\n"}


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(lambda f: {**f, "catalog.json": b"{not json" + b" " * 20_000}, id="bad-json"),
        pytest.param(
            lambda f: {**f, "catalog.json": b"[" + b"1," * 9_000 + b"1]"}, id="not-object"
        ),
        pytest.param(lambda f: _with_catalog(f, models=[]), id="no-models"),
        pytest.param(
            lambda f: {**f, "benchmarks.json": json.dumps({"models": []}).encode() + b" " * 999},
            id="benchmarks-models-not-object",
        ),
        pytest.param(lambda f: {**f, "context-windows.json": b"{}"}, id="too-small"),
        pytest.param(lambda f: {**f, "model-tier-cost-scale.md": b"\xff" * 6_000}, id="not-utf8"),
        pytest.param(_no_options, id="no-model-options"),
        pytest.param(_stale_selector, id="hash-mismatch"),
        pytest.param(lambda f: _with_catalog(f, schema_version="99"), id="newer-catalog-schema"),
        pytest.param(lambda f: _with_catalog(f, output_contract_version=3), id="newer-contract"),
        pytest.param(
            lambda f: {
                **f,
                "effort-tokens.json": json.dumps({"schema_version": 9, "models": {}}).encode(),
            },
            id="newer-effort-tokens-schema",
        ),
    ],
)
def test_a_set_that_fails_a_check_is_not_published(
    github: _GitHub, spoil: Callable[[dict[str, bytes]], dict[str, bytes]]
) -> None:
    github.files = spoil(github.files)
    assert live_data.refresh() is False
    assert "ROADMODEL_DATA_DIR" not in os.environ
    assert _sets() == []  # nothing half written is left behind
    assert data_files.override_dir() is None
    assert live_data.status()["source"] == "bundled"


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("unreachable", request=request)


@pytest.mark.parametrize(
    "fail",
    [
        pytest.param(_connect_error, id="unreachable"),
        pytest.param(lambda r: httpx.Response(503), id="http-503"),
        pytest.param(lambda r: httpx.Response(404), id="http-404"),
        pytest.param(
            lambda r: httpx.Response(302, headers={"location": "https://example.com/x"}),
            id="redirect",
        ),
    ],
)
def test_a_network_failure_keeps_the_last_good_set(
    github: _GitHub, fail: Callable[[httpx.Request], httpx.Response]
) -> None:
    assert live_data.refresh() is True
    good = live_data._STATE.published

    github.fail = fail
    assert live_data.refresh() is False
    assert os.environ["ROADMODEL_DATA_DIR"] == good
    assert _sets() == [Path(good or "")]
    assert data_files.override_dir() == Path(good or "")


def test_a_download_over_its_ceiling_stops(
    github: _GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(live_data.FILES, "context-windows.json", (100, 1_000))
    github.files = {**github.files, "context-windows.json": b" " * 5_000}
    assert live_data.refresh() is False
    assert "ROADMODEL_DATA_DIR" not in os.environ


def test_a_cold_request_waits_and_a_warm_one_waits_for_the_interval(github: _GitHub) -> None:
    live_data.ensure_fresh()  # cold: waits for the first download
    first = live_data._STATE.published
    assert first is not None and os.environ["ROADMODEL_DATA_DIR"] == first
    assert len(github.requests) == len(live_data.FILES)

    live_data.ensure_fresh()  # inside the interval: nothing new
    assert len(github.requests) == len(live_data.FILES)

    # Past the interval the next download runs in the background.
    assert live_data._STATE.attempted is not None
    live_data._STATE.attempted -= live_data.REFRESH_SECONDS + 1
    github.files = _with_catalog(github.files, generated_at_utc="2099-02-02T00:00:00Z")
    live_data.ensure_fresh()
    assert live_data._STATE.worker is not None
    live_data._STATE.worker.join(5)
    second = live_data._STATE.published
    assert second not in (None, first)
    assert len(github.requests) == 2 * len(live_data.FILES)
    assert funding.load_catalog()["generated_at_utc"] == "2099-02-02T00:00:00Z"
    # The set before stays for a request still reading it; older ones go.
    assert _sets() == sorted([Path(first), Path(second or "")])
    live_data._STATE.attempted -= live_data.REFRESH_SECONDS + 1
    github.files = _with_catalog(github.files, generated_at_utc="2099-03-03T00:00:00Z")
    live_data.ensure_fresh()
    live_data._STATE.worker.join(5)
    assert Path(first) not in _sets() and len(_sets()) == 2


def test_an_unchanged_set_keeps_its_directory(github: _GitHub) -> None:
    assert live_data.refresh() is True
    first = live_data._STATE.published
    stamp = data_files.stamp("catalog.json")
    assert live_data.refresh() is True
    # Same directory, same stamp: the caches keyed on it stay warm.
    assert live_data._STATE.published == first and _sets() == [Path(first or "")]
    assert data_files.stamp("catalog.json") == stamp


def test_after_a_failure_the_retry_comes_sooner(github: _GitHub) -> None:
    github.fail = _connect_error
    live_data.ensure_fresh()
    assert live_data._STATE.settled and not live_data._STATE.ok
    attempts = len(github.requests)

    assert live_data._STATE.attempted is not None
    live_data._STATE.attempted -= live_data.RETRY_SECONDS + 1
    github.fail = None
    live_data.ensure_fresh()
    assert live_data._STATE.worker is not None
    live_data._STATE.worker.join(5)
    assert len(github.requests) > attempts
    assert live_data._STATE.ok and data_files.override_dir() is not None


def test_the_switch_turns_it_off(github: _GitHub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROADMODEL_LIVE_DATA", "0")
    live_data.ensure_fresh()
    assert github.requests == []
    assert "ROADMODEL_DATA_DIR" not in os.environ


def test_a_directory_the_deployment_sets_stands(
    github: _GitHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ROADMODEL_DATA_DIR", str(tmp_path))
    live_data.ensure_fresh()
    assert github.requests == []
    assert os.environ["ROADMODEL_DATA_DIR"] == str(tmp_path)


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ROADMODEL_INTERNAL_TOKEN", _TOKEN)
    for module_name in ("app.main", "app.recommend", "app.visitor", "app.score"):
        sys.modules.pop(module_name, None)
    app = importlib.import_module("app.main").app
    return TestClient(app, headers={"Authorization": f"Bearer {_TOKEN}"})


def test_a_request_fetches_first_and_healthz_reports_it(
    github: _GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _client(monkeypatch).get("/healthz").json()
    assert body["data"]["source"] == "live"
    assert body["data"]["fetched_at"]
    assert len(github.requests) == len(live_data.FILES)


def test_a_request_never_fails_because_github_does(
    github: _GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    github.fail = _connect_error
    client = _client(monkeypatch)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["data"]["source"] == "bundled"
    task = {
        "category": "coding",
        "complexity": "high",
        "novel": False,
        "budget_priority": "balanced",
    }
    assert client.post("/v1/score", json=task).status_code == 200


def test_the_real_client_follows_no_redirect_and_gives_up_fast() -> None:
    with live_data._client() as client:  # builds the client; connects nowhere
        assert client.follow_redirects is False
        assert client.timeout.connect == 2.0 and client.timeout.read == 5.0
    assert live_data.BASE_URL.startswith("https://raw.githubusercontent.com/")
