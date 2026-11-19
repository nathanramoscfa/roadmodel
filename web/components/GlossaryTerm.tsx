// web/components/GlossaryTerm.tsx
//
// Inline "definable term" with a portaled hover/focus/tap popover (#269).
// Uses FloatingCard + useHoverPopup so definitions inside scrolled table
// containers (column header info icons, Jurisdiction badges) and rationale prose
// render in document.body without scroll-box clipping, stay open when moving
// into the popup (including to tap "View source ↗"), and get a touch-only
// close button when tapped on phones/tablets.
"use client";

import type { ReactNode, RefObject } from "react";

import { FloatingCard, useHoverPopup } from "./FloatingCard";

interface GlossaryTermProps {
  definition: string;
  // Canonical source. When set, the term is a link (hover/focus reveals the
  // definition; mouse click opens the source, touch tap opens the popup with
  // the source link inside). When absent, it stays a definable span.
  url?: string;
  // Retained for caller compatibility; FloatingCard positions against the viewport.
  align?: "left" | "right";
  children: ReactNode;
}

const BASE_CLASS =
  "inline-block border-b border-dotted border-brand-slate-400 outline-none focus-visible:ring-2 focus-visible:ring-brand-accent dark:border-brand-slate-500";

export function GlossaryTerm({ definition, url, children }: GlossaryTermProps) {
  const { open, cardProps, triggerProps } = useHoverPopup<HTMLElement>();

  const card = (
    <div className="w-72 max-w-full text-xs leading-snug">
      <p>{definition}</p>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-block font-medium text-brand-accent hover:underline"
        >
          View source ↗
        </a>
      ) : null}
    </div>
  );

  return (
    <>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          ref={triggerProps.ref as RefObject<HTMLAnchorElement | null>}
          aria-describedby={triggerProps["aria-describedby"]}
          onPointerEnter={triggerProps.onPointerEnter}
          onPointerLeave={triggerProps.onPointerLeave}
          onPointerDown={triggerProps.onPointerDown}
          onClick={triggerProps.onClick}
          onFocus={triggerProps.onFocus}
          onBlur={triggerProps.onBlur}
          onKeyDown={triggerProps.onKeyDown}
          className={`${BASE_CLASS} cursor-pointer hover:border-brand-accent`}
        >
          {children}
        </a>
      ) : (
        <span
          tabIndex={0}
          ref={triggerProps.ref as RefObject<HTMLSpanElement | null>}
          aria-describedby={triggerProps["aria-describedby"]}
          onPointerEnter={triggerProps.onPointerEnter}
          onPointerLeave={triggerProps.onPointerLeave}
          onPointerDown={triggerProps.onPointerDown}
          onClick={triggerProps.onClick}
          onFocus={triggerProps.onFocus}
          onBlur={triggerProps.onBlur}
          onKeyDown={triggerProps.onKeyDown}
          className={`${BASE_CLASS} cursor-help`}
        >
          {children}
        </span>
      )}
      {open && (
        <FloatingCard {...cardProps} testId="glossary-card">
          {card}
        </FloatingCard>
      )}
    </>
  );
}
