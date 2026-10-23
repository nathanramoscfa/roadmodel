# Automatic usage-pool tracking

The stdlib-only collectors in `scripts/` write private, atomic snapshots to
`~/.cache/roadmodel/pools/{source}.json`. Snapshots contain UTC epoch timestamps,
usage percentages, window lengths and reset times. OpenRouter also stores the
current key's numeric dollar usage and limits. Keys, account labels, transcripts
and raw responses never go into snapshots or public commits.

Run collectors and preview the personal table without editing it:

```sh
python3 scripts/collect_claude_usage.py
python3 scripts/collect_codex_pool.py
python3 scripts/collect_openrouter_pool.py
python3 scripts/collect_antigravity_pool.py
python3 scripts/preview_pool_status.py --dry-run
```

Claude's primary collector is `python3 scripts/collect_claude_usage.py`. It runs
the supported headless `claude -p /usage`, which the CLI answers locally with no
model usage, from any surface (the VS Code extension never runs the status
line). It records the 5-hour session, the all-models weekly pool and the Fable
weekly sub-cap, so the Fable row updates automatically. It passes the CLI only
`HOME`, `USER` and `PATH`, retries a cold start that prints a cost summary, and
saves nothing when the output is not the expected subscription meters.

Claude's secondary collector is a status-line wrapper (terminal only):
`python3 scripts/collect_claude_pool.py`. It receives the documented status-line
JSON on stdin. With `--original FILE`, it passes the exact original stdin to the
shell command saved in that private JSON statusLine object and preserves its
output and exit code. Without an original it prints `wk 42% · 5h 12%`. Missing
meters print dashes and leave the saved observation alone. Settings installation
must preserve the complete original statusLine object and show a diff first.

Codex reads the newest timestamped account-wide rate-limit event across rollout
logs, regardless of file modification time. It classifies windows by
`window_minutes`, never by the primary/secondary slot. Partial lines are ignored.

OpenRouter makes one GET to `/api/v1/key` using the macOS keychain entry
`roadmodel/OPENROUTER_API_KEY`. Authentication failures retain the previous
snapshot. A fixed prepaid reserve has no automatic reset.

