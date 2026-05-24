// web/components/FreeTierLabel.tsx
//
// Free-tier label rendered on both /recommend (Phase 3) and
// /roadmap (Phase 4 Step 6). Two callers share this component
// because the upgrade CTA copy is identical; the engine-name
// portion of the label is the only thing that varies, and it's
// derived server-side from the catalog-tracked resolver so the
// label automatically follows the engine when the Phase 9 §9.2
// cron flips it.

import Link from "next/link";

export type FreeTierSurface = "recommend" | "roadmap";

// engine string → display copy. Centralized here so a future
// engine swap is a one-line edit; the resolver returns the model
// id and this map renders its public-facing copy. Unknown
// engines fall back to a neutral "free tier" label — the
// resolver's NoEligibleEngineError should fire long before any
// id we don't recognize reaches the UI, but the fallback exists
// so a stale browser tab doesn't render undefined.
const ENGINE_DISPLAY: Record<string, string> = {
  "gemini-2.5-flash": "Gemini 2.5 Flash",
  "gemini-3-flash": "Gemini 3 Flash",
};

function engineDisplayName(engine: string | undefined): string | null {
  if (!engine) {
    return null;
  }
  return ENGINE_DISPLAY[engine] ?? null;
}

interface FreeTierLabelProps {
  // Phase 3 callers still pass a fully-formed `label` string; the
  // /recommend surface keeps that shape for backward compatibility.
  // /roadmap callers pass surface + engine instead and let the
  // component format the copy from the engine-display map.
  label?: string;
  surface?: FreeTierSurface;
  engine?: string;
}

function formatRoadmapLabel(engine: string | undefined): string {
  const display = engineDisplayName(engine);
  if (display) {
    return `Free tier (${display}) — upgrade for frontier models`;
  }
  return "Free tier — upgrade for frontier models";
}

export function FreeTierLabel({
  label,
  surface,
  engine,
}: FreeTierLabelProps) {
  const text =
    label ??
    (surface === "roadmap" ? formatRoadmapLabel(engine) : "Free tier");
  return (
    <p className="text-sm">
      <Link
        href="/pricing"
        className="font-medium text-brand-accent underline-offset-2 hover:underline"
      >
        {text}
      </Link>
    </p>
  );
}
