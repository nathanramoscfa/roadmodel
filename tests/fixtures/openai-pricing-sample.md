<!--
Faithful slice of https://developers.openai.com/api/docs/pricing.md — the JS/JSX
pricing arrays, used to test update/extract_openai_catalog.py offline. Includes
the STANDARD pane and a BATCH pane (same model names at half price) to prove the
parser scopes to data-value="standard" and ignores the discounted panes; plus a
-pro row and gpt-5.1 (not in the selector's map) to prove they're skipped.
Refresh from the live docs if the parser's expectations change.
-->
<small className="pricing-switcher-meta">Prices per 1M tokens.</small>

<div data-content-switcher-pane data-value="standard">
  <div class="hidden">Standard</div>
  <TextTokenPricingTables
    client:load
    tier="standard"
    rows={[
      ["gpt-5.5 (<272K context length)", 5, 0.5, 30],
      ["gpt-5.5-pro (<272K context length)", 30, "", 180],
      ["gpt-5.4 (<272K context length)", 2.5, 0.25, 15],
      ["gpt-5.4-mini", 0.75, 0.075, 4.5],
      ["gpt-5.4-nano", 0.2, 0.02, 1.25],
      ["gpt-5.2", 1.75, 0.175, 14],
      ["gpt-5.1", 1.25, 0.125, 10],
      ["gpt-5", 1.25, 0.125, 10],
      ["gpt-5-mini", 0.25, 0.025, 2],
    ]}
  />
</div>

<div data-content-switcher-pane data-value="batch" hidden>
  <div class="hidden">Batch</div>
  <TextTokenPricingTables
    client:load
    tier="batch"
    rows={[
      ["gpt-5.5 (<272K context length)", 2.5, 0.25, 15],
      ["gpt-5.4 (<272K context length)", 1.25, 0.13, 7.5],
      ["gpt-5-mini", 0.125, 0.0125, 1],
    ]}
  />
</div>
