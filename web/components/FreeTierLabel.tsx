// web/components/FreeTierLabel.tsx
//
// Engine-tier label rendered on /roadmap (Phase 4 Step 6). The engine-name
// portion is derived server-side from the catalog-tracked resolver so the
// label automatically follows the engine when the Phase 9 §9.2 cron flips it.
// /recommend names its engine itself (RecommendResult's engine line), from
// the engine registry.

import Link from "next/link";

export type FreeTierSurface = "roadmap";

// engine string → display copy. Centralized here so a future
// engine swap is a one-line edit; the resolver returns the model
// id and this map renders its public-facing copy. Unknown
// engines fall back to a neutral label.
const ENGINE_DISPLAY: Record<string, string> = {
  "gemini-2.5-flash": "Gemini 2.5 Flash",
  "gemini-3-flash": "Gemini 3 Flash",
  // Prior signed-in quality-tier engine (kept for historical audit rows).
  "gemini-2.5-pro": "Gemini 2.5 Pro",
  // Signed-in quality-tier engine + anon canary (2026-07-19 eval-backed cutover).
  "gpt-5-mini": "GPT-5 mini",
};

function engineDisplayName(engine: string | undefined): string | null {
  if (!engine) {
    return null;
  }
  return ENGINE_DISPLAY[engine] ?? null;
}

interface FreeTierLabelProps {
  // Phase 3 callers may still pass a fully-formed `label` string; the
  // /roadmap surface passes surface + engine.
  label?: string;
  surface?: FreeTierSurface;
  engine?: string;
}

function freeTierCopy(engine: string | undefined): string {
  const display = engineDisplayName(engine);
  return display
    ? `Free tier (${display}) — upgrade for frontier models`
    : "Free tier — upgrade for frontier models";
}

export function FreeTierLabel(props: FreeTierLabelProps) {
  const { label, engine } = props;

  // Phase-3 callers pass a fully-formed label string (kept as a /pricing link).
  if (label) {
    return (
      <p className="text-sm">
        <Link
          href="/pricing"
          className="font-medium text-brand-accent underline-offset-2 hover:underline"
        >
          {label}
        </Link>
      </p>
    );
  }

  // /roadmap (+ fallback): unchanged free-tier upgrade copy.
  return (
    <p className="text-sm">
      <Link
        href="/pricing"
        className="font-medium text-brand-accent underline-offset-2 hover:underline"
      >
        {freeTierCopy(engine)}
      </Link>
    </p>
  );
}
