# Codex Models

<!--
Faithful slice of https://developers.openai.com/codex/models.md covering the
`## Recommended models` ModelDetails slugs plus a `## Deprecated Codex models`
section, used to test update/extract_codex_models.py offline. Deprecated slugs
must NOT be flagged. Refresh from the live docs if the parser's expectations
change.
-->

## Recommended models

<div class="not-prose grid gap-6 md:grid-cols-2 xl:grid-cols-3">
  <ModelDetails
    client:load
    name="gpt-5.5"
    slug="gpt-5.5"
    description="OpenAI's newest frontier model for complex coding."
  />

  <ModelDetails
    client:load
    name="gpt-5.4"
    slug="gpt-5.4"
    description="Flagship frontier model for professional work."
  />

  <ModelDetails
    client:load
    name="gpt-5.4-mini"
    slug="gpt-5.4-mini"
    description="Fast, efficient mini model for responsive coding tasks and subagents."
  />

  <ModelDetails
    client:load
    name="gpt-5.3-codex-spark"
    slug="gpt-5.3-codex-spark"
    description="Text-only research preview model optimized for near-instant coding iteration."
  />
</div>

For most tasks in Codex, start with `gpt-5.5`.

## Deprecated Codex models

The `gpt-5.2` and `gpt-5.3-codex` models are deprecated in Codex when you sign
in with ChatGPT.
