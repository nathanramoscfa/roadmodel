// web/components/GlossaryTerm.tsx
//
// Inline "definable term" with a CSS-only popover (#269). The definition shows
// on hover AND on keyboard focus (focus also fires on tap, so touch is covered)
// via group-hover / group-focus — no client JS. The definition lives in the DOM
// (display:none until revealed, so a hidden popover never widens an
// overflow-x container — `invisible` still occupies layout, and the /models
// table wrapper grew a horizontal scrollbar from tooltips it wasn't showing).
import type { ReactNode } from "react";

interface GlossaryTermProps {
  definition: string;
  // Canonical source. When set, the term is a link (hover/focus still reveals the
  // definition; click opens the source). When absent, it stays a definable span.
  url?: string;
  // Which edge the popover hangs from. "right" for terms near the right edge of
  // a scroll container, where a left-anchored 16rem popover would be clipped.
  align?: "left" | "right";
  children: ReactNode;
}

const BASE_CLASS =
  "group relative inline-block border-b border-dotted border-brand-slate-400 outline-none dark:border-brand-slate-500";
// `whitespace-normal` + `break-words` + `normal-case tracking-normal` are
// load-bearing: a term inside a table header inherits that header's
// `whitespace-nowrap` / `uppercase tracking-wide`, which ran the definition
// off the right edge of the box in one unbroken line.
const TOOLTIP_CLASS =
  "hidden absolute top-full z-20 mt-1 w-72 whitespace-normal break-words rounded-md border border-brand-slate-200 bg-white p-2 text-left text-xs font-normal normal-case leading-snug tracking-normal text-brand-slate-700 shadow-lg group-hover:block group-focus:block dark:border-brand-slate-600 dark:bg-brand-slate-800 dark:text-brand-slate-200";

export function GlossaryTerm({ definition, url, align = "left", children }: GlossaryTermProps) {
  const tooltip = (
    <span
      role="tooltip"
      className={`${TOOLTIP_CLASS} ${align === "right" ? "right-0" : "left-0"}`}
    >
      {definition}
      {url ? (
        <span className="mt-1 block font-medium text-brand-accent">View source ↗</span>
      ) : null}
    </span>
  );

  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className={`${BASE_CLASS} cursor-pointer hover:border-brand-accent`}
      >
        {children}
        {tooltip}
      </a>
    );
  }

  return (
    <span tabIndex={0} className={`${BASE_CLASS} cursor-help`}>
      {children}
      {tooltip}
    </span>
  );
}
