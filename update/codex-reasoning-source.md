{
      key: "model_reasoning_effort",
      type: "string",
      description:
        "Reasoning effort advertised by the selected model, such as `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`. Available levels depend on the model and client.",
    },
    {
      key: "plan_mode_reasoning_effort",
      type: "string",
      description:
        "Plan-mode-specific reasoning override using a level supported by the selected model. When unset, Plan mode uses its built-in preset default.",
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
    }
