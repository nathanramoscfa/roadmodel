# Security policy

## Reporting a vulnerability

Please report security vulnerabilities **privately** to:

**nathan.ramos.github@gmail.com**

Do not file a public GitHub issue for undisclosed security problems.

## What to expect

- **Acknowledgement:** You should receive an acknowledgement within **72
  hours** of a valid report.
- **Embargoed reports:** If we agree to an embargo, we will negotiate a
  **coordinated public disclosure date** with you before any details are
  published.
- **Severity and scope:** We may ask follow-up questions or request a
  minimal reproducer. Please allow time for investigation and fix planning.

## Supported versions

Security fixes are applied to the latest published package release and the
current deployments. Use roadmodel 0.2.83 or later for the private-file, local automation and
request-boundary fixes. Older releases do not receive routine backports.

## Scope

Reports may cover the CLI, MCP server, web app at roadmodel.ai, its API service,
database authorization, automation scripts and GitHub Actions as shipped on
`main`.
Third-party services (model providers, data hosts) are outside this
project's control; route those issues to the respective vendor.

## Service request controls

The authenticated service caps each request body at 1 MiB before JSON parsing,
with a 15-second body-read budget. Request and nested context fields are closed
and bounded; task text remains limited to 50,000 characters. Validation responses
contain a fixed error code, without request values.

Hosted recommendation requests have a 120-second budget for admitting new engine
attempt groups. Each admitted group uses network phase/inactivity timeouts capped
at 60 seconds and the remaining budget, with SDK retries disabled. This is not a
completion deadline or cancellation guarantee: an in-flight provider call can
continue, and the operator lane's two classification votes can outlive a failed
primary call or overlap fallback work. The current registry allows up to four
attempt groups (12 calls with votes) per operator ladder request. A visitor request
uses one call on that visitor's key, with no votes or fallback. Separate edge
fan-out requests have separate budgets; aborting an HTTP request does not cancel
already running provider work.

Visitor-key redaction is request-local across authentication, validation,
threadpool execution and response handling. Standard logging records are scrubbed
after structured fields and filters, before queue handoff. Standard Uvicorn access
records omit client addresses and query strings while retaining route/status fields.
Warning hooks suppress
secret-bearing diagnostics before registry insertion, and remove warning source
objects while a visitor key is in scope. They are installed before lazy SDK imports;
previously captured warning aliases, direct C-level warnings and custom logging
pipelines that bypass standard record/filter handling are outside this guarantee.
Service-owned failure logs contain fixed events and bounded counts.

## Web request controls

Browser mutations require an exact same-origin Origin and compatible Fetch
Metadata. Enabled funding routes also support the existing authenticated machine
bypass with neither Origin nor Fetch Metadata. Explicit foreign origins never
use that exception. Request JSON is streamed into bounded buffers: 512 KiB for
recommendations, 1 MiB aggregate for roadmap history, 32 KiB for profile edits,
and 4 KiB for keyless scoring and key exchange. Gate forms are capped at 16 KiB.
Body reads have a 15-second budget. Roadmap history permits up to 50 messages of
20,000 characters each; the aggregate limit can reject histories below those limits.
Authenticated and mutation responses use private/no-store caching.

The roadmap provider path shares a 120-second abort signal across cache creation,
stream opening and body reads, including its single application retry. SDK retries
are disabled, and browser cancellation aborts the local provider request. Redis
memo waits are capped at two seconds each. Aborting local HTTP work does not
guarantee cancellation or prevent billing for work already accepted remotely.
Web-owned dependency failure logs contain fixed events, without exception objects.

Visitor, keyless, rejected-key and exchange quotas use salted IPs. Migrating
from the previous IP/user-agent key starts a fresh quota window once. Configured
limiter failures and SDK timeouts stop dispatch outside explicit local E2E mode.
Optional Upstash environment variables retain production runtime enforcement.

The daily spend guard remains a post-call meter, not a reservation system.
Concurrent admitted calls, retries and fallback work can exceed its threshold.
Redis waits and the paginated ledger fallback are bounded; when both stores fail,
this guard retains its availability-oriented fail-open policy. Provider account
limits remain the backstop. Aborting an edge request cannot cancel provider work
already admitted by the service.

Recent browser results use one account-scoped store capped at eight runs and
512 KiB. Sign-out, account
changes and explicit clearing remove it and invalidate pending responses. Browser
Supabase cookies intentionally remain readable by the browser auth client, with
SameSite=Lax and Secure on HTTPS; the gate cookie is HttpOnly. CSP retains inline
styles required by the framework and permits the configured Supabase origin;
script execution requires the per-response nonce. OAuth popup compatibility uses
Cross-Origin-Opener-Policy: same-origin-allow-popups.

## Automated security checks

Required CI runs full security-extended CodeQL analysis for Python and JavaScript/
TypeScript, with diff filtering and overlay analysis disabled. Bandit scans every
tracked Python file with locked tools and verified per-file coverage. Missing,
failed or malformed analysis fails the gate. Both scanners bind results to the
immutable checkout and emit typed review evidence without raw messages or snippets.

Reviewed false positives and accepted risks require an exact occurrence in
`.github/security-allowances.json`, including source, tool, query and context
digests plus a rationale. New, changed, duplicate or stale findings fail. The
shared context policy permits only validated updates to the existing catalog data
under its frozen baseline; code, identities, prose and unrelated files require
review again. Native GitHub CodeQL results remain visible independently.

Pull requests also run secret scanning, workflow security checks and audits of
resolved Python and production npm dependencies. These gates supplement review;
they do not establish that every vulnerability or disclosure has been detected.
