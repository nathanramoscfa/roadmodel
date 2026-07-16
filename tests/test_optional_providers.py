"""Provider SDKs are an opt-in ``recommend`` extra (0.2.22, pyproject.toml).

These guard the two properties that make that safe for the offline planning-kit
workflow — which installs with NONE of the provider SDKs present:

  1. Importing the package / CLI must not import anthropic / openai /
     google-genai — each SDK is imported lazily at call time in providers/*.py.
     Run in a fresh subprocess so the check is independent of whatever other
     tests in this session already imported.
  2. Calling a provider whose SDK is absent must raise a ProviderCallError that
     names ``pip install 'roadmodel[recommend]'`` — an actionable hint, not a
     bare ImportError / traceback.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from roadmodel.errors import ProviderCallError
from roadmodel.providers import anthropic as anthropic_provider
from roadmodel.providers import google as google_provider
from roadmodel.providers import openai as openai_provider

_SDK_MODULES = ("anthropic", "openai", "google.genai")


def test_importing_cli_does_not_load_provider_sdks() -> None:
    code = (
        "import sys, roadmodel.cli\n"
        f"leaked = [m for m in {_SDK_MODULES!r} if m in sys.modules]\n"
        "assert not leaked, f'provider SDK imported at import time: {leaked}'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("provider", "import_root"),
    [
        (anthropic_provider, "anthropic"),
        (openai_provider, "openai"),
        (google_provider, "google"),
    ],
)
def test_missing_sdk_raises_actionable_error(
    provider: object, import_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Poisoning the module in sys.modules makes `import <root>` raise ImportError,
    # exercising the lazy-import guard exactly as a bare `pip install roadmodel`
    # environment (no SDKs) would at call time.
    monkeypatch.setitem(sys.modules, import_root, None)
    with pytest.raises(ProviderCallError) as excinfo:
        provider.recommend("prompt", "system", api_key="unused")  # type: ignore[attr-defined]
    assert "roadmodel[recommend]" in str(excinfo.value)
