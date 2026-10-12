"""A budget for admitting engine groups, not cancellation of running calls."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from roadmodel.providers._safety import transport_timeout  # type: ignore[import-untyped]

ADMISSION_SECONDS = 120.0
PHASE_TIMEOUT_SECONDS = 60.0


@contextmanager
def attempt(deadline: float) -> Iterator[None]:
    remaining = deadline - time.monotonic()
    # Google converts seconds to integer milliseconds: never admit a zero.
    if remaining < 0.001:
        raise HTTPException(status_code=504, detail="provider_deadline")
    with transport_timeout(min(PHASE_TIMEOUT_SECONDS, remaining)):
        yield


def deadline() -> float:
    return time.monotonic() + ADMISSION_SECONDS
