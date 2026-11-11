# src/roadmodel/data_files.py
"""Where the package reads its data files: the bundled copies, or a newer set.

Every data file ships inside the package (``roadmodel/data/``, copied from
``docs/`` at build). ``ROADMODEL_DATA_DIR`` names a directory that replaces
them file by file: a file the directory holds is read from there, any other
from the bundle. The hosted service points it at the catalog it fetches from
``main`` (service/app/live_data.py), so a catalog change reaches /recommend
without a release.

The directory is looked up at read time, never at import, because the service
swaps in a new set while the process runs: a new ``ROADMODEL_DATA_DIR`` takes
effect on the next read, and a file rewritten in place within RECHECK_SECONDS.
(The scorer asks thousands of times per ladder; a stat on every ask made it a
third slower.)

The directory's ``catalog.json`` vouches for the set: the directory is used
only when it holds a catalog whose schema and output contract this package
reads, and every other versioned file in it parses and carries a schema this
package reads. Otherwise every file comes from the bundle, so data newer than
the code never meets that code half way.

``ROADMODEL_CATALOG_PATH`` still names the catalog itself and wins over the
directory for ``catalog.json`` (cost._load_catalog).
"""

from __future__ import annotations

import functools
import json
import os
import time
from collections.abc import Callable, Iterator
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import IO, Any, Final, Literal, TypeVar, overload

DATA_DIR_ENV: Final = "ROADMODEL_DATA_DIR"

# The catalog schemas this package reads. SOURCE OF TRUTH:
# update/build_catalog.py SCHEMA_VERSION; a schema bump adds its version here
# in the same change, or the bundled catalog fails tests/test_data_files.py.
CATALOG_SCHEMAS: Final[frozenset[str]] = frozenset({"5"})
# The selector output contracts this package parses: recommend.
# OUTPUT_CONTRACT_VERSION, which the catalog records as output_contract_version.
OUTPUT_CONTRACTS: Final[frozenset[int]] = frozenset({2})
# The other versioned files and the schemas this package reads of each.
FILE_SCHEMAS: Final[dict[str, frozenset[int]]] = {
    "benchmarks.json": frozenset({2}),  # update/fetch_aa_benchmarks.py
    "effort-tokens.json": frozenset({1}),  # update/measure_effort_tokens.py
}
# Every JSON file the set check parses: one that fails to parse would read as
# empty data downstream (scoring's loaders return {}), which is worse than the
# bundle.
_CHECKED: Final[tuple[str, ...]] = (
    "catalog.json",
    "benchmarks.json",
    "context-windows.json",
    "effort-tokens.json",
)

# How long one look at the directory stands before the next read looks again.
RECHECK_SECONDS: Final = 1.0

# Set verdicts by directory and the stat of each checked file, so the JSON is
# parsed again only when a file changes.
_VERDICTS: dict[tuple[object, ...], bool] = {}
_VERDICTS_MAX: Final = 16
# The last look: the ROADMODEL_DATA_DIR value, when it was taken, the usable
# directory (None: the bundle) and the stat of each file asked about since.
_LOOK: tuple[str, float, Path | None, dict[str, tuple[int, int, int] | None]] | None = None

T = TypeVar("T")


def _bundled(name: str) -> Traversable:
    return resources.files("roadmodel.data") / name


