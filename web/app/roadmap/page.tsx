// web/app/roadmap/page.tsx
import type { Metadata } from "next";

import { RoadmapWorkspace } from "@/components/RoadmapWorkspace";
import { getServerSession } from "@/lib/auth";

export const metadata: Metadata = {
  title: "roadmap — Roadmap builder",
  description:
    "Describe your project and get a structured, phased roadmap — " +
    "executive summary, milestones, and acceptance criteria aligned " +
    "to your constraints.",
};

export default async function RoadmapPage() {
  const session = await getServerSession();

  return (
    <section className="mx-auto max-w-6xl px-6 py-12 sm:py-16">
      <header className="max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 sm:text-4xl">
          Roadmap builder
        </h1>
        <p className="mt-3 text-brand-slate-600">
          Describe your project and we will shape a phased roadmap with
          executive summary, milestones, and testable acceptance criteria.
        </p>
      </header>

      <div className="mt-10">
        <RoadmapWorkspace isAnonymous={!session} />
      </div>
    </section>
  );
}
