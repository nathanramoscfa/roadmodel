// web/components/PreviewPanel.tsx
"use client";

import type { RoadmapDraft } from "@/lib/roadmap-types";

import { FreeTierLabel } from "./FreeTierLabel";

interface PreviewPanelProps {
  draft: RoadmapDraft | null;
  // Step 6 — server-resolved engine string ("gemini-2.5-flash" /
  // "gemini-3-flash") plumbed in from the /roadmap page so the
  // FreeTierLabel can render the catalog-tracked model name.
  engine?: string | null;
}

function SkeletonState() {
  return (
    <div className="space-y-6">
      <div
        className={
          "rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-100 dark:bg-brand-slate-800/60 " +
          "px-4 py-8 text-center text-sm text-brand-slate-500 dark:text-brand-slate-400"
        }
      >
        Project overview will appear here
      </div>
      <div
        className={
          "rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-100 dark:bg-brand-slate-800/60 " +
          "px-4 py-8 text-center text-sm text-brand-slate-500 dark:text-brand-slate-400"
        }
      >
        Phases
      </div>
      <div
        className={
          "rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-100 dark:bg-brand-slate-800/60 " +
          "px-4 py-8 text-center text-sm text-brand-slate-500 dark:text-brand-slate-400"
        }
      >
        Acceptance criteria.
      </div>
    </div>
  );
}

export function PreviewPanel({ draft, engine }: PreviewPanelProps) {
  if (!draft) {
    return (
      <div
        className={
          "flex min-h-[480px] flex-1 flex-col rounded-xl border " +
          "border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-4 shadow-sm sm:p-6"
        }
      >
        <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
          Preview
        </h2>
        <div className="mt-6 flex-1">
          <SkeletonState />
        </div>
        {engine ? (
          <div className="mt-4">
            <FreeTierLabel surface="roadmap" engine={engine} />
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={
        "flex min-h-[480px] flex-1 flex-col rounded-xl border " +
        "border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-4 shadow-sm sm:p-6"
      }
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-slate-500 dark:text-brand-slate-400">
        Preview
      </h2>
      {engine ? (
        <div className="mt-2">
          <FreeTierLabel surface="roadmap" engine={engine} />
        </div>
      ) : null}
      <div className="mt-6 flex-1 space-y-6 overflow-y-auto">
        <section>
          <h3 className="text-lg font-semibold text-brand-slate-900 dark:text-brand-slate-50">
            Executive Summary
          </h3>
          <div
            className={
              "mt-3 rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 " +
              "bg-brand-slate-50 dark:bg-brand-slate-900 px-4 py-4 text-sm text-brand-slate-700 dark:text-brand-slate-200"
            }
          >
            <p className="whitespace-pre-wrap">{draft.project_overview}</p>
          </div>
        </section>

        <section>
          <h3 className="text-lg font-semibold text-brand-slate-900 dark:text-brand-slate-50">
            Phased Roadmap
          </h3>
          <ol className="mt-3 space-y-4">
            {draft.phases.map((phase) => (
              <li
                key={phase.title}
                className={
                  "rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 p-4"
                }
              >
                <h4 className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                  {phase.title}
                </h4>
                <p className="mt-1 text-sm text-brand-slate-600 dark:text-brand-slate-300">
                  <span className="font-medium">Goal:</span> {phase.goal}
                </p>
                {phase.sub_sections.length > 0 ? (
                  <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-brand-slate-700 dark:text-brand-slate-200">
                    {phase.sub_sections.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {phase.acceptance_criteria.length > 0 ? (
                  <div
                    className={
                      "mt-4 rounded-md border border-brand-accent-muted " +
                      "bg-brand-accent-muted/40 px-3 py-3"
                    }
                  >
                    <p className="text-xs font-semibold uppercase tracking-wide text-brand-accent">
                      Acceptance criteria
                    </p>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-brand-slate-700 dark:text-brand-slate-200">
                      {phase.acceptance_criteria.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        </section>

        {draft.glossary.length > 0 ? (
          <section>
            <h3 className="text-lg font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              Glossary
            </h3>
            <dl className="mt-3 space-y-2 text-sm text-brand-slate-700 dark:text-brand-slate-200">
              {draft.glossary.map((entry) => (
                <div key={entry.term}>
                  <dt className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
                    {entry.term}
                  </dt>
                  <dd>{entry.definition}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}
      </div>
    </div>
  );
}
