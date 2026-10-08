# src/roadmodel/usage.py
"""What the last engine call actually consumed, as the provider reported it.

The recommender's cost has always been an ESTIMATE (a fixed prompt size times a
rate card), and the estimate drifts: the static prompt grew from ~20k to ~61k
tokens while the estimate stood still, and prompt caching makes the real bill a
fraction of the list price on a warm prefix. Each provider adapter records the
token counts its SDK returned here, so a caller (the hosted service) can meter
the call exactly instead of guessing.

The record lives in a :class:`~contextvars.ContextVar`, so concurrent requests
(threads, asyncio tasks) never read each other's numbers, and the
``ProviderAdapter`` protocol keeps returning plain text. Recording is
best-effort by construction: an SDK response without a usage block records
nothing, and nothing here can raise into a recommendation.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CallUsage:
    provider: str
    model: str
    # Every prompt token the call sent, cached or not.
    input_tokens: int
    # The part of input_tokens served from the provider's prompt cache (billed
    # at the cache-read rate).
    cached_input_tokens: int
    # The part of input_tokens written to the cache on this call, for providers
    # that bill a write separately (Anthropic); 0 elsewhere.
    cache_write_tokens: int
    # Every generated token, reasoning included (all providers bill reasoning
    # at the output rate).
    output_tokens: int
    # The reasoning share of output_tokens, when the provider reports it.
    reasoning_tokens: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_LAST: ContextVar[CallUsage | None] = ContextVar("roadmodel_last_usage", default=None)


def reset() -> None:
    """Forget the previous call's usage, before making a new one."""
    _LAST.set(None)


def last() -> CallUsage | None:
    """The usage the most recent engine call in this context recorded, if any."""
    return _LAST.get()


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def record(
    provider: str,
    model: str,
    *,
    input_tokens: object,
    output_tokens: object,
    cached_input_tokens: object = 0,
    cache_write_tokens: object = 0,
    reasoning_tokens: object = None,
) -> None:
    """Store one call's counts. Silently skips a response whose totals are not
    integers (an SDK that omits usage), so a missing block never fails a call."""
    total_in = _int(input_tokens)
    total_out = _int(output_tokens)
    if total_in is None or total_out is None:
        return
    _LAST.set(
        CallUsage(
            provider=provider,
            model=model,
            input_tokens=total_in,
            cached_input_tokens=_int(cached_input_tokens) or 0,
            cache_write_tokens=_int(cache_write_tokens) or 0,
            output_tokens=total_out,
            reasoning_tokens=_int(reasoning_tokens),
        )
    )


def add(extra: list[CallUsage | None]) -> None:
    """Fold other calls made for the same request (the classification votes,
    run in their own contexts) into this context's record, summing every
    count, so the caller meters the request whole. ``None`` entries (a call
    that reported nothing) are skipped."""
    calls = [u for u in extra if u is not None]
    if not calls:
        return
    base = _LAST.get()
    if base is not None:
        calls = [base, *calls]
    reasoning = [u.reasoning_tokens for u in calls if u.reasoning_tokens is not None]
    _LAST.set(
        CallUsage(
            provider=calls[0].provider,
            model=calls[0].model,
            input_tokens=sum(u.input_tokens for u in calls),
            cached_input_tokens=sum(u.cached_input_tokens for u in calls),
            cache_write_tokens=sum(u.cache_write_tokens for u in calls),
            output_tokens=sum(u.output_tokens for u in calls),
            reasoning_tokens=sum(reasoning) if reasoning else None,
        )
    )
