# service/app/live_data.py
"""The catalog on main, read by the hosted recommender without a release.

The roadmodel package reads its data files from ROADMODEL_DATA_DIR when that
directory holds a set it can read (roadmodel.data_files). This module keeps
one filled. The first authenticated request on an instance (app/auth.py)
downloads the files a catalog refresh changes from the repository's main
branch, checks every one, and publishes them as a new directory; the first
such request after REFRESH_SECONDS starts the next download in the background. Any failure keeps the last good
set, or the bundled data when there is none, so /recommend never fails because
GitHub is unreachable.

ROADMODEL_LIVE_DATA=0 turns it off. A ROADMODEL_DATA_DIR the deployment sets
itself turns it off too, and that directory stands.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

try:  # a roadmodel that reads ROADMODEL_DATA_DIR; an older one keeps its bundle
    from roadmodel import data_files  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only against an older roadmodel
    data_files = None

logger = logging.getLogger(__name__)

SWITCH_ENV = "ROADMODEL_LIVE_DATA"
DATA_DIR_ENV = "ROADMODEL_DATA_DIR"
# One fixed host and path over HTTPS. The files are public: the request
# carries no credential, and redirects are not followed.
BASE_URL = "https://raw.githubusercontent.com/nathanramoscfa/roadmodel/main/docs/"
# The data files a catalog refresh rewrites that the package reads, each with
# the size it may have in bytes: a floor a truncated download falls under, and
# a ceiling far above today's (the selector is ~200 KB, catalog.json ~100 KB).
# docs/effort-ratings.json is left out because the package never reads it.
FILES: dict[str, tuple[int, int]] = {
    "catalog.json": (10_000, 4_000_000),
    "model-selector.txt": (20_000, 4_000_000),
    "model-tier-cost-scale.md": (5_000, 4_000_000),
    "benchmarks.json": (1_000, 4_000_000),
    "context-windows.json": (100, 1_000_000),
    "effort-tokens.json": (100, 4_000_000),
}
# The JSON files and the top-level member each must hold as an object.
_MODELS_OBJECT = ("benchmarks.json", "context-windows.json")
# The files catalog.json records the SHA-256 of (source_doc_sha256), which
# proves the selector and the catalog came from one commit.
_HASHED = ("model-selector.txt", "model-tier-cost-scale.md")

REFRESH_SECONDS = 15 * 60
# After a failed attempt the next one waits this long, not the full interval.
RETRY_SECONDS = 60
# How long a request on a cold instance waits for the first download before
# it goes ahead on the bundled data.
COLD_WAIT_SECONDS = 4.0
# The whole download's budget, and each request's connect and read timeouts.
DOWNLOAD_SECONDS = 20.0
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


def enabled() -> bool:
    """Whether this deployment keeps a live set: the switch is not off, the
    installed roadmodel reads one, and the deployment pinned no directory of
    its own."""
    if os.environ.get(SWITCH_ENV, "1").strip().lower() in {"0", "false", "off", "no"}:
        return False
    if data_files is None:
        return False
    pinned = os.environ.get(DATA_DIR_ENV)
    return not pinned or pinned == _STATE.published


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=False)


def _download(client: httpx.Client, name: str, deadline: float) -> bytes:
    """One file's bytes. It stops at the file's ceiling and at the download's
    deadline, so a slow or endless body cannot hold the worker or the memory."""
    high = FILES[name][1]
    with client.stream("GET", BASE_URL + name) as response:
        if response.status_code != 200:
            raise ValueError(f"{name}: HTTP {response.status_code}")
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > high:
                raise ValueError(f"{name}: larger than {high} bytes")
            if time.monotonic() > deadline:
                raise TimeoutError(f"{name}: download budget spent")
    return bytes(body)


def _json_object(name: str, raw: bytes) -> dict[str, Any]:
    parsed: object = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{name}: not a JSON object")
    return parsed


def validate(files: dict[str, bytes]) -> None:
    """Raise ValueError unless *files* is one whole, well-formed set: every
    file present and UTF-8, every JSON file the type the package expects, the
    selector holding its model list, and the selector and tier-cost scale the
    very bytes catalog.json records the hashes of. Whether the package reads
    the catalog's schema is the package's own check (data_files.usable), made
    on the written directory."""
    missing = set(FILES) - set(files)
    if missing:
        raise ValueError(f"missing {sorted(missing)}")
    for name, raw in files.items():
        low, high = FILES[name]
        if not low <= len(raw) <= high:
            raise ValueError(f"{name}: {len(raw)} bytes is outside {low}..{high}")
        raw.decode("utf-8")
    catalog = _json_object("catalog.json", files["catalog.json"])
    for key in ("models", "access_methods"):
        if not isinstance(catalog.get(key), list) or not catalog[key]:
            raise ValueError(f"catalog.json: no {key}")
    for name in _MODELS_OBJECT:
        if not isinstance(_json_object(name, files[name]).get("models"), dict):
            raise ValueError(f"{name}: no models object")
    _json_object("effort-tokens.json", files["effort-tokens.json"])
    if b"<model-options>" not in files["model-selector.txt"]:
        raise ValueError("model-selector.txt: no <model-options>")
    recorded = catalog.get("source_doc_sha256")
    if not isinstance(recorded, dict):
        raise ValueError("catalog.json: no source_doc_sha256")
    for name in _HASHED:
        if recorded.get(name) != hashlib.sha256(files[name]).hexdigest():
            raise ValueError(f"{name}: not the copy catalog.json was built from")


def _write_atomic(path: Path, data: bytes) -> None:
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


class _State:
    """What this process knows of its live set. One download runs at a time;
    readers never wait on the lock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        # time.monotonic() of the last attempt to start, and whether the last
        # finished attempt published a set.
        self.attempted: float | None = None
        self.ok = False
        # True once the first attempt has finished, published or not.
        self.settled = False
        # The private root that holds each published set, and the newest set.
        self.root: Path | None = None
        self.published: str | None = None
        self.fetched_at: float | None = None


