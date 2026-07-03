// web/components/WhyDisclosure.tsx
//
// Renders the model's own reasoning ("Why this model?") as an always-visible
// card. When the service supplies structured `rationale_sections` (task / pick /
// run), they render as sub-headed segments — the /recommend redesign. When they
// are absent (an older service, or a model that ignored the labelled RATIONALE
// format), it falls back to the prior behavior: split the single `rationale`
// string into readable, sentence-level lines (#270) with glossary popovers.
import { Fragment, type ReactNode } from "react";

import { segmentRationale } from "@/lib/glossary";

import { GlossaryTerm } from "./GlossaryTerm";

interface WhyDisclosureProps {
  rationale: string | null;
  // Structured sections keyed by "task" / "pick" / "run" (best-effort from the
  // service). Rendered as sub-headings when any is present.
  sections?: Record<string, string> | null;
}

// The three sub-heads, in display order, mapped from the service's section keys.
const SECTIONS: { key: string; label: string }[] = [
  { key: "task", label: "The task" },
  { key: "pick", label: "Why this pick" },
  { key: "run", label: "How to run it" },
];

function sectionText(
  sections: Record<string, string> | null | undefined,
  key: string,
): string | null {
  const value = sections?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function hasSections(sections?: Record<string, string> | null): boolean {
  return SECTIONS.some(({ key }) => sectionText(sections, key) !== null);
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

export function WhyDisclosure({ rationale, sections }: WhyDisclosureProps) {
  const structured = hasSections(sections);
  if (!structured && !rationale?.trim()) {
    return null;
  }

  return (
    <section
      aria-label="Why this model?"
      className="rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-50 dark:bg-brand-slate-900 p-4"
    >
      <h3 className="text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        Why this model?
      </h3>

      {structured ? (
        // Sub-headed sections: an accent label + the segment, each with a left
        // rail so the three read as distinct steps (The task / Why this pick /
        // How to run it).
        <div className="mt-3 space-y-3">
          {SECTIONS.map(({ key, label }) => {
            const text = sectionText(sections, key);
            if (!text) {
              return null;
            }
            return (
              <div
                key={key}
                className="border-l-2 border-brand-slate-200 dark:border-brand-slate-700 pl-3"
              >
                <h4 className="text-xs font-semibold uppercase tracking-wide text-brand-accent">
                  {label}
                </h4>
                <p className="mt-0.5 text-sm leading-relaxed text-brand-slate-700 dark:text-brand-slate-200">
                  {renderSegments(text)}
                </p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-2 space-y-2 text-sm leading-relaxed text-brand-slate-700 dark:text-brand-slate-200">
          {toLines(rationale ?? "").map((line, index) => (
            <p key={index}>{renderSegments(line)}</p>
          ))}
        </div>
      )}
    </section>
  );
}
