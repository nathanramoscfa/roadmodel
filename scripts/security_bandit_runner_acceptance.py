"""Disposable runner acceptance only; never scan the working repository."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
S = REPO / "scripts"
NAMES = [
    "check_bandit.py",
    "security_bandit.py",
    "security_manifest.py",
    "security_sarif.py",
    "security_source.py",
    "check_codeql_sarif.py",
    "security_catalog.py",
]
SOURCE = Path(sys.prefix)
checks = []
count = 0


def checked(label, predicate):
    if not predicate:
        raise RuntimeError(label)
    checks.append(label)


def command(argv, env, timeout=180):
    return subprocess.run(  # noqa: S603 — fixed synthetic Git/Python commands
        argv,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def main():
    global count
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON", "BANDIT"))}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="bandit-synthetic-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        repo = root / "repo"
        repo.mkdir()
        venv = root / "tool"
        made = command(
            [str(SOURCE / "bin/python"), "-I", "-B", "-m", "venv", "--without-pip", str(venv)], env
        )
        checked("isolated_fixture_environment", made.returncode == 0)
        source_site = next(SOURCE.glob("lib/python*/site-packages"))
        target_site = next(venv.glob("lib/python*/site-packages"))
        # Copy only the locked Bandit dependency closure; no installed source edit.
        for component in [
            "bandit",
            "packaging",
            "yaml",
            "_yaml",
            "stevedore",
            "rich",
            "markdown_it",
            "mdurl",
            "pygments",
            "typing_extensions.py",
        ]:
            origin = source_site / component
            if origin.is_dir():
                shutil.copytree(
                    origin,
                    target_site / component,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            elif origin.exists():
                shutil.copyfile(origin, target_site / component)
        for prefix in [
            "bandit",
            "packaging",
            "pyyaml",
            "stevedore",
            "rich",
            "markdown_it_py",
            "mdurl",
            "pygments",
            "typing_extensions",
        ]:
            matches = list(source_site.glob(prefix + "-*.dist-info"))
            for origin in matches:
                target = target_site / origin.name
                shutil.copytree(
                    origin, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                )
                record = target / "RECORD"
                rows = list(csv.reader(io.StringIO(record.read_text())))
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerows(row for row in rows if not row[0].endswith(".pyc"))
                record.write_text(output.getvalue())
        scripts = repo / "scripts"
        scripts.mkdir()
        for name in NAMES:
            shutil.copyfile(S / name, scripts / name)
        (repo / ".github").mkdir()
        for name in ["requirements-security.txt", "requirements-security.in"]:
            shutil.copyfile(REPO / ".github" / name, repo / ".github" / name)
        (repo / "fixture.py").write_text('value = eval("PRIVATE_SYNTHETIC_CANARY")  # nosec B307\n')
        (repo / "empty.py").write_text("")
        (repo / ".bandit").write_text("[bandit]\nskips = B102,B307,B404,B603,B607\n")
        (repo / "pyproject.toml").write_text(
            '[tool.bandit]\nskips = ["B102", "B307", "B404", "B603", "B607"]\n'
        )

        def git(*args):
            result = command(["git", "-C", str(repo), *args], env)
            checked("git_fixture_" + str(len(checks)), result.returncode == 0)
            return result.stdout.decode().strip()

        git("init", "-q")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("add", ".")
        git("-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic fixture")
        commit = git("rev-parse", "HEAD")
        env.update(
            GITHUB_SHA=commit,
            GITHUB_EVENT_NAME="push",
            GITHUB_REF="refs/heads/main",
            GITHUB_RUN_ID="1",
            GITHUB_RUN_ATTEMPT="1",
        )
        for key in ["CODEQL_PR_HEAD_SHA", "CODEQL_PR_BASE_SHA"]:
            env.pop(key, None)
        python = str(venv / "bin/python")
        cli = str(scripts / "check_bandit.py")
        snapshot = root / "snapshot.json"

        def run(output="review.json"):
            return command(
                [
                    python,
                    "-I",
                    "-B",
                    cli,
                    "run",
                    "--repo",
                    str(repo),
                    "--snapshot",
                    str(snapshot),
                    "--review-output",
                    str(root / output),
                ],
                env,
            )

        result = command(
            [python, "-I", "-B", cli, "snapshot", "--repo", str(repo), "--output", str(snapshot)],
            env,
        )
        checked("snapshot_cli", result.returncode == 0 and snapshot.exists())
        result = run()
        count += 1
        checked("valid_locked_runner_creates_typed_review", (root / "review.json").exists())
        value = json.loads((root / "review.json").read_text())
        checked("unapproved_findings_fail", result.returncode == 1 and value["raw_blocking"] > 0)
        checked(
            "fixture_nosec_and_config_do_not_hide_rule",
            any(
                x["proof"]["rule_id"] == "B307" and x["proof"]["source"]["path"] == "fixture.py"
                for x in value["candidates"]
            ),
        )
        checked(
            "dynamic_python_coverage",
            value["coverage"]["tracked_python_files"] == len(NAMES) + 2
            and value["coverage"]["covered_files"] == len(NAMES) + 2,
        )
        checked(
            "raw_text_not_output",
            b"PRIVATE_SYNTHETIC_CANARY" not in result.stdout + result.stderr
            and "PRIVATE_SYNTHETIC_CANARY" not in json.dumps(value),
        )
        checked(
            "typed_review_only",
            value["purpose"] == "review-only"
            and value["active_allowances"] == 0
            and not (repo / ".github/security-allowances.json").exists(),
        )
        checked("private_review_mode", (root / "review.json").stat().st_mode & 0o777 == 0o600)
        checked(
            "source_and_run_bound",
            value["source_snapshot"]["commit"] == commit
            and value["execution"]["analyzed_commit"] == commit
            and value["execution"]["scanner"] == "bandit",
        )
        # A real fixture scan with a simulated scanner-internal error must refuse
        # even if its final file inventory/metrics would otherwise be complete.
        internal = (
            "import sys,json,logging;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import check_bandit as c;guard=c.uncached_entrypoints();guard.__enter__();logging.disable(logging.CRITICAL);from bandit.core.manager import BanditManager;logging.disable(logging.NOTSET);original=BanditManager.run_tests\n"
            + "def fault(self):\n original(self);logging.getLogger('bandit.fixture').error('PRIVATE_INTERNAL_EVENT')\n"
            + "BanditManager.run_tests=fault\ntry:\n c.scan_worker(c.SharedGitTree(Path(sys.argv[2])));print(json.dumps({'refused':False}))\nexcept Exception:\n print(json.dumps({'refused':True}))"
        )
        response = command([python, "-I", "-B", "-c", internal, str(scripts), str(repo)], env)
        count += 1
        checked(
            "internal_scanner_error_refused",
            response.returncode == 0
            and json.loads(response.stdout) == {"refused": True}
            and b"PRIVATE_INTERNAL_EVENT" not in response.stdout + response.stderr,
        )
        # Changing only the isolated environment prefix must not change identity.
        second = root / "other-tool"
        made = command(
            [str(SOURCE / "bin/python"), "-I", "-B", "-m", "venv", "--without-pip", str(second)],
            env,
        )
        checked("second_fixture_environment", made.returncode == 0)
        second_site = next(second.glob("lib/python*/site-packages"))
        shutil.copytree(target_site, second_site, dirs_exist_ok=True)
        identity_code = "import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import check_bandit as c;print(json.dumps(c.tool_identity(c.SharedGitTree(Path(sys.argv[2])))))"
        compared = command(
            [str(second / "bin/python"), "-I", "-B", "-c", identity_code, str(scripts), str(repo)],
            env,
        )
        checked(
            "identity_stable_across_environment_prefixes",
            compared.returncode == 0 and json.loads(compared.stdout) == value["tool_identity"],
        )
        result = run()
        count += 1
        checked(
            "existing_output_refused",
            result.returncode == 1 and json.loads((root / "review.json").read_text()) == value,
        )
        (root / "link.json").symlink_to(root / "review.json")
        result = run("link.json")
        count += 1
        checked(
            "symlink_output_refused",
            result.returncode == 1 and json.loads((root / "review.json").read_text()) == value,
        )
        (repo / "untracked.py").write_text("value=1\n")
        result = run("untracked.json")
        checked(
            "untracked_refused_before_scan",
            result.returncode == 1 and not (root / "untracked.json").exists(),
        )
        (repo / "untracked.py").unlink()
        source = repo / "fixture.py"
        original = source.read_bytes()
        source.write_bytes(original + b"changed=1\n")
        result = run("changed.json")
        checked(
            "changed_source_refused",
            result.returncode == 1 and not (root / "changed.json").exists(),
        )
        source.write_bytes(original)
        package = target_site / "bandit/core/manager.py"
        original = package.read_bytes()
        package.write_bytes(original + b"\n# fixture tamper\n")
        result = run("tamper.json")
        checked(
            "installed_scanner_hash_tamper_refused",
            result.returncode == 1 and not (root / "tamper.json").exists(),
        )
        package.write_bytes(original)
        extra = target_site / "bandit/unbound.py"
        extra.write_text("value=1\n")
        result = run("extra.json")
        checked(
            "unrecorded_package_module_refused",
            result.returncode == 1 and not (root / "extra.json").exists(),
        )
        extra.unlink()
        cache = target_site / "bandit/__pycache__"
        cache.mkdir(exist_ok=True)
        pyc = cache / "fixture.pyc"
        pyc.write_bytes(b"synthetic")
        result = run("cache.json")
        checked(
            "unverified_bytecode_refused",
            result.returncode == 1 and not (root / "cache.json").exists(),
        )
        pyc.unlink()
        cache.rmdir()
        foreign = target_site / "fixture_plugin-1.dist-info"
        foreign.mkdir()
        (foreign / "METADATA").write_text("Name: fixture-plugin\nVersion: 1\n")
        (foreign / "entry_points.txt").write_text(
            "[bandit.plugins]\nfixture = fixture_plugin:run\n"
        )
        result = run("plugin.json")
        checked(
            "foreign_bandit_plugin_refused",
            result.returncode == 1 and not (root / "plugin.json").exists(),
        )
        shutil.rmtree(foreign)
        alias = target_site / "fixture_alias-1.dist-info"
        alias.mkdir()
        (alias / "METADATA").write_text("Name: bandit\nVersion: 1.9.4\n")
        (alias / "entry_points.txt").write_text(
            "[bandit.plugins]\nfixture_alias = fixture_alias:run\n"
        )
        (target_site / "fixture_alias.py").write_text(
            "import os\nfrom pathlib import Path\nPath(os.environ['FIXTURE_MARKER']).write_text('executed')\ndef run(): pass\n"
        )
        env["FIXTURE_MARKER"] = str(root / "plugin-executed")
        result = run("alias.json")
        checked(
            "masquerading_plugin_refused_before_import",
            result.returncode == 1
            and not (root / "alias.json").exists()
            and not (root / "plugin-executed").exists(),
        )
        checked("no_checkout_bytecode", not list(repo.rglob("*.pyc")))
    receipt = {
        "schema": 1,
        "scope": "disposable-synthetic-fixture-only",
        "checks_passed": len(checks),
        "checks": checks,
        "actual_fixture_scans": count,
        "working_tree_scans": 0,
        "active_allowances": 0,
    }
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = main()
        sys.path.insert(0, str(S))
        from check_codeql_sarif import write_receipt

        write_receipt(args.output, receipt)
        print(
            json.dumps(
                {
                    key: receipt[key]
                    for key in (
                        "scope",
                        "checks_passed",
                        "actual_fixture_scans",
                        "working_tree_scans",
                        "active_allowances",
                    )
                }
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "fixture-refused",
                    "last_success": checks[-1] if checks else None,
                    "fixed_test_label": str(exc)
                    if isinstance(exc, RuntimeError)
                    else type(exc).__name__,
                }
            )
        )
        raise SystemExit(1) from None
