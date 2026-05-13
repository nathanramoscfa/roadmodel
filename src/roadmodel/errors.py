# src/roadmodel/errors.py
from __future__ import annotations

from pathlib import Path


class RoadmodelError(Exception):
    """Base class for typed roadmodel runtime errors."""


class MissingProviderKeyError(RoadmodelError):
    """No usable provider key could be resolved."""


class ProviderCallError(RoadmodelError):
    """A provider SDK call failed."""


class BundledDocNotFoundError(RoadmodelError):
    """A required bundled document is missing from package data."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(f"reinstall roadmodel; bundled data '{filename}' is missing")


class UserContextNotFoundError(RoadmodelError):
    """User context file is missing at the requested path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"User context file not found: {path}")


class MalformedResponseError(RoadmodelError):
    """Provider response could not be parsed into the six-field block."""

    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text[:2048]
        super().__init__("Provider response did not match the expected six-field format.")