_STATE = _State()


def _publish(files: dict[str, bytes]) -> Path:
    """Write *files* into a new directory and return it once the package
    reads it. The directory is new, so no reader sees it half written."""
    if _STATE.root is None:
        _STATE.root = Path(tempfile.mkdtemp(prefix="roadmodel-live-data-"))
    target = Path(tempfile.mkdtemp(prefix="set-", dir=_STATE.root))
    try:
        for name, raw in files.items():
            _write_atomic(target / name, raw)
        if not data_files.usable(target):
            raise ValueError("catalog.json: a schema this roadmodel does not read")
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _prune(keep: set[str]) -> None:
    """Remove every set but *keep*: the newest, and the one before it, which a
    request that resolved a path just before the swap may still be reading."""
    root = _STATE.root
    if root is None:
        return
    for child in root.iterdir():
        if str(child) not in keep:
            shutil.rmtree(child, ignore_errors=True)


def _unchanged(files: dict[str, bytes]) -> bool:
    """Whether the published set already holds exactly *files*. Keeping its
    directory then keeps every cache keyed on it (the ladder table, the dial
    map) warm."""
    current = _STATE.published
    if current is None:
        return False
    try:
        return all((Path(current) / name).read_bytes() == raw for name, raw in files.items())
    except OSError:
        return False


def refresh() -> bool:
    """Download, check and publish one set; True when main's set is the one
    published. Any failure leaves ROADMODEL_DATA_DIR on the last good set (or
    unset)."""
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    try:
        with _client() as client:
            files = {name: _download(client, name, deadline) for name in FILES}
        validate(files)
        if _unchanged(files):
            _STATE.fetched_at = time.time()
            return True
        target = _publish(files)
    except Exception as exc:  # noqa: BLE001 - a failed refresh keeps the last good set
        logger.warning("live data refresh failed; keeping the current data (%s)", exc)
        return False
    previous = _STATE.published
    os.environ[DATA_DIR_ENV] = str(target)
    _STATE.published = str(target)
    _STATE.fetched_at = time.time()
    _prune({str(target), previous or ""})
    logger.info("live data: published a new set from main")
    return True


def _run() -> None:
    published = refresh()
    with _STATE.lock:
        _STATE.ok = published
        _STATE.settled = True


def _start_if_due() -> threading.Thread | None:
    """The running download, a new one when the last is old enough, or None."""
    now = time.monotonic()
    with _STATE.lock:
        if _STATE.worker is not None and _STATE.worker.is_alive():
            return _STATE.worker
        wait = REFRESH_SECONDS if _STATE.ok else RETRY_SECONDS
        if _STATE.attempted is not None and now - _STATE.attempted < wait:
            return None
        _STATE.attempted = now
        worker = threading.Thread(target=_run, name="roadmodel-live-data", daemon=True)
        _STATE.worker = worker
        worker.start()
        return worker


def ensure_fresh() -> None:
    """Keep the live set current; require_bearer (app/auth.py) runs it once a
    request's token checks out.

    A cold instance waits up to COLD_WAIT_SECONDS for its first download, so
    its first answers already read main's catalog; every later download runs
    in the background while requests read the set before it. Never raises."""
    try:
        if not enabled():
            return
        worker = _start_if_due()
        if worker is not None and not _STATE.settled:
            worker.join(COLD_WAIT_SECONDS)
    except Exception:  # noqa: BLE001 - live data is best-effort, never fatal
        logger.warning("live data check failed; using the current data")
