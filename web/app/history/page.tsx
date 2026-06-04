// web/app/history/page.tsx
//
// Phase 4 Step 5 — signed-in user's list of past roadmap
// conversations. Server component: pulls the list with the
// session-bound supabase client so RLS enforces row ownership.
// Filtering UI (title substring + ISO date range, debounced
// 300ms) lives in the HistoryList client component because the
// search is purely client-side over the already-fetched window.

import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getServerSession } from "@/lib/auth";
import { listConversationsForUser } from "@/lib/conversations";
import { env } from "@/lib/env";
import { HistoryList } from "./HistoryList";

export const metadata: Metadata = {
  title: "History — roadmodel",
  description: "Your past roadmap conversations on roadmodel.",
};

export default async function HistoryPage() {
  // Recommender-only mode (issue #171): the roadmap builder is off.
  if (!env.ROADMAP_ENABLED) {
    redirect("/recommend");
  }
  const session = await getServerSession();
  if (!session) {
    redirect("/login?next=/history");
  }

  const conversations = await listConversationsForUser(session.id);

  return (
    <section className="mx-auto max-w-4xl px-6 py-12 sm:py-16">
      <header className="max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-accent">
          roadmodel
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-brand-slate-900 sm:text-4xl">
          Roadmap history
        </h1>
        <p className="mt-3 text-brand-slate-600">
          Pick up a past roadmap or browse what you have generated so far.
        </p>
      </header>

      <div className="mt-10">
        {conversations.length === 0 ? (
          <div
            className={
              "rounded-lg border border-brand-slate-200 bg-brand-slate-50 " +
              "px-6 py-10 text-center"
            }
          >
            <p className="text-brand-slate-700">
              No roadmaps yet. Start one at{" "}
              <Link href="/roadmap" className="font-medium text-brand-accent underline">
                /roadmap
              </Link>
              .
            </p>
          </div>
        ) : (
          <HistoryList conversations={conversations} />
        )}
      </div>
    </section>
  );
}
