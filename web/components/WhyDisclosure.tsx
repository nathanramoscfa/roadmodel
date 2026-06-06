// web/components/WhyDisclosure.tsx
//
// Renders the model's own reasoning ("Why this model?") as an always-visible
// card. Previously a collapsed <details> that hid the rationale behind a click —
// but the rationale is the core value of a recommendation (the #173 work made it
// non-empty), so it is surfaced prominently rather than disclosed.

interface WhyDisclosureProps {
  rationale: string | null;
}

export function WhyDisclosure({ rationale }: WhyDisclosureProps) {
  if (!rationale?.trim()) {
    return null;
  }

  return (
    <section
      aria-label="Why this model?"
      className="rounded-lg border border-brand-slate-200 bg-brand-slate-50 p-4"
    >
      <h3 className="text-sm font-semibold text-brand-slate-800">
        Why this model?
      </h3>
      <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-brand-slate-700">
        {rationale}
      </p>
    </section>
  );
}
