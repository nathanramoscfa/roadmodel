// web/components/GlossaryTerm.tsx
//
// Inline "definable term" with a CSS-only popover (#269). The definition shows
// on hover AND on keyboard focus (focus also fires on tap, so touch is covered)
// via group-hover / group-focus — no client JS. The definition lives in the DOM
// (hidden until revealed) so assistive tech can reach it after the term.
import type { ReactNode } from "react";

interface GlossaryTermProps {
  definition: string;
  children: ReactNode;
}

export function GlossaryTerm({ definition, children }: GlossaryTermProps) {
  return (
    <span
      tabIndex={0}
      className="group relative inline-block cursor-help border-b border-dotted border-brand-slate-400 outline-none dark:border-brand-slate-500"
    >
      {children}
      <span
        role="tooltip"
        className="invisible absolute left-0 top-full z-20 mt-1 w-64 rounded-md border border-brand-slate-200 bg-white p-2 text-xs font-normal leading-snug text-brand-slate-700 opacity-0 shadow-lg transition-opacity duration-100 group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100 dark:border-brand-slate-600 dark:bg-brand-slate-800 dark:text-brand-slate-200"
      >
        {definition}
      </span>
    </span>
  );
}
