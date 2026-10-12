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

Security fixes are applied to the **latest released minor** version line of
this repository. Older tags may not receive backports unless noted in a
release announcement.

## Scope

Reports should concern this repository and its documented workflows (for
example, automation scripts and GitHub Actions) as shipped on `main`.
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
