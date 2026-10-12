# Automated catalog changes

Refreshes may update existing numeric prices and rating letters. Reviewed
instructions, identities, method descriptions and subscription coverage remain
fixed. New models, changed capabilities and editorial changes use an ordinary
reviewed pull request.

The raw curation guard quarantines proposals outside that boundary. A final
guard reconstructs generated prose from the base document and bounded data,
then verifies the rendered selector and catalog. Rejected content is never
copied into the guard's public report. A quarantined proposal does not advance
the successful-source hash.

The default-branch refresh merger reads candidate commits as data through the
GitHub API. It checks producer provenance, allowed paths, regular file modes,
instruction integrity and every CI result, then merges only the verified head
commit. Producer workflows do not enable native auto-merge. A scheduled catch-up
retries open refreshes after checks or rebases finish. Mark a PR as draft, or
close it, to stop that merger.

`refresh-integrity` is a separate base-context check for the refresh bot. The
repository administrator should require it in main's branch protection,
alongside `test`; adding the workflow does not change repository settings.

Locally, run `python update/automation_integrity.py --base HEAD` after all
generators. The check executes only the trusted checkout's generator code.
