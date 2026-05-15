# src/roadmodel/providers/google.py
from __future__ import annotations

from roadmodel.errors import ProviderCallError

DEFAULT_MODEL = "gemini-3.1-pro"


def recommend(prompt: str, system: str, *, model: str | None = None, api_key: str) -> str:
    try:
        from google import genai
        from google.genai.errors import APIError
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise ProviderCallError(
            "Google GenAI SDK is unavailable; install the 'google-genai' package."
        ) from exc

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model or DEFAULT_MODEL,
            contents=prompt,
            config={"system_instruction": system},
        )
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        raise ProviderCallError("Google response did not contain text output.")
    except ProviderCallError:
        raise
    except APIError as exc:
        raise ProviderCallError(f"Google API call failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive adapter guard
        raise ProviderCallError(f"Google API call failed ({type(exc).__name__}).") from exc
