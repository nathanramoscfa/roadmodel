<!-- tests/fixtures/model-config-sample-2026-10-20.md
Verbatim in-scope span of https://code.claude.com/docs/en/model-config.md
as published 2026-10-20 (Claude Code 2.1.300), plus the terminating heading
isolate_in_scope scans for. The extended-thinking section words the
no-disable fact as "You can't turn thinking off on Opus 5.5, Sonnet 5.5,
Haiku 5.5, or the Fable models", which the extractor's old "cannot be turned
off on" regex never read: the snapshot carried cannot_disable_on: [] from
2026-09-10 to 2026-10-20. Do not paraphrase this file — its value is that it
is exactly what the docs say. -->

### Adjust effort level

[Effort levels](https://platform.claude.com/docs/en/build-with-claude/effort) control adaptive reasoning, which lets the model decide whether and how much to think on each step based on task complexity. Lower effort is faster and cheaper for straightforward tasks, while higher effort provides deeper reasoning for complex problems.

The available effort levels depend on the model. Models not listed here do not support effort:

| Model | Levels |
| :- | :- |
| Fable 5.1 and Fable 5 | `low`, `medium`, `high`, `xhigh`, `max` |
| Opus 5.5, Sonnet 5.5, Haiku 5.5, Opus 5, Sonnet 5, Opus 4.8, and Opus 4.7 | `low`, `medium`, `high`, `xhigh`, `max` |
| Opus 4.6 and Sonnet 4.6 | `low`, `medium`, `high`, `max` |

If you set a level the active model does not support, Claude Code falls back to the highest supported level at or below the one you set. For example, `xhigh` runs as `high` on Opus 4.6. Your organization or your own settings can also cap the levels a model offers; see [Organization effort limits](#organization-effort-limits).

Claude Code resolves the session's effort level in this order, taking the first that applies:

1. An explicit choice: the [`CLAUDE_CODE_EFFORT_LEVEL`](/docs/en/env-vars#variables) environment variable, launching with `--effort`, or `/effort` in the session ([a non-interactive `/effort` has narrower effect](#non-interactive-effort))
2. Your settings: the level you saved for the model or an [`effortLevel`](/docs/en/settings-reference#effortlevel) key, with the precedence between them and across settings files stated at [`modelSettings`](/docs/en/settings-reference#modelsettings)
3. The model's default effort: `high` on every model that supports effort, except that Opus 5.5, Sonnet 5.5, and Haiku 5.5 default to `medium`, Opus 4.7 defaults to `xhigh`, and, when your organization sets a default effort level for its [organization default model](#organization-default-model), that level is the default when you run that model

After an automatic model fallback, see [Effort level after a fallback](#effort-level-after-a-fallback) for the level that applies.

Opus 5.5 starts at `medium` unless one of the sources above sets a level for it, and a top-level `effortLevel` in your user settings file doesn't count for Opus 5.5. That key is the older form `/effort` wrote before Claude Code saved levels per model: it keeps applying where it applied before, on Opus 5, Fable 5.1, and earlier models, while Opus 5.5 and models released after it start at their own default until you choose a level for them with `/effort` or the `/model` picker. A top-level `effortLevel` in project, local, or managed settings, or one passed with `--settings`, applies to every model.

When you set `low`, `medium`, `high`, or `xhigh` in an interactive session on your machine, you choose how long it lasts by how you confirm it:

* `Enter` in the `/effort` slider or the `/model` picker, or a level typed after `/effort`: save the level as your default and apply it in later sessions
* `s` in the `/effort` slider or the `/model` picker: apply the level to this session only. Requires Claude Code v2.1.257 or later

Claude Code saves the level per model, under the [`modelSettings`](/docs/en/settings-reference#modelsettings) key in your user settings, so each model keeps its own saved level.

`max` is the deepest reasoning level. Unless you set it through the `CLAUDE_CODE_EFFORT_LEVEL` environment variable, Claude Code applies `max` to the current session only.

> [!NOTE]
>
> A level you pick from the effort control on a phone or browser connected through [Remote Control](/docs/en/remote-control#what-connected-devices-see) applies to that session only.

When you set a level with `/effort` in a [`-p` run](/docs/en/headless), Claude Code applies it to that session only and doesn't save it as your default.

The `/effort` slider also has an **Ultracode** toggle. Ultracode is a Claude Code setting rather than a model effort level: with it on, Claude orchestrates [dynamic workflows](/docs/en/workflows) for substantive tasks, at whichever effort level the session runs at. For where it can be set persistently, see the [`ultracode`](/docs/en/settings-reference#ultracode) setting.

Turning ultracode on or off with `/effort` or the `ultracode` setting leaves the effort level unchanged. The `--effort ultracode` flag and the Agent SDK `effortLevel: "ultracode"` value turn it on and also set the level to `xhigh`. Picking a level in the `/effort` slider or the `/model` picker leaves ultracode as it was.

You can turn on ultracode through any of the following:

* **`/effort`**: run `/effort ultracode` to turn it on for the current session or `/effort ultracode off` to turn it off. In the `/effort` slider, press `Tab` to flip the **Ultracode** toggle, then `Enter` to apply it
* **`--effort` flag**: launch with `claude --effort ultracode`, which starts the session at `xhigh` effort with ultracode on
* **`ultracode` setting**: set [`"ultracode": true`](/docs/en/settings-reference#ultracode) in a settings file, with `--settings`, or in an Agent SDK control request. An [`applyFlagSettings()`](/docs/en/agent-sdk/typescript#applyflagsettings) request also accepts `effortLevel: "ultracode"`, which turns it on and sets the effort level to `xhigh`

The `/effort ultracode off` form, the slider toggle, and keeping ultracode on at effort levels other than `xhigh` require Claude Code v2.1.284 or later. Before v2.1.284, turning on ultracode set the session to `xhigh` effort, picking another level turned it off, and an effort cap below `xhigh` made it unavailable.

Passing `ultracode` to the `--effort` flag or the Agent SDK `effortLevel` value requires Claude Code v2.1.203 or later. Before v2.1.203, `--effort ultracode` printed `Unknown --effort value 'ultracode'` and the session started at the default effort.

The persisted `effortLevel` setting and the `CLAUDE_CODE_EFFORT_LEVEL` environment variable don't accept `ultracode`. If `CLAUDE_CODE_EFFORT_LEVEL` or an [effort cap](#organization-effort-limits) sets the session's level, ultracode stays on at that level.

Ultracode is unavailable when:

* [Workflows are turned off](/docs/en/workflows#turn-workflows-off)
* The model doesn't support `xhigh` effort

In those cases `--effort ultracode` starts the session with ultracode off, at the highest effort level the model and any cap allow, up to `xhigh`.

#### Choose an effort level

Each level trades token spend against capability. The default suits most coding tasks; adjust when you want a different balance.

| Level | When to use it |
| :- | :- |
| `low` | Quick exchanges where you review each result, such as brainstorming, a first sketch, or a small change like a rename |
| `medium` | The default on Opus 5.5, Sonnet 5.5, and Haiku 5.5. On Opus 5.5 and Sonnet 5.5, it fits day-to-day engineering work with a clear scope, such as implementing a new feature. On models with a higher default, reduces token usage for cost-sensitive work that can trade off some intelligence |
| `high` | Work where verification matters or edge cases are likely, such as fixing a bug in an existing codebase. The default on every model except Opus 5.5, Sonnet 5.5, Haiku 5.5, and Opus 4.7 |
| `xhigh` | Deeper reasoning at higher token spend. The default on Opus 4.7 |
| `max` | Hard problems you want Claude to work through without you, such as finding security vulnerabilities. `max` may show diminishing returns and is prone to overthinking, so test before adopting it broadly |
| `ultracode` | A Claude Code setting rather than a level: plans a [dynamic workflow](/docs/en/workflows) for each substantive task at any effort level |

In tests on Opus 5.5 and Fable 5.1, Claude at a higher level tested more edge cases and verified more of its work before answering. It also made more choices on its own. At a lower level, Claude returned a starting point sooner, which fits work where you review each result and steer the next step. To see the same tasks run at each level, read [Using Claude Code: Spending your effort](https://claude.dev/blog/spending-your-effort/) on the blog.

The effort scale is calibrated per model, so the same level name does not represent the same underlying value across models.

Opus 5.5 [defaults to `medium`](#adjust-effort-level), one level below Opus 5's default of `high`. In Anthropic's testing, Opus 5.5 at `medium` matches or exceeds Opus 5 at `high` on coding and knowledge-work evaluations. At a given level, Opus 5.5 tends to think more per turn than Opus 5. When you move from Opus 5 to Opus 5.5, start at `medium` rather than carrying over the level you used on Opus 5. To test levels against your own work, see [Calibrate effort](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5#calibrate-effort) in the Opus 5.5 prompting guide.

#### Use ultrathink for one-off deep reasoning

Include `ultrathink` anywhere in your prompt to request deeper reasoning on that turn without changing your session effort setting. Claude Code recognizes the keyword and adds an in-context instruction. The effort level sent to the API is unchanged. Claude Code passes other phrases such as "think", "think hard", and "think more" through as ordinary prompt text and doesn't recognize them as keywords.

#### Set the effort level

You can change effort through any of the following:

* **`/effort`**: run `/effort` with no arguments to open an interactive slider, `/effort` followed by a level name to set it directly, or `/effort auto` to clear your saved level for the active model. You can run it while Claude is working, and once you confirm the [cache warning](/docs/en/prompt-caching#changing-effort-level), if Claude Code shows one, Claude Code applies the new level to the next request in the turn
* **In `/model`**: use left/right arrow keys to adjust the effort slider when selecting a model
* **`--effort` flag**: pass a level name to set it for a single session when launching Claude Code
* **Environment variable**: set `CLAUDE_CODE_EFFORT_LEVEL` to a level name or `auto`
* **Settings**: set a per-model level in [`modelSettings`](/docs/en/settings-reference#modelsettings), or set [`effortLevel`](/docs/en/settings-reference#effortlevel) to `low`, `medium`, `high`, or `xhigh` as the default for models without one. `max` isn't accepted as a level in either key, and `ultracode` has its own [`ultracode`](/docs/en/settings-reference#ultracode) key
* **From a connected device**: in a [Remote Control](/docs/en/remote-control#what-connected-devices-see) session, pick a level from the effort control on your phone or in your browser. The level applies to the current session only. Requires Claude Code v2.1.234 or later
* **Skill and subagent frontmatter**: set `effort` in a [skill](/docs/en/skills#frontmatter-reference) or [subagent](/docs/en/sub-agents#supported-frontmatter-fields) markdown file to override the effort level when that skill or subagent runs

Frontmatter effort applies when that skill or subagent is active, overriding the session level but not the environment variable. A [`maxEffortLevel`](/docs/en/settings-reference#maxeffortlevel) or [organization effort cap](#organization-effort-limits) still limits the level the skill or subagent runs at.

If you set `effortLevel` in [managed settings](/docs/en/managed-settings), Claude Code applies it at the settings step of the [effort resolution order](#adjust-effort-level), and users can still change the level with `/effort` or `--effort`. To keep users at or below a level, set [`maxEffortLevel`](/docs/en/settings-reference#maxeffortlevel).

The effort slider appears in `/model` when a supported model is selected. The current effort level is also shown in the session header next to the model name, for example "with low effort", so you can confirm which setting is active without opening `/model`. The footer also briefly shows the effort level at startup and when it changes.

#### Adaptive reasoning and fixed thinking budgets

Adaptive reasoning makes thinking optional on each step, so Claude can respond faster to routine prompts and reserve deeper thinking for steps that benefit from it. If you want Claude to think more or less often than the current level produces, you can say so directly in your prompt or in `CLAUDE.md`; the model responds to that guidance within its effort setting.

Fable models, Sonnet 5 and later, Haiku 5.5, and Opus 4.7 and later always use adaptive reasoning. The fixed thinking budget mode and `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` don't apply to them.

On Opus 4.6 and Sonnet 4.6, you can set `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` to revert to the previous fixed thinking budget controlled by `MAX_THINKING_TOKENS`. See [environment variables](/docs/en/env-vars).

### Extended thinking

Extended thinking is the reasoning Claude emits before responding. On models that support [adaptive reasoning](#adjust-effort-level), the effort level is the primary control for how much thinking happens; the settings below turn thinking on or off and control how it displays. With thinking turned off on the Anthropic API, Claude Code sends effort `high` instead of a higher level to models it knows [don't accept that combination](/docs/en/errors#effort-isnt-available-with-thinking-turned-off), such as Opus 5.

| Control | How to set it |
| :- | :- |
| Toggle for the current session | Press `Option+T` on macOS or `Alt+T` on Windows and Linux |
| Set the global default | Run `/config` and toggle thinking mode. Saved as `alwaysThinkingEnabled` in `~/.claude/settings.json` |
| Disable through an environment variable | Set [`MAX_THINKING_TOKENS=0`](/docs/en/env-vars), which turns thinking off on the Anthropic API except on Opus 5.5, Sonnet 5.5, Haiku 5.5, and Fable models. On [third-party providers](/docs/en/third-party-integrations), Claude Code omits the `thinking` parameter instead, and adaptive-reasoning models may still think |

You can't turn thinking off on Opus 5.5, Sonnet 5.5, Haiku 5.5, or the Fable models. The session toggle and the `/config` row show `Thinking can't be turned off` for these models instead of offering the switch, and a saved `alwaysThinkingEnabled: false` or `MAX_THINKING_TOKENS=0` has no effect there. On these models, the model decides per step how much to think based on the effort level. The saved setting applies again when you switch to a model that accepts it.

Claude Code collapses thinking output by default. Press `Ctrl+O` to toggle verbose mode and see the reasoning as gray italic text. Interactive sessions on the Anthropic API receive redacted thinking blocks by default, so set `showThinkingSummaries: true` in [settings](/docs/en/settings) if you want the full summaries available when you expand. You are charged for all thinking tokens generated, even when collapsed or redacted.

### Extended context
