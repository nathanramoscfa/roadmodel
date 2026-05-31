# src/roadmodel/providers/__init__.py
from __future__ import annotations

from typing import Protocol


class ProviderAdapter(Protocol):
    def recommend(
        self,
        prompt: str,
        system: str,
        *,
        model: str | None = None,
        api_key: str,
        max_output_tokens: int | None = None,
    ) -> str: ...
