#!/usr/bin/env python3
"""Seed an allowlisted Keychain credential through a hidden prompt and stdin."""

from __future__ import annotations

import getpass
import hmac
import shlex
import subprocess
import sys
import warnings

NAMES = frozenset(
    "SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY NEXT_PUBLIC_SUPABASE_ANON_KEY "
    "GOOGLE_API_KEY SITE_PASSWORD ROADMODEL_LATENCY_BYPASS_TOKEN UPSTASH_REDIS_URL "
    "UPSTASH_REDIS_TOKEN AA_API_KEY ROADMODEL_INTERNAL_TOKEN ROADMODEL_IP_SALT "
    "POOL_SYNC_REFRESH_TOKEN ANTHROPIC_API_KEY OPENAI_API_KEY DEEPSEEK_API_KEY "
    "XAI_API_KEY GROQ_API_KEY MISTRAL_API_KEY ZAI_API_KEY OPENROUTER_API_KEY "
    "TOGETHER_API_KEY OLLAMA_API_KEY ROADMODEL_API_KEY".split()
)


def seed(name: str) -> bool:
    if name not in NAMES:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Credential (hidden): ")
        if not value or any(c in value for c in "\x00\r\n"):
            return False
        command = shlex.join(
            [
                "add-generic-password",
                "-U",
                "-a",
                getpass.getuser(),
                "-s",
                f"roadmodel/{name}",
                "-w",
                value,
            ]
        )
        subprocess.run(  # noqa: S603 — fixed executable; credential only in stdin
            ["/usr/bin/security", "-i"],
            input=command + "\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        )
        result = subprocess.run(  # noqa: S603 — fixed executable and allowlisted name
            ["/usr/bin/security", "find-generic-password", "-s", f"roadmodel/{name}", "-w"],
            capture_output=True,
            check=True,
            timeout=15,
        )
        # security adds exactly one output newline; password spaces are meaningful.
        actual = result.stdout.removesuffix(b"\n")
        return hmac.compare_digest(actual, value.encode())
    except (
        OSError,
        subprocess.SubprocessError,
        EOFError,
        KeyboardInterrupt,
        getpass.GetPassWarning,
    ):
        return False


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in NAMES:
        print("Usage: seed-prod-secret.py NAME (an approved production credential name).")
        return 64
    if not seed(sys.argv[1]):
        print("Credential storage or verification failed.")
        return 1
    print("Credential stored and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
