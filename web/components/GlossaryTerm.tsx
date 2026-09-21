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
const TOOLTIP_CLASS =
  "hidden absolute top-full z-20 mt-1 w-64 rounded-md border border-brand-slate-200 bg-white p-2 text-xs font-normal leading-snug text-brand-slate-700 shadow-lg group-hover:block group-focus:block dark:border-brand-slate-600 dark:bg-brand-slate-800 dark:text-brand-slate-200";

export function GlossaryTerm({ definition, url, align = "left", children }: GlossaryTermProps) {
  const tooltip = (
    <span
      role="tooltip"
      className={`${TOOLTIP_CLASS} ${align === "right" ? "right-0 text-right" : "left-0"}`}
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
