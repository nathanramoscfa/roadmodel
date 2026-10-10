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
