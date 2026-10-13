"""Share one closed policy manifest between required security scanner gates."""

from security_sarif import MANIFEST_PATH as LEGACY_PATH
from security_sarif import arr, digest, obj, require
from security_source import GitTree

MANIFEST_PATH = ".github/security-allowances.json"
EMPTY = {"schema": 1, "context_policy": "whole-tree-v1", "codeql": [], "bandit": []}


def manifest(value):
    value = obj(value)
    require(set(value) == set(EMPTY) and type(value["schema"]) is int and value["schema"] == 1)
    require(
        value["context_policy"] == "whole-tree-v1"
        or isinstance(value["context_policy"], dict)
        and value["context_policy"].get("mode") == "typed-catalog-v1"
    )
    for scanner in ("codeql", "bandit"):
        require(len(arr(value[scanner])) <= 10000)
        for entry in value[scanner]:
            obj(entry)
    return value


class SharedGitTree(GitTree):
    manifest_path = MANIFEST_PATH

    def context_digest(self, excluded=MANIFEST_PATH):
        # Compatibility with the original CodeQL evaluator's explicit argument.
        # Regardless of its spelling, only the combined manifest is excluded.
        require(excluded in {MANIFEST_PATH, LEGACY_PATH})
        return digest(
            {
                "policy": "whole-tree-v1",
                "files": [
                    [path, row["mode"], row["sha256"]]
                    for path, row in sorted(self.entries.items())
                    if path != MANIFEST_PATH
                ],
            }
        )


def codeql_namespace(value):
    value = manifest(value)
    return {"schema": 1, "context_policy": value["context_policy"], "entries": value["codeql"]}


def selected_context(tree, policy):
    if policy == "whole-tree-v1":
        return tree.context_digest()
    from security_catalog import context_digest

    return context_digest(tree, policy)
