# Codex configuration reference

<!--
Faithful slice of https://developers.openai.com/codex/config-reference.md
covering ONLY the in-scope reasoning/verbosity config keys of the
`## config.toml` ConfigTable, used to test
update/extract_codex_reasoning.py offline. A couple of neighbouring keys are
kept (one before, one after) so the in-scope-span isolation is exercised
realistically. Refresh from the live docs if the parser's expectations change.
-->

## `config.toml`

User-level configuration lives in `~/.codex/config.toml`. The keys below are
parsed from a JSX `<ConfigTable options={[ ... ]}>` component, NOT a Markdown
table.

<ConfigTable
  options={[
    {
      key: "model_providers.amazon-bedrock.aws.region",
      type: "string",
      description: "AWS region used by the built-in `amazon-bedrock` provider.",
    },
    {
      key: "model_reasoning_effort",
      type: "minimal | low | medium | high | xhigh",
      description:
        "Adjust reasoning effort for supported models (Responses API only; `xhigh` is model-dependent).",
    },
    {
      key: "plan_mode_reasoning_effort",
      type: "none | minimal | low | medium | high | xhigh",
      description:
        "Plan-mode-specific reasoning override. When unset, Plan mode uses its built-in preset default.",
    },
    {
      key: "model_reasoning_summary",
      type: "auto | concise | detailed | none",
      description:
        "Select reasoning summary detail or disable summaries entirely.",
    },
    {
      key: "model_verbosity",
      type: "low | medium | high",
      description:
        "Optional GPT-5 Responses API verbosity override; when unset, the selected model/preset default is used.",
    },
    {
      key: "model_supports_reasoning_summaries",
      type: "boolean",
      description: "Force Codex to send or not send reasoning metadata.",
    },
  ]}
/>

### Extra context

Out-of-scope content follows here in the real page.
