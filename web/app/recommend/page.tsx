// web/app/recommend/page.tsx
import { RecommendWorkspace } from "@/components/RecommendWorkspace";

export default function RecommendPage() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-12 sm:py-16">
      <header className="max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 sm:text-4xl">
          Get a model recommendation
        </h1>
        <p className="mt-3 text-brand-slate-600">
          Describe your task and we will suggest a model, platform, settings,
          and cost context.
        </p>
      </header>

      <div className="mt-10 grid grid-cols-1 gap-10 lg:grid-cols-2 lg:gap-12">
        <RecommendWorkspace />
      </div>
    </section>
  );
}
