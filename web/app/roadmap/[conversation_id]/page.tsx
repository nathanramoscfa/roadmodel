// web/app/roadmap/[conversation_id]/page.tsx
//
// Phase 4 Step 5 — re-hydrate a past roadmap conversation. Server
// component loads the conversation + messages + roadmap snapshot
// inside the user's session, then hands them to RoadmapWorkspace
// as initial props so the chat + preview render immediately
// without a round-trip to /api/roadmap. RLS on the underlying
// tables makes notFound() the right shape for both missing rows
// and cross-user reads — the supabase query returns null in
// either case.

import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { RoadmapWorkspace } from "@/components/RoadmapWorkspace";
import { getServerSession } from "@/lib/auth";
import { getConversationDetail } from "@/lib/conversations";
import { env } from "@/lib/env";
import { resolveRoadmapEngine } from "@/lib/model-routing";
import { getProfile } from "@/lib/profile";

interface PageProps {
  params: Promise<{ conversation_id: string }>;
}

export const metadata: Metadata = {
  title: "Roadmap — roadmodel",
  description: "Continue a past roadmap conversation on roadmodel.",
};

export default async function HydratedRoadmapPage({ params }: PageProps) {
  const session = await getServerSession();
  const { conversation_id } = await params;
  if (!session) {
    redirect(`/login?next=/roadmap/${conversation_id}`);
  }

  const detail = await getConversationDetail(conversation_id, session.id);
  if (!detail) {
    notFound();
  }

  let engine: string | null = null;
  try {
    const profile = await getProfile(session.id);
    const resolved = resolveRoadmapEngine({
      profile,
      envFrontierEnabled: env.FRONTIER_ROADMAP_ENABLED,
    });
    engine = resolved.engine;
  } catch (err) {
    console.warn("[/roadmap/:id] engine resolve failed", err);
  }

  return (
    <section className="mx-auto max-w-6xl px-6 py-12 sm:py-16">
      <header className="max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 sm:text-4xl">
          {detail.title}
        </h1>
        <p className="mt-3 text-brand-slate-600">
          Continue the conversation, or download the latest roadmap.
        </p>
      </header>

      <div className="mt-10">
        <RoadmapWorkspace
          isAnonymous={false}
          initialMessages={detail.messages}
          initialDraft={detail.draft}
          initialConversationId={detail.id}
          initialRoadmapId={detail.roadmap_id}
          engine={engine}
        />
      </div>
    </section>
  );
}
