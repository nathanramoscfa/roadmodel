<!-- tests/fixtures/model-config-sample-2026-09.md
Verbatim in-scope span of https://code.claude.com/docs/en/model-config.md
as published 2026-09-04, plus the terminating heading isolate_in_scope
scans for. This is the wording that broke the extractor for 24 days: the
ultrathink pass-through sentence was reworded from "are not recognized as
keywords" to "doesn't recognize them as keywords". Do not paraphrase this
file — its value is that it is exactly what the docs say. -->

### Adjust effort level

[Effort levels](https://platform.claude.com/docs/en/build-with-claude/effort) control adaptive reasoning, which lets the model decide whether and how much to think on each step based on task complexity. Lower effort is faster and cheaper for straightforward tasks, while higher effort provides deeper reasoning for complex problems.

The available effort levels depend on the model. Models not listed here do not support effort:

| Model                                    | Levels                                  |
| :--------------------------------------- | :-------------------------------------- |
| Fable 5.1 and Fable 5                    | `low`, `medium`, `high`, `xhigh`, `max` |
| Opus 5, Sonnet 5, Opus 4.8, and Opus 4.7 | `low`, `medium`, `high`, `xhigh`, `max` |
| Opus 4.6 and Sonnet 4.6                  | `low`, `medium`, `high`, `max`          |

If you set a level the active model does not support, Claude Code falls back to the highest supported level at or below the one you set. For example, `xhigh` runs as `high` on Opus 4.6. Your organization can also cap which levels are available for a model; see [Organization effort limits](#organization-effort-limits).

With the [`ultracode`](/docs/en/settings-reference#ultracode) setting off, Claude Code resolves the session's effort level in this order, taking the first that applies:

1. An explicit choice: the [`CLAUDE_CODE_EFFORT_LEVEL`](/docs/en/env-vars#variables) environment variable, launching with `--effort`, or `/effort` in the session ([a non-interactive `/effort` has narrower effect](#non-interactive-effort))
2. The model's default effort, on Fable 5, Opus 4.8, or Opus 4.7: from the first time you run one of these models, Claude Code holds that model's default effort across sessions, even when your settings resolve a different level, until you change effort once, for example with an interactive `/effort`, the `/model` picker's effort slider, or `--effort` at launch. Opus 5 and Fable 5.1 have no such hold
3. Your settings: the level you saved for the model or an [`effortLevel`](/docs/en/settings-reference#effortlevel) key, with the precedence between them and across settings files stated at [`modelSettings`](/docs/en/settings-reference#modelsettings)
4. The model's default effort: `high` on every model that supports effort, except that Opus 4.7 defaults to `xhigh` and, when your organization sets a default effort level for its [organization default model](#organization-default-model), that level is the default when you run that model

When you set `low`, `medium`, `high`, or `xhigh` in an interactive session on your machine, Claude Code saves the level and applies it in later sessions. It saves the level per model, under the [`modelSettings`](/docs/en/settings-reference#modelsettings) key in your user settings, so each model keeps its own saved level.

`max` is the deepest reasoning level. Unless you set it through the `CLAUDE_CODE_EFFORT_LEVEL` environment variable, Claude Code applies `max` to the current session only.

<Note>
  A level you pick from the effort control on a phone or browser connected through [Remote Control](/docs/en/remote-control#what-connected-devices-see) applies to that session only.
</Note>

<span id="non-interactive-effort" />

A level set with `/effort` in [non-interactive mode](/docs/en/headless), with the `-p` flag, applies to the current session only and isn't saved as your default. It also doesn't count as the one change that ends the model-default step above on Fable 5, Opus 4.8, or Opus 4.7: while that step is in effect, a non-interactive `/effort` reports `Not applied`, so pass `--effort` at launch instead.

The `/effort` menu also offers `ultracode`. Ultracode is a Claude Code setting rather than a model effort level: it sends `xhigh` to the model and additionally has Claude orchestrate [dynamic workflows](/docs/en/workflows) for substantive tasks. For where it can be set persistently, see the [`ultracode`](/docs/en/settings-reference#ultracode) setting.

You can turn on ultracode through any of the following:

* **`/effort`**: run `/effort ultracode`, or select it from the menu
* **`--effort` flag**: launch with `claude --effort ultracode`, which starts the session at `xhigh` effort with ultracode on
* **`ultracode` setting**: set [`"ultracode": true`](/docs/en/settings-reference#ultracode) in a settings file, with `--settings`, or in an Agent SDK control request. An [`applyFlagSettings()`](/docs/en/agent-sdk/typescript#applyflagsettings) request also accepts `effortLevel: "ultracode"`
* **`/model` picker**: move the effort slider to `ultracode` with the arrow keys while you choose a model. Claude Code turns it on for the current session, even when you save that model as your default

Passing `ultracode` to the `--effort` flag or the Agent SDK `effortLevel` value requires Claude Code v2.1.203 or later. Before v2.1.203, `--effort ultracode` printed `Unknown --effort value 'ultracode'` and the session started at the default effort.

The persisted `effortLevel` setting and the `CLAUDE_CODE_EFFORT_LEVEL` environment variable don't accept `ultracode`. When `CLAUDE_CODE_EFFORT_LEVEL` is set to a level other than `xhigh`, requests run at that level and ultracode's workflow orchestration stays inactive. Selecting ultracode then shows a warning that the environment variable overrides effort for the session.

When ultracode isn't available, for example when [workflows are turned off](/docs/en/workflows#turn-workflows-off), `--effort ultracode` sets `xhigh` effort only.

#### Choose an effort level

Each level trades token spend against capability. The default suits most coding tasks; adjust when you want a different balance.

| Level       | When to use it                                                                                                                         |
| :---------- | :------------------------------------------------------------------------------------------------------------------------------------- |
| `low`       | Reserve for short, scoped, latency-sensitive tasks that are not intelligence-sensitive                                                 |
| `medium`    | Reduces token usage for cost-sensitive work that can trade off some intelligence                                                       |
| `high`      | Balances token usage and intelligence. The default on every model except Opus 4.7                                                      |
| `xhigh`     | Deeper reasoning at higher token spend. The default on Opus 4.7                                                                        |
| `max`       | Can improve performance on demanding tasks but may show diminishing returns and is prone to overthinking. Test before adopting broadly |
| `ultracode` | A Claude Code setting that plans a [dynamic workflow](/docs/en/workflows) for each substantive task with `xhigh` per-message reasoning      |

The effort scale is calibrated per model, so the same level name does not represent the same underlying value across models.

#### Use ultrathink for one-off deep reasoning

Include `ultrathink` anywhere in your prompt to request deeper reasoning on that turn without changing your session effort setting. Claude Code recognizes the keyword and adds an in-context instruction. The effort level sent to the API is unchanged. Claude Code passes other phrases such as "think", "think hard", and "think more" through as ordinary prompt text and doesn't recognize them as keywords.

#### Set the effort level

You can change effort through any of the following:

* **`/effort`**: run `/effort` with no arguments to open an interactive slider, `/effort` followed by a level name to set it directly, or `/effort auto` to clear your saved level for the active model. You can run it while Claude is working, and once you confirm the [cache warning](/docs/en/prompt-caching#changing-effort-level), if Claude Code shows one, Claude Code applies the new level to the next request in the turn
* **In `/model`**: use left/right arrow keys to adjust the effort slider when selecting a model
* **`--effort` flag**: pass a level name to set it for a single session when launching Claude Code
* **Environment variable**: set `CLAUDE_CODE_EFFORT_LEVEL` to a level name or `auto`
* **Settings**: set a per-model level in [`modelSettings`](/docs/en/settings-reference#modelsettings), or set [`effortLevel`](/docs/en/settings-reference#effortlevel) to `low`, `medium`, `high`, or `xhigh` as the default for models without one. `max` isn't accepted in either key, and `ultracode` has its own [`ultracode`](/docs/en/settings-reference#ultracode) key
* **From a connected device**: in a [Remote Control](/docs/en/remote-control#what-connected-devices-see) session, pick a level from the effort control on your phone or in your browser. The level applies to the current session only. Requires Claude Code v2.1.234 or later
* **Skill and subagent frontmatter**: set `effort` in a [skill](/docs/en/skills#frontmatter-reference) or [subagent](/docs/en/sub-agents#supported-frontmatter-fields) markdown file to override the effort level when that skill or subagent runs

Frontmatter effort applies when that skill or subagent is active, overriding the session level but not the environment variable.

The `effortLevel` key in [managed settings](/docs/en/managed-settings) is a starting default, not enforcement: users can change it for a session with `/effort` or `--effort`, and the managed value re-asserts as the default in new sessions.

The effort slider appears in `/model` when a supported model is selected. The current effort level is also shown in the session header next to the model name, for example "with low effort", so you can confirm which setting is active without opening `/model`. The footer also briefly shows the effort level at startup and when it changes.

#### Adaptive reasoning and fixed thinking budgets

Adaptive reasoning makes thinking optional on each step, so Claude can respond faster to routine prompts and reserve deeper thinking for steps that benefit from it. If you want Claude to think more or less often than the current level produces, you can say so directly in your prompt or in `CLAUDE.md`; the model responds to that guidance within its effort setting.

Fable 5.1, Fable 5, Sonnet 5, and Opus 4.7 and later always use adaptive reasoning. The fixed thinking budget mode and `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` do not apply to them.

On Opus 4.6 and Sonnet 4.6, you can set `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` to revert to the previous fixed thinking budget controlled by `MAX_THINKING_TOKENS`. See [environment variables](/docs/en/env-vars).

### Extended thinking

Extended thinking is the reasoning Claude emits before responding. On models that support [adaptive reasoning](#adjust-effort-level), the effort level is the primary control for how much thinking happens; the settings below turn thinking on or off and control how it displays. With thinking turned off on the Anthropic API, Claude Code sends effort `high` instead of a higher level to models it knows [don't accept that combination](/docs/en/errors#effort-isnt-available-with-thinking-turned-off), such as Opus 5.

| Control                                 | How to set it                                                                                                                                                                                                                                                                                                                                                                           |
| :-------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Toggle for the current session          | Press `Option+T` on macOS or `Alt+T` on Windows and Linux                                                                                                                                                                                                                                                                                                                               |
| Set the global default                  | Run `/config` and toggle thinking mode. Saved as `alwaysThinkingEnabled` in `~/.claude/settings.json`                                                                                                                                                                                                                                                                                   |
| Disable through an environment variable | Set [`MAX_THINKING_TOKENS=0`](/docs/en/env-vars), which turns thinking off on the Anthropic API except on Fable 5.1 and Fable 5. On [third-party providers](/docs/en/third-party-integrations) this omits the `thinking` parameter instead, and adaptive-reasoning models may still think. Other values apply only with a [fixed thinking budget](#adaptive-reasoning-and-fixed-thinking-budgets) |

Thinking cannot be turned off on Fable 5.1 or Fable 5. The session toggle, `alwaysThinkingEnabled`, and `MAX_THINKING_TOKENS=0` have no effect there, and the model decides per step how much to think based on the effort level.

Claude Code collapses thinking output by default. Press `Ctrl+O` to toggle verbose mode and see the reasoning as gray italic text. Interactive sessions on the Anthropic API receive redacted thinking blocks by default, so set `showThinkingSummaries: true` in [settings](/docs/en/settings) if you want the full summaries available when you expand. You are charged for all thinking tokens generated, even when collapsed or redacted.

### Extended context
