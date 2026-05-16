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


class AlternativeRejectedError(RoadmodelError):
    """A model alternative was rejected per user-context.md selection rules."""

    def __init__(self, model_id: str, standard_id: str) -> None:
        self.model_id = model_id
        self.standard_id = standard_id
        super().__init__(
            f"Fast variant {model_id!r} rejected — use {standard_id!r} instead per "
            "user-context.md Speed posture (Fast variants charge 2x for marginal speed)."
        )