def _file_stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _parse(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _known(value: object, versions: frozenset[Any]) -> bool:
    # A JSON true equals 1, and is no schema version.
    return not isinstance(value, bool) and value in versions


def usable(directory: Path) -> bool:
    """Whether this package reads the data set in *directory*: it holds a
    catalog.json of a schema and output contract this package knows, and
    every other JSON file it holds parses, with a known schema where the file
    carries one."""
    catalog = _parse(directory / "catalog.json")
    if not isinstance(catalog, dict):
        return False
    if not _known(catalog.get("schema_version"), CATALOG_SCHEMAS):
        return False
    if not _known(catalog.get("output_contract_version"), OUTPUT_CONTRACTS):
        return False
    for name in _CHECKED[1:]:
        path = directory / name
        if not path.is_file():
            continue
        doc = _parse(path)
        if not isinstance(doc, dict):
            return False
        versions = FILE_SCHEMAS.get(name)
        if versions is not None and not _known(doc.get("schema_version"), versions):
            return False
    return True


def _verdict(raw: str) -> Path | None:
    if not raw:
        return None
    directory = Path(raw).expanduser()
    key = (str(directory), *(_file_stamp(directory / name) for name in _CHECKED))
    verdict = _VERDICTS.get(key)
    if verdict is None:
        verdict = usable(directory)
        if len(_VERDICTS) >= _VERDICTS_MAX:
            _VERDICTS.clear()
        _VERDICTS[key] = verdict
    return directory if verdict else None


def _look() -> tuple[Path | None, dict[str, tuple[int, int, int] | None]]:
    global _LOOK
    raw = os.environ.get(DATA_DIR_ENV, "").strip()
    now = time.monotonic()
    look = _LOOK
    if look is None or look[0] != raw or now - look[1] >= RECHECK_SECONDS:
        look = (raw, now, _verdict(raw), {})
        _LOOK = look
    return look[2], look[3]


def _override(name: str) -> tuple[Path, tuple[int, int, int]] | None:
    """The data directory's copy of *name* and its stat, when reads take it."""
    directory, seen = _look()
    if directory is None:
        return None
    if name not in seen:
        seen[name] = _file_stamp(directory / name)
    found = seen[name]
    return None if found is None else (directory / name, found)


def override_dir() -> Path | None:
    """The data directory reads use now, or None for the bundle: the
    ``ROADMODEL_DATA_DIR`` directory when its set is usable."""
    return _look()[0]


def reset() -> None:
    """Forget the last look at the data directory, so the next read looks
    again at once (tests that rewrite a file in place)."""
    global _LOOK
    _LOOK = None
    _VERDICTS.clear()


def locate(resource: Traversable) -> Traversable:
    """The file a read of *resource* opens now: a DataFile's current source,
    or *resource* itself. ``resources.as_file`` needs this to hand back a
    real path rather than a temporary copy."""
    return resource.current() if isinstance(resource, DataFile) else resource


def stamp(*names: str) -> tuple[object, ...]:
    """What a read of each named file would return now, cheaply: its path,
    modification time, size and inode when it comes from the data directory,
    "bundled" otherwise. A cache keyed on the stamp stays right while the
    service swaps sets."""
    out: list[object] = []
    for name in names:
        found = _override(name)
        out.append("bundled" if found is None else (str(found[0]), *found[1]))
    return tuple(out)


def cached_on(*names: str) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Cache a loader's result until one of the named data files changes.

    It replaces ``functools.cache`` on loaders of data files, which would keep
    the first set read for the life of the process. ``__wrapped__`` still
    reaches the uncached loader."""

    def decorate(loader: Callable[[], T]) -> Callable[[], T]:
        # One (stamp, value) pair, replaced whole so a thread never pairs one
        # set's stamp with another's value.
        memo: list[tuple[tuple[object, ...], T]] = []

        @functools.wraps(loader)
        def cached() -> T:
            key = stamp(*names)
            last = memo[-1] if memo else None
            if last is not None and last[0] == key:
                return last[1]
            value = loader()
            memo[:] = [(key, value)]
            return value

        return cached

    return decorate


class DataFile(Traversable):
    """One data file, found again on every read: the data directory's copy
    when the directory holds one and its set is usable, the bundled copy
    otherwise. It stands in wherever a ``resources.files(...) / name``
    Traversable did."""

    def __init__(self, name: str) -> None:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("A data file is named by a bare file name.")
        self._name = name

    def current(self) -> Traversable:
        found = _override(self._name)
        return _bundled(self._name) if found is None else found[0]

    @property
    def name(self) -> str:
        return self._name

    def read_text(self, encoding: str | None = None) -> str:
        return self.current().read_text(encoding=encoding)

    def read_bytes(self) -> bytes:
        return self.current().read_bytes()

    @overload
    def open(
        self,
        mode: Literal["r"] = "r",
        *,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> IO[str]: ...

    @overload
    def open(self, mode: Literal["rb"]) -> IO[bytes]: ...

    def open(
        self, mode: str = "r", *, encoding: str | None = None, errors: str | None = None
    ) -> IO[Any]:
        if mode == "rb":
            return self.current().open("rb")
        if mode == "r":
            return self.current().open("r", encoding=encoding, errors=errors)
        raise ValueError(f"A data file opens for reading only, not {mode!r}.")

    def is_file(self) -> bool:
        return self.current().is_file()

    def is_dir(self) -> bool:
        return self.current().is_dir()

    def iterdir(self) -> Iterator[Traversable]:
        return self.current().iterdir()

    def joinpath(self, *descendants: str | os.PathLike[str]) -> Traversable:
        return self.current().joinpath(*descendants)

    def __truediv__(self, child: str | os.PathLike[str], /) -> Traversable:
        return self.current() / child

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DataFile) and other._name == self._name

    def __hash__(self) -> int:
        return hash((DataFile, self._name))

    def __str__(self) -> str:
        return str(self.current())

    def __repr__(self) -> str:
        return f"DataFile({self._name!r})"


def data_file(name: str) -> DataFile:
    """The data file *name*, read from the data directory or the bundle."""
    return DataFile(name)
