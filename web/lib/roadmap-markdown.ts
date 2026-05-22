// web/lib/roadmap-markdown.ts
//
// Phase 4 Step 5 — pure RoadmapDraft → Markdown renderer used by
// /api/roadmaps/[id]/export. Section ordering matches the
// requirements block in the Step 5 task spec verbatim:
//
//   1. # <title>
//   2. ## Executive Summary
//   3. ## Phased Roadmap        (each phase = ### with Goal,
//                                bullets, nested Acceptance criteria)
//   4. ## Acceptance Criteria   (flat aggregated list across phases)
//   5. ## Glossary              (skipped when empty)
//
// Kept dependency-free and synchronous so the export route is a
// thin handler and so the unit-testable behavior can be covered
// without standing up an HTTP server.

import type { RoadmapDraft } from "./roadmap-types";

const DEFAULT_TITLE = "Untitled roadmap";

export function slugifyTitle(input: string | undefined | null): string {
  const text = (input ?? "").toLowerCase().trim();
  if (!text) {
    return "roadmap";
  }
  const slug = text
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return slug || "roadmap";
}

function renderPhase(phase: RoadmapDraft["phases"][number]): string {
  const lines: string[] = [];
  lines.push(`### ${phase.title}`);
  lines.push("");
  lines.push(`**Goal:** ${phase.goal}`);
  if (phase.sub_sections.length > 0) {
    lines.push("");
    for (const item of phase.sub_sections) {
      lines.push(`- ${item}`);
    }
  }
  if (phase.acceptance_criteria.length > 0) {
    lines.push("");
    lines.push("**Acceptance criteria**");
    for (const item of phase.acceptance_criteria) {
      lines.push(`- ${item}`);
    }
  }
  return lines.join("\n");
}

export function draftToMarkdown(draft: RoadmapDraft): string {
  const title = (draft.title ?? "").trim() || DEFAULT_TITLE;
  const sections: string[] = [];

  sections.push(`# ${title}`);

  sections.push(["## Executive Summary", "", draft.project_overview.trim()].join("\n"));

  const phaseBlocks = draft.phases.map(renderPhase);
  sections.push(["## Phased Roadmap", "", ...phaseBlocks].join("\n\n"));

  const allCriteria = draft.phases.flatMap((p) =>
    p.acceptance_criteria.map((c) => `- (${p.title}) ${c}`),
  );
  if (allCriteria.length > 0) {
    sections.push(["## Acceptance Criteria", "", ...allCriteria].join("\n"));
  } else {
    sections.push("## Acceptance Criteria");
  }

  if (draft.glossary.length > 0) {
    const rows = draft.glossary.map((g) => `- **${g.term}** — ${g.definition}`);
    sections.push(["## Glossary", "", ...rows].join("\n"));
  }

  return sections.join("\n\n") + "\n";
}
