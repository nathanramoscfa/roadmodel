// web/app/roadmap/page.tsx
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { RoadmapWorkspace } from "@/components/RoadmapWorkspace";
import { getServerSession } from "@/lib/auth";
import { env } from "@/lib/env";
import { resolveRoadmapEngine } from "@/lib/model-routing";
import { getProfile } from "@/lib/profile";

export const metadata: Metadata = {
  title: "roadmap — Roadmap builder",
  description:
    "Describe your project and get a structured, phased roadmap — " +
    "executive summary, milestones, and acceptance criteria aligned " +
    "to your constraints.",
};

export default async function RoadmapPage() {
  // Recommender-only mode (issue #171): the roadmap builder is off.
  if (!env.ROADMAP_ENABLED) {
    redirect("/recommend");
  }
  const session = await getServerSession();
  // Step 6 — resolve the catalog-tracked engine server-side so
  // the PreviewPanel can render the free-tier label with the
  // current engine name. Anonymous traffic skips this (the
  // engine wrapper is signed-in-only); a failed resolve falls
  // back to a null engine so the panel renders without the
  // label rather than blocking page load.
  let engine: string | null = null;
  if (session) {
    try {
      const profile = await getProfile(session.id);
      const resolved = resolveRoadmapEngine({
        profile,
        envFrontierEnabled: env.FRONTIER_ROADMAP_ENABLED,
      });
      engine = resolved.engine;
    } catch (err) {
      console.warn("[/roadmap] engine resolve failed", err);
    }
  }

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
        <RoadmapWorkspace isAnonymous={!session} engine={engine} />
      </div>
    </section>
  );
}
