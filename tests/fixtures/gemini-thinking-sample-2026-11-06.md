## Controlling thinking  {% id="thinking-levels" %}

Gemini models engage in dynamic thinking by default, automatically adjusting
the amount of reasoning effort based on the complexity of the request. You can
control this behavior using the `thinking_level` parameter.

| Model | Default Thinking | Levels Supported |
| --- | --- | --- |
| gemini-4-argon | On (medium) | low, medium, high |
| gemini-3.8-flash | On (medium) | low, medium, high |
| gemini-3.6-flash | On (medium) | minimal, low, medium, high |
| gemini-3.5-flash-lite | On (minimal) | minimal, low, medium, high |
| gemini-3.1-pro-preview | On (high) | low, medium, high |
| gemini-3.1-flash-lite-image | On (minimal) | minimal, high |
| gemini-3-flash-preview | On (high) | minimal, low, medium, high |
| gemini-3-pro-preview | On (high) | low, high |
| gemini-2.5-pro | On | low, medium, high |
| gemini-2.5-flash | On | low, medium, high |
| gemini-2.5-flash-lite | Off | low, medium, high |
| gemini-robotics-er-2-preview | On (high) | minimal, low, medium, high |