Antigravity runs the supported interactive [`/usage` command](https://www.antigravity.google/docs/cli/commands/usage)
in a bounded local terminal. Its panel can expose separate weekly Gemini and
Claude/GPT groups; the displayed window takes precedence over assumptions about
the plan. A fully unused group can report “Quota available” without a reset.
No reset date is invented. If the supported panel is unavailable, timestamped
quota failures in logs/JSON error records provide an exhausted observation with a
reset five hours after the error. No error means unknown, never headroom.
`--logs-only` skips the interactive readout. No private Google API is invoked.

`pool_usage.decide` owns the state thresholds:

- Exhausted: usage ≥97%, a rate-limit-reached flag, or a quota failure.
- Tight: usage divided by the elapsed window fraction projects ≥100% at reset;
  weekly windows need at least 12 hours elapsed. Also tight: usage ≥85% with
  more than 24 hours remaining.
- Headroom: other fresh, valid observations.
- OpenRouter: exhausted below $1 remaining; tight below 20% of the key's limit.
- Observations older than six hours for weekly windows or one hour for
  five-hour windows cannot change a state. OpenRouter expires after six hours.
  Future timestamps, missing meters and invalid values also preserve state.

The preview preserves manual model sub-caps. Lowering a grouped pool requires
fresh data for every observed group. A known passed reset is handled separately
by the existing table roller. Pay-as-you-go maker keys and local inference have
no usage-pool state.

References: [Claude status-line data](https://code.claude.com/docs/en/statusline),
[OpenRouter current-key meter](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key).

The hourly updater (`roll_pool_status.py`) refreshes the three polling collectors
and applies fresh cached observations plus known reset expiry. It preserves
file permissions, follows the configured context symlink, and replaces the
personal file atomically. Run `--dry-run` to inspect cached changes;
`--dry-run --refresh` refreshes cache too. `--no-collect` skips polling.
The launchd cadence remains hourly and uses Python 3.11 or later.

Preview the Claude settings change with
`python3 scripts/configure_claude_pool.py`; show the diff before invoking
`--install`. The complete original statusLine object stays privately in the
cache, all other settings survive, and repeating installation is a no-op.
`--restore` reinstates the original object (or removes the wrapper when none
existed). The status-line command inherits its existing padding and refresh
options. Claude updates its snapshot during normal usage; the hourly job never
calls a Claude model just to refresh a meter.

Displayed reset times round up to the next minute so minute-resolution table cells never clear a live exhausted window early.

For an account-specific funded pool, bind Antigravity to the expected account
using `--account` or a private `~/.cache/roadmodel/pools/accounts.json` file:
`{"antigravity": "funded-account@example.invalid"}`. A different signed-in
account cannot update the pool, and older snapshots from another account are
ignored. Snapshots store only a digest for identity matching. Bound quota-error
records must identify the matching account; unbound logs cannot change it.
If the funded account is not signed in, existing state is retained until its
supported meter or a matching error record becomes available.

Scoring matches generic collector labels to their funded surface, including
independent Codex weekly and five-hour rows. Claude’s pool does not attach to
Antigravity. An exhausted OpenRouter reserve disables its key’s funding;
prepaid credit states never expire on a timer. Maker pay-as-you-go keys remain
independent. CLI and MCP scoring use the same rules; package changes reach the
hosted recommender only through a release and service floor update.

The saved web profile carries normalized observations in `profiles.pool_states`.
Apply the additive
[`20261010173834_profiles_pool_states.sql`](../infra/supabase/migrations/20261010173834_profiles_pool_states.sql)
migration before deploying the web consumer:

```sh
supabase db push --linked
```

`scripts/push_pool_status.py` uses the Supabase publishable key and a rotating
**per-user session**, with owner-only profile policies. It never reads a
service-role credential. It reads these macOS Keychain entries:

- `roadmodel/SUPABASE_URL`
- `roadmodel/NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable or legacy anon key)
- `roadmodel/POOL_SYNC_REFRESH_TOKEN` (the signed-in user's refresh token)

Provision the first two through the existing Keychain setup. To import a
per-user session, run the following locally and enter its refresh token at the
hidden prompt; never paste credentials into a chat or commit them:

```sh
python3 scripts/push_pool_status.py --import-refresh-token
python3 scripts/push_pool_status.py
```

Import verifies the session before activation and stores the rotated token in
Keychain. Subsequent runs rotate it automatically. A revoked session requires
another import. The account must already have a saved Settings profile; the
uploader derives the owner from the verified session and never creates users.

The uploader merges fresh cached observations with saved states, then PATCHes
only `pool_states`. A timestamp condition retries concurrent profile updates;
ordinary Settings saves omit the field and preserve the latest upload. Missing,
stale, future, malformed, or older observations cannot lower a saved state.
A known passed subscription reset clears its effective state; prepaid credits
never clear on a timer. An unavailable session or network leaves the saved
profile intact and makes the job report failure.

Inspect the allowlisted upload without authentication or network access:

```sh
python3 scripts/push_pool_status.py --dry-run
```

Entries contain only stable pool/source/platform identifiers, state, used
percentage, window duration, and UTC observation/reset timestamps. The personal
context document, account identifiers, logs, API keys and raw provider responses
are never uploaded. The profile mapper forwards saved states through the
keyless scorer and the engine-backed recommendation route; the service renders
them as Usage-pool rows for the shared scorer. Cost annotations disclose an
exhausted subscription or OpenRouter reserve.

After an authenticated write/read round trip succeeds, install the committed
hourly launchd plist (which adds `--sync-web`) using its instructions. The sync
runs even if the local table has no changes. `--dry-run` on the hourly updater
never authenticates or uploads. Owner isolation is covered by the profile's
migration tests; profile retention and recommendation forwarding are covered
by browser tests.
