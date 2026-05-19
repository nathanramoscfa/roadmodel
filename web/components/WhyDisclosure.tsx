// web/components/WhyDisclosure.tsx
"use client";

interface WhyDisclosureProps {
  rationale: string | null;
}

export function WhyDisclosure({ rationale }: WhyDisclosureProps) {
  if (!rationale?.trim()) {
    return null;
  }

  return (
    <details className="rounded-lg border border-brand-slate-200 bg-white">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-brand-slate-800">
        Why this model?
      </summary>
      <p className="border-t border-brand-slate-200 px-4 py-3 text-sm text-brand-slate-700">
        {rationale}
      </p>
    </details>
  );
}
