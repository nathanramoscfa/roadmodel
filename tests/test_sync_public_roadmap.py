# tests/test_sync_public_roadmap.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINTER_PATH = REPO_ROOT / "update" / "sync_public_roadmap.py"
DENY_LIST_PATH = REPO_ROOT / "docs" / "templates" / "public-roadmap-deny-list.txt"
PUBLIC_ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"


def _run_linter(public_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(LINTER_PATH),
            "--check",
            "--public",
            str(public_path),
            "--deny-list",
            str(DENY_LIST_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_doc_passes(tmp_path: Path) -> None:
    fixture = tmp_path / "clean.md"
    fixture.write_text(
        "# Clean public roadmap\n\n"
        "This file contains only provider-agnostic prose with no\n"
        "private vocabulary, no dollar amounts, and no internal-doc\n"
        "references. It should pass the deny-list cleanly.\n"
    )
    result = _run_linter(fixture)
    assert result.returncode == 0, (
        f"Linter unexpectedly failed on clean doc.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_pricing_pattern_fails(tmp_path: Path) -> None:
    fixture = tmp_path / "pricing.md"
    fixture.write_text("# Pricing leak\n\nPro Hosted is $200/mo billed monthly.\n")
    result = _run_linter(fixture)
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "pricing.md:3" in result.stdout


def test_vendor_pattern_fails(tmp_path: Path) -> None:
    fixture = tmp_path / "vendor.md"
    fixture.write_text("# Vendor leak\n\nThe web tier ships on Vercel with Next.js 15.\n")
    result = _run_linter(fixture)
    assert result.returncode == 1
    assert "FAIL  Vercel" in result.stdout
    assert "vendor.md:3" in result.stdout


def test_pro_forma_pattern_fails(tmp_path: Path) -> None:
    fixture = tmp_path / "proforma.md"
    fixture.write_text("# Pro forma leak\n\nsee PRO_FORMA.md for the revenue model.\n")
    result = _run_linter(fixture)
    assert result.returncode == 1
    assert "FAIL  PRO_FORMA" in result.stdout
    assert "proforma.md:3" in result.stdout


def test_actual_public_roadmap_passes() -> None:
    assert PUBLIC_ROADMAP_PATH.is_file(), f"Public roadmap not found at {PUBLIC_ROADMAP_PATH}"
    result = _run_linter(PUBLIC_ROADMAP_PATH)
    assert result.returncode == 0, (
        f"Linter failed against the real ROADMAP.md.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
