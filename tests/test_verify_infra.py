"""Preview protection remains enabled while infrastructure checks verify TLS."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX executable stubs for the Bash infrastructure verifier"
)


@pytest.mark.parametrize(
    ("headers", "accepted"),
    [
        ("HTTP/2 200\r\n\r\n", True),
        ("HTTP/2 404\r\n\r\n", True),
        ("HTTP/2 302\r\nLocation: https://vercel.com/sso-api?nonce=fixture\r\n\r\n", True),
        ("HTTP/2 302\r\nLocation: https://unrelated.invalid/sso-api\r\n\r\n", False),
        ("HTTP/2 302\r\n\r\n", False),
        ("HTTP/2 503\r\n\r\n", False),
    ],
)
def test_preview_tls_response(tmp_path: Path, headers: str, accepted: bool) -> None:
    for name, body in {
        "curl": "import os; print(os.environ['VERIFY_INFRA_TEST_HEADERS'], end='')",
        "dig": "print('fixture.vercel-dns.com.')",
    }.items():
        executable = tmp_path / name
        executable.write_text(f"#!{sys.executable}\n{body}\n")
        executable.chmod(0o700)
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", "scripts/verify-infra.sh"],
        cwd=root,
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "VERIFY_INFRA_TEST_HEADERS": headers,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stdout
    assert "nonce=fixture" not in result.stdout
