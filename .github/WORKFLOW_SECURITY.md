# Workflow security

Every workflow starts with no token permissions. Jobs declare their own grants;
refresh App tokens are restricted to this repository and the permissions needed
to create data pull requests. Only jobs that push retain checkout credentials.
The refresh content policy and trusted merger are described in
[automation-integrity.md](../docs/automation-integrity.md).

The required `test` aggregate includes actionlint, zizmor's medium-or-higher
findings, a redacted full-history gitleaks scan, dependency audits, Bandit on
package/service/updater code, and CodeQL for Python and JavaScript/TypeScript.
CodeQL SARIF is checked locally for high/critical security findings and errors;
a completed analysis alone is not a vulnerability gate. Repository settings
should also require CodeQL's code-scanning results and `refresh-integrity`.

Security, build, and privileged refresh tools use complete hash-locked dependency closures.
The refresh closure is validated on Linux with Python 3.12. Regenerate
locks with `pip-compile --generate-hashes --strip-extras` from the corresponding
`.in` file and test with `pip install --require-hashes`. Review version changes
and hashes together. Builds use `--no-isolation` so PEP 517 cannot replace the
locked backend. Application and compatibility-test dependency ranges continue
to resolve on the supported Python matrix and are audited separately.

The narrow zizmor exceptions document privileged triggers that execute trusted
base code and checkouts that must push. Runtime installs for the production
soak intentionally match the validated version reported by the service. These
exceptions do not grant a bot permission to merge arbitrary code.

## Release trust

Releases use stable `vMAJOR.MINOR.PATCH` tags. Legacy `-pypi` tags are not accepted
for publication; milestone `-phase-` tags do not publish. The install-verification
workflow still accepts a `-pypi` suffix for historical stable versions.

The verifier and SSH allowed-signers policy come from protected main. A release
tag must be signed by an approved key, name the matching package version, and
point directly to a commit on main. Builds check out that immutable commit.
Each publisher checks that the remote tag still names the verified tag object.
The local release script enforces this policy on new and resumed releases.
Signing failure stops publication.

Production publication retains the manual dispatch on main, `pypi-production`
environment, OIDC trusted publishing, and Sigstore artifacts. Operators must
restrict that environment to main and protect release tag creation, updates,
and deletion. Workflow code alone cannot enforce repository or environment
settings. Add or revoke public signing keys through a reviewed change to
`release-allowed-signers`; never place private keys in the repository.
