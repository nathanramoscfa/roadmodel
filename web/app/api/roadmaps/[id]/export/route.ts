// web/app/api/roadmaps/[id]/export/route.ts
//
// Phase 4 Step 5 — Markdown export for a stored RoadmapDraft.
// The roadmaps row is fetched with the session-bound supabase
// client so RLS pins the read to auth.uid() = user_id. A
// cross-user GET surfaces as 404, never as a silent empty render.
//
// Phase 6 will add HTML / PDF / DOCX siblings under
// /api/roadmaps/[id]/export.{ext}; the Markdown variant ships
// alone in Phase 4 because it has no headless-browser or font
// dependency.

import { NextResponse } from "next/server";

import { AuthError, requireSession } from "@/lib/auth";
import { getRoadmapById } from "@/lib/conversations";
import { draftToMarkdown, slugifyTitle } from "@/lib/roadmap-markdown";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(_req: Request, ctx: RouteContext): Promise<Response> {
  let userId: string;
  try {
    const session = await requireSession();
    userId = session.id;
  } catch (err) {
    const status = err instanceof AuthError ? err.status : 401;
    return NextResponse.json({ error: "unauthorized" }, { status });
  }

  const { id } = await ctx.params;
  const roadmap = await getRoadmapById(id, userId);
  if (!roadmap) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  const markdown = draftToMarkdown(roadmap.draft);
  const filename = `${slugifyTitle(roadmap.draft.title)}.md`;

  return new Response(markdown, {
    status: 200,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "private, no-store",
    },
  });
}
