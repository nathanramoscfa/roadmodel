"""Preserve Claude memories from this repository's registered git worktrees.

Archives keep every source file and its relative links. Sources are never
changed. A three-way hash baseline protects edits made to imported memories.
This module uses only the standard library and supports Python 3.9+.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

STATE = ".roadmodel/worktree-imports.json"
ARCHIVE = ".roadmodel/memory/worktrees"


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(project), *args],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=30,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "git command failed")
    return result.stdout


def _common(project: Path) -> Path:
    common = Path(_git(project, "rev-parse", "--git-common-dir").strip())
    return (common if common.is_absolute() else project / common).resolve()


def _registered_common(worktree: Path) -> Path:
    """Validate worktree ownership without running Git under another root.

    The Windows sandbox uses a separate user and grants Git trust to the active
    project. Its registered sibling worktrees need no new safe.directory entries:
    their .git pointer and commondir files establish the same relationship.
    """
    git_entry = worktree / ".git"
    if git_entry.is_dir():
        return git_entry.resolve()
    pointer = git_entry.read_text(encoding="utf-8").strip()
    if not pointer.startswith("gitdir: "):
        raise ValueError(f"invalid registered worktree git pointer: {git_entry}")
    git_dir = Path(pointer[8:])
    if not git_dir.is_absolute():
        git_dir = worktree / git_dir
    shared = Path((git_dir / "commondir").read_text(encoding="utf-8").strip())
    return (shared if shared.is_absolute() else git_dir / shared).resolve()


def _slug(project: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", str(project))


def _namespace(project: Path) -> str:
    identity = os.path.normcase(str(project.resolve()))
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", project.name)[:80] or "worktree"
    return f"{name}-{suffix}"


def _atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".roadmodel-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_path(root: Path, destination: Path) -> None:
    # Context setup deliberately links this one directory to an explicitly
    # configured custom store. Validate that choice, then guard descendants
    # relative to its canonical root so the permitted link is not mistaken
    # for an arbitrary redirect inside an archive.
    memory = root / ".roadmodel/memory"
    if memory in destination.parents:
        _safe_path(root, memory.parent)
        canonical = memory.resolve()
        if os.path.normcase(str(canonical)) != os.path.normcase(str(memory.absolute())):
            settings_path = root / ".claude/settings.local.json"
            settings = (
                json.loads(settings_path.read_text(encoding="utf-8-sig"))
                if settings_path.exists()
                else {}
            )
            configured = settings.get("autoMemoryDirectory") if isinstance(settings, dict) else None
            if (
                not isinstance(configured, str)
                or not Path(configured).expanduser().is_absolute()
                or os.path.normcase(str(Path(configured).expanduser().resolve()))
                != os.path.normcase(str(canonical))
            ):
                raise ValueError(f"memory redirect differs from its configured store: {memory}")
        destination = canonical / destination.relative_to(memory)
        root = canonical
    # Includes junctions on Python versions before Path.is_junction exists.
    path = destination
    while path != root:
        if path.is_symlink() or (
            path.exists()
            and os.path.normcase(str(path.resolve())) != os.path.normcase(str(path.absolute()))
        ):
            raise ValueError(f"archive path redirects outside its location: {path}")
        path = path.parent


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def import_worktree_memory(
    project: Path, home: Path, dry_run: bool = False, check: bool = False
) -> tuple[list[str], bool]:
    """Import registered worktree memories; return report lines and success.

    ``check`` reports unapplied source changes without writing; ``dry_run``
    reports the proposed import. Local modifications and source deletions are
    preserved, and simultaneous source/local modifications return a conflict.
    """
    lines: list[str] = []
    try:
        return _import(project.resolve(), home, dry_run, check, lines)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return [*lines, f"worktree memory: FAILED: {error}"], False


def _import(
    project: Path, home: Path, dry_run: bool, check: bool, lines: list[str]
) -> tuple[list[str], bool]:
    common = _common(project)
    if _git(project, "ls-files", "--", ARCHIVE, STATE).strip():
        raise ValueError("private worktree memory paths are tracked; refusing import")
    state_path = project / STATE
    _safe_path(project, state_path)
    state = (
        json.loads(state_path.read_text(encoding="utf-8-sig"))
        if state_path.exists()
        else {"version": 1, "imports": {}}
    )
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("imports"), dict)
    ):
        raise ValueError("invalid worktree memory provenance file")
    before = json.dumps(state, sort_keys=True)
    imports = state["imports"]
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
    fields = _git(project, "worktree", "list", "--porcelain", "-z").split("\0")
    worktrees = sorted(
        {Path(field[9:]).resolve() for field in fields if field.startswith("worktree ")}
    )
    # Keep the observed destination hash and the prior provenance value with
    # each queued write. Another agent can edit an archive while the remaining
    # stores are scanned, so the final write must recheck that observation.
    pending: list[tuple[Path, bytes, Optional[str], dict, str, Optional[str]]] = []
    conflict = False
    for worktree in worktrees:
        if worktree == project or not worktree.exists():
            continue
        if _registered_common(worktree) != common:
            raise ValueError(f"registered worktree now belongs to another repo: {worktree}")
        source = config / "projects" / _slug(worktree) / "memory"
        if not source.is_dir():
            continue
        shared = (project / ".roadmodel/memory").resolve()
        if source.resolve() == shared or shared in source.resolve().parents:
            continue  # Already uses the shared root; never recursively import it.
        namespace = _namespace(worktree)
        destination = project / ARCHIVE / namespace
        _safe_path(project, destination)
        record = imports.get(namespace, {})
        if not isinstance(record, dict) or not isinstance(record.get("files", {}), dict):
            raise ValueError(f"invalid provenance for {namespace}")
        if record and record.get("source") != str(source):
            raise ValueError(f"source changed for {namespace}; inspect its provenance")
        baseline = dict(record.get("files", {}))
        count = 0
        for entry in sorted(source.rglob("*")):
            relative = entry.relative_to(source).as_posix()
            if entry.is_symlink() or (
                entry.exists()
                and os.path.normcase(str(entry.resolve()))
                != os.path.normcase(str(source.resolve() / relative))
            ):
                raise ValueError(f"source contains a redirected memory path: {entry}")
            if not entry.is_file():
                continue
            content = entry.read_bytes()
            source_hash = _hash(content)
            target = destination / relative
            _safe_path(project, target)
            previous_hash = baseline.get(relative)
            current_hash = _hash(target.read_bytes()) if target.exists() else None
            count += 1
            if current_hash == source_hash:
                baseline[relative] = source_hash
            elif previous_hash is not None and source_hash == previous_hash:
                # Only the local copy changed (or was deleted); keep that edit.
                continue
            elif current_hash == previous_hash:
                pending.append((target, content, current_hash, baseline, relative, previous_hash))
                baseline[relative] = source_hash
            else:
                conflict = True
                lines.append(f"worktree memory: conflict preserved: {target}")
        if count:
            imports[namespace] = {
                "worktree": str(worktree),
                "source": str(source),
                "archive": str(destination.relative_to(project)),
                "files": baseline,
            }
            lines.append(f"worktree memory: {worktree.name}: {count} source files")
    if not imports:
        return [*lines, "worktree memory: no additional memories"], not conflict

    # Keep old archives discoverable after their worktree or source disappears.
    index_lines = [
        "# Memories imported from git worktrees",
        "",
        "Complete copies of each source store, with relative links preserved.",
        "Sources stay intact. Provenance and update baselines are in",
        "`.roadmodel/worktree-imports.json`. Local edits are preserved.",
        "",
    ]
    for namespace, record in sorted(imports.items()):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", namespace):
            raise ValueError("invalid archive namespace in provenance")
        if not isinstance(record, dict) or not isinstance(record.get("files"), dict):
            raise ValueError(f"invalid provenance for {namespace}")
        index_target = "MEMORY.md" if "MEMORY.md" in record["files"] else ""
        index_lines.append(f"- [{namespace}]({namespace}/{index_target})")
    index_content = ("\n".join(index_lines) + "\n").encode("utf-8")
    index_path = project / ARCHIVE / "INDEX.md"
    _safe_path(project, index_path)
    if not index_path.exists() or index_path.read_bytes() != index_content:
        existing = _hash(index_path.read_bytes()) if index_path.exists() else None
        if existing != state.get("index_hash"):
            conflict = True
            lines.append(f"worktree memory: conflict preserved: {index_path}")
        else:
            pending.append(
                (index_path, index_content, existing, state, "index_hash", state.get("index_hash"))
            )
            state["index_hash"] = _hash(index_content)
    changed = before != json.dumps(state, sort_keys=True)
    if check:
        if pending or changed:
            lines.append("worktree memory: imports need refresh")
        return lines, not (pending or changed or conflict)
    if dry_run:
        lines.append(f"worktree memory: would write {len(pending)} files")
        return lines, not conflict

    # Private local excludes apply across worktrees; no tracked rules are edited.
    exclude = common / "info/exclude"
    exclusion = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    updated = exclusion
    for pattern in (f"/{ARCHIVE}/", f"/{STATE}"):
        if pattern not in exclusion.splitlines():
            updated = updated.rstrip("\n") + "\n" + pattern + "\n"
    if exclusion != updated:
        _atomic(exclude, updated.encode("utf-8"))
    written = 0
    for target, content, expected_hash, baseline, key, previous_hash in pending:
        _safe_path(project, target)
        current_hash = _hash(target.read_bytes()) if target.exists() else None
        if current_hash != expected_hash:
            # Do not claim the incoming source revision was applied: keeping
            # its old baseline makes the conflict visible on subsequent runs.
            if previous_hash is None:
                baseline.pop(key, None)
            else:
                baseline[key] = previous_hash
            conflict = True
            lines.append(f"worktree memory: concurrent edit preserved: {target}")
            continue
        _atomic(target, content)
        written += 1
    if before != json.dumps(state, sort_keys=True):
        _atomic(state_path, (json.dumps(state, indent=2) + "\n").encode("utf-8"))
    lines.append(f"worktree memory: imported {written} changed files")
    return lines, not conflict
