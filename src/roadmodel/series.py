"""A model's series and version, read off its catalog id.

The operator's rule: a recommendation never names an older version of a
series when a newer one is offered on the same platform. GPT-6 Sol and
GPT-6.1 Sol are one series ("sol"), so only GPT-6.1 Sol is recommended; Opus 5
and Opus 5.5 are one series, so only Opus 5.5 is.

A series is the id's name words, its version numbers and the vendor prefix
aside: `claude-opus-5-5`, `claude-opus-5` and `opus-4.8` are one series;
`gpt-6-sol` and `gpt-6-luna` are two, and so are `gpt-5.5` and
`gpt-5.5-mini`. A parameter count (`20b`, `120b`, `a3b`) names a size, not a
version, so `gpt-oss-20b` and `gpt-oss-120b` are two series.

Mirrored by update/supersede.py (which cannot import the package); the tests
hold the two together.
"""

from __future__ import annotations

import re
from typing import Final

_SIZE_RE: Final = re.compile(r"(?<![a-z0-9.])a?\d+(?:\.\d+)?[bmk](?![a-z0-9])")
_VENDOR_WORDS: Final[frozenset[str]] = frozenset({"claude"})


def _split(model_id: str) -> tuple[str, tuple[str, ...]]:
    text = model_id.lower()
    return _SIZE_RE.sub(" ", text), tuple(sorted(_SIZE_RE.findall(text)))


def series(model_id: str) -> frozenset[str]:
    """The id's name words, plus any size; empty when it has no name word."""
    rest, sizes = _split(model_id)
    words = frozenset(re.findall(r"[a-z]+", rest)) - _VENDOR_WORDS
    if not words:
        return frozenset()
    return words | frozenset(f"size:{s}" for s in sizes)


def version(model_id: str) -> tuple[int, ...]:
    """The id's version numbers, in order: `gpt-6.1-sol` → (6, 1)."""
    rest, _ = _split(model_id)
    return tuple(int(n) for n in re.findall(r"\d+", rest))


def is_newer(old: str, new: str) -> bool:
    """Whether ``new`` is a later version of ``old``'s series."""
    s = series(old)
    return bool(s) and s == series(new) and version(new) > version(old)
