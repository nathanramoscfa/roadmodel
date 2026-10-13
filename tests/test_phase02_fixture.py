"""Exercise the real Phase 2 determinism fixture across a copy-time boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase02_catalog_fixture_preserves_source_times(tmp_path: Path) -> None:
    script = (ROOT / "scripts/verify-phase02.sh").read_text()
    start = script.index("  # V1.2 — build_catalog determinism")
    end = script.index("  # V1.3 — catalog json pytest", start)
    lines = script[start:end].splitlines()
    copies = [
        i
        for i, line in enumerate(lines)
        if line.lstrip().startswith("cp ") and "docs/model-selector.txt" in line
    ]
    assert len(copies) == 2
    # A real second boundary makes the pre-fix fixture fail deterministically;
    # timestamp-preserving copies retain the source generator input instead.
    lines.insert(copies[1], "  sleep 1.1")
    for relative in [
        "docs/model-selector.txt",
        "docs/model-tier-cost-scale.md",
        "update/build_catalog.py",
        "update/selector_re.py",
    ]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
        os.utime(target, (1_000_000_000, 1_000_000_000))
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    env = dict(os.environ, PYTHON_BIN=sys.executable, TMPDIR=str(temporary))
    env.pop("SOURCE_DATE_EPOCH", None)
    command = (
        "run_fixture() {\nSTEP_POST_PASS=0\nSTEP_POST_FAIL=0\n"
        + "\n".join(lines)
        + '\ntest "$STEP_POST_FAIL" = 0\n}\nrun_fixture\n'
    )
    result = subprocess.run(
        ["bash", "-c", command], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS] V1.2:" in result.stdout
