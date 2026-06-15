// web/components/WhyDisclosure.tsx
//
// Renders the model's own reasoning ("Why this model?") as an always-visible
// card. Previously a collapsed <details> that hid the rationale behind a click —
// but the rationale is the core value of a recommendation (the #173 work made it
// non-empty), so it is surfaced prominently rather than disclosed.
import { Fragment } from "react";

import { segmentRationale } from "@/lib/glossary";

import { GlossaryTerm } from "./GlossaryTerm";

interface WhyDisclosureProps {
  rationale: string | null;
}

// Break the rationale into readable lines so it doesn't render as one dense
// block (#270). Honor any explicit newlines first, then split each paragraph on
// sentence boundaries — punctuation followed by whitespace + a capital/quote.
// The lookbehind/lookahead avoids splitting decimals ("62.9") or "(#2)." mid-
// number, so benchmark figures stay intact.
function toLines(rationale: string): string[] {
  const lines = rationale
    .trim()
    .split(/\n+/)
    .flatMap((para) => para.split(/(?<=[.!?])\s+(?=[A-Z"'(])/))
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.length > 0 ? lines : [rationale.trim()];
}

export function WhyDisclosure({ rationale }: WhyDisclosureProps) {
  if (!rationale?.trim()) {
    return null;
  }

  const lines = toLines(rationale);

  return (
    <section
      aria-label="Why this model?"
      className="rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-50 dark:bg-brand-slate-900 p-4"
    >
      <h3 className="text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        Why this model?
      </h3>
      <div className="mt-2 space-y-2 text-sm leading-relaxed text-brand-slate-700 dark:text-brand-slate-200">
        {lines.map((line, index) => (
          <p key={index}>
            {segmentRationale(line).map((segment, segmentIndex) =>
              segment.term && segment.definition ? (
                <GlossaryTerm
                  key={segmentIndex}
                  definition={segment.definition}
                  url={segment.url}
                >
                  {segment.text}
                </GlossaryTerm>
              ) : (
                <Fragment key={segmentIndex}>{segment.text}</Fragment>
              ),
            )}
          </p>
        ))}
      </div>
    </section>
  );
}
