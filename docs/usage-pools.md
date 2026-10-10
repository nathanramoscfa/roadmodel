# Automatic usage-pool tracking

The stdlib-only collectors in `scripts/` write private, atomic snapshots to
`~/.cache/roadmodel/pools/{source}.json`. Snapshots contain UTC epoch timestamps,
usage percentages, window lengths and reset times. OpenRouter also stores the
current key's numeric dollar usage and limits. Keys, account labels, transcripts
and raw responses never go into snapshots or public commits.

Run collectors and preview the personal table without editing it:

```sh
python3 scripts/collect_codex_pool.py
python3 scripts/collect_openrouter_pool.py
python3 scripts/collect_antigravity_pool.py
python3 scripts/preview_pool_status.py --dry-run
```

Claude's collector is a status-line wrapper:
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
