// web/components/Hero.tsx
import Link from "next/link";
import { TryItNowTextarea } from "./TryItNowTextarea";

export function Hero() {
  return (
    <section className="mx-auto max-w-4xl px-6 py-20 text-center sm:py-28">
      <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
        roadmodel
      </p>
      <h1 className="mt-4 text-4xl font-bold tracking-tight text-brand-slate-900 sm:text-5xl">
        Pick the right model for the right job
      </h1>
      <p className="mx-auto mt-6 max-w-2xl text-lg text-brand-slate-600">
        Point roadmodel at a task description and get a grounded recommendation
        for which AI model, which platform, and which settings to use — with
        cost context from live benchmarks and pricing catalogs.
      </p>
      <Link
        href="/recommend"
        className="mt-8 inline-flex items-center rounded-lg bg-brand-accent px-6 py-3 text-base font-semibold text-white shadow-sm transition hover:bg-brand-accent-hover"
      >
        Try it free →
      </Link>
      <TryItNowTextarea />
    </section>
  );
}
