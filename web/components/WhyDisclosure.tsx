// web/components/WhyDisclosure.tsx
//
// A pick's reasoning ("Why Opus 5.5?"), always visible. The answer's labelled
// sections render as sub-headed segments: the AI recommender's The task / Why
// this pick / Why this effort, or Quick pick's Strength / Fit to the task /
// Cost (lib/ladder-view.ts names them). An answer with no sections (an older
// service, or an engine that ignored the labelled format) falls back to its
// single rationale string, split into readable sentence-level lines (#270).
// Either way a glossary term or a benchmark name in the text opens its
// definition.
import { Fragment, type ReactNode } from "react";

import { segmentRationale } from "@/lib/glossary";
import type { WhySection } from "@/lib/ladder-view";

import { GlossaryTerm } from "./GlossaryTerm";

interface WhyDisclosureProps {
  rationale: string | null;
  // The labelled sections, in display order; empty when the answer has none.
  sections?: readonly WhySection[];
  // The picked model's display name, shown in the heading ("Why Opus 5.5?").
  // The section's aria-label stays "Why this model?" so it is a stable
  // landmark whatever the pick.
  model?: string | null;
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
    .filter(Boolean)
    // roadmodel answers what to run and with which settings, not how to
    // invoke it: a labelled "RUN: …" sentence is left out. Only the explicit
    // label form, so ordinary prose that starts with "Run" is kept.
    .filter((line) => !/^run:/i.test(line));
  return lines.length > 0 ? lines : [rationale.trim()];
}

// Render one line/segment with inline glossary popovers + benchmark links.
function renderSegments(text: string): ReactNode {
  return segmentRationale(text).map((segment, index) =>
    segment.term && segment.definition ? (
      <GlossaryTerm key={index} definition={segment.definition} url={segment.url}>
        {segment.text}
      </GlossaryTerm>
    ) : (
      <Fragment key={index}>{segment.text}</Fragment>
    ),
  );
}

export function WhyDisclosure({ rationale, sections = [], model }: WhyDisclosureProps) {
  const structured = sections.length > 0;
  if (!structured && !rationale?.trim()) {
    return null;
  }
  const heading = model?.trim() ? `Why ${model.trim()}?` : "Why this model?";

  return (
    // No chrome of its own: the panel that holds it owns the border and
    // background, so the reasoning and the cost read as one card.
    <section aria-label="Why this model?" data-testid="why">
      <h3 className="text-base font-semibold text-brand-slate-900 dark:text-brand-slate-50">{heading}</h3>

      {structured ? (
        // An accent label over each segment, with a left rail so they read as
        // distinct steps.
        <div className="mt-3 space-y-3">
          {sections.map(({ key, label, text }) => (
            <div key={key} className="border-l-2 border-brand-accent/40 pl-3.5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-brand-accent">{label}</h4>
              <p className="mt-1 text-sm leading-6 text-brand-slate-700 dark:text-brand-slate-200">
                {renderSegments(text)}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-3 space-y-2 text-sm leading-6 text-brand-slate-700 dark:text-brand-slate-200">
          {toLines(rationale ?? "").map((line, index) => (
            <p key={index}>{renderSegments(line)}</p>
          ))}
        </div>
      )}
    </section>
  );
}
