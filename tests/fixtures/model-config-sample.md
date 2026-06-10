# Model configuration

<!--
Faithful slice of https://code.claude.com/docs/en/model-config.md covering ONLY
the four in-scope effort/thinking sections, used to test
update/extract_claude_code_effort.py offline. The trailing "### Extended
context" heading is the in-scope end boundary (its body is intentionally
omitted). Refresh from the live docs if the parser's expectations change.
-->

### Adjust effort level

[Effort levels](https://platform.claude.com/docs/en/build-with-claude/effort) control adaptive reasoning, which lets the model decide whether and how much to think on each step based on task complexity. Lower effort is faster and cheaper for straightforward tasks, while higher effort provides deeper reasoning for complex problems.

The available effort levels depend on the model. Models not listed here do not support effort:

| Model                   | Levels                                  |
| :---------------------- | :-------------------------------------- |
| Fable 5                 | `low`, `medium`, `high`, `xhigh`, `max` |
| Opus 4.8 and Opus 4.7   | `low`, `medium`, `high`, `xhigh`, `max` |
| Opus 4.6 and Sonnet 4.6 | `low`, `medium`, `high`, `max`          |

If you set a level the active model does not support, Claude Code falls back to the highest supported level at or below the one you set. For example, `xhigh` runs as `high` on Opus 4.6.

The default effort is `high` on Fable 5, Opus 4.8, Opus 4.6, and Sonnet 4.6, and `xhigh` on Opus 4.7.

`low`, `medium`, `high`, and `xhigh` persist across sessions. `max` provides the deepest reasoning with no constraint on token spending and applies to the current session only, except when set through the `CLAUDE_CODE_EFFORT_LEVEL` environment variable.

The `/effort` menu also offers `ultracode`. Ultracode is a Claude Code setting rather than a model effort level: it sends `xhigh` to the model and additionally has Claude orchestrate [dynamic workflows](/en/workflows) for substantive tasks. It applies to the current session only. Set it through `/effort`, or pass `"ultracode": true` via `--settings` or an Agent SDK control request. It is not part of the `effortLevel` setting, the `--effort` flag, or `CLAUDE_CODE_EFFORT_LEVEL`.

#### Choose an effort level

Each level trades token spend against capability. The default suits most coding tasks; adjust when you want a different balance.

| Level       | When to use it                                                                                                                                  |
| :---------- | :---------------------------------------------------------------------------------------------------------------------------------------------- |
| `low`       | Reserve for short, scoped, latency-sensitive tasks that are not intelligence-sensitive                                                          |
| `medium`    | Reduces token usage for cost-sensitive work that can trade off some intelligence                                                                |
| `high`      | Balances token usage and intelligence. Default on Fable 5, Opus 4.8, Opus 4.6, and Sonnet 4.6                                                   |
| `xhigh`     | Deeper reasoning at higher token spend. Default on Opus 4.7                                                                                     |
| `max`       | Can improve performance on demanding tasks but may show diminishing returns and is prone to overthinking. Test before adopting broadly          |
| `ultracode` | A Claude Code setting that plans a [dynamic workflow](/en/workflows) for each substantive task with `xhigh` per-message reasoning. Session-only |

The effort scale is calibrated per model, so the same level name does not represent the same underlying value across models.

#### Use ultrathink for one-off deep reasoning

Include `ultrathink` anywhere in your prompt to request deeper reasoning on that turn without changing your session effort setting. Claude Code recognizes the keyword and adds an in-context instruction. The effort level sent to the API is unchanged. Other phrases such as "think", "think hard", and "think more" are passed through as ordinary prompt text and are not recognized as keywords.

### Extended thinking

Extended thinking is the reasoning Claude emits before responding. On models that support [adaptive reasoning](#adjust-effort-level), the effort level is the primary control for how much thinking happens; the settings below turn thinking on or off and control how it displays.

| Control                        | How to set it                                                                                                                |
| :----------------------------- | :--------------------------------------------------------------------------------------------------------------------------- |
| Toggle for the current session | Press `Option+T` on macOS or `Alt+T` on Windows and Linux                                                                     |
| Set the global default         | Run `/config` and toggle thinking mode. Saved as `alwaysThinkingEnabled` in `~/.claude/settings.json`                         |
| Disable regardless of effort   | Set `MAX_THINKING_TOKENS=0`, which turns thinking off on the Anthropic API except on Fable 5.                                 |

Thinking cannot be turned off on Fable 5. The session toggle, `alwaysThinkingEnabled`, and `MAX_THINKING_TOKENS=0` have no effect there, and Fable 5 decides per step how much to think based on the effort level.

### Extended context
