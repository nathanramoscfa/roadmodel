// web/lib/roadmap-types.ts

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface RoadmapPhase {
  title: string;
  goal: string;
  sub_sections: string[];
  acceptance_criteria: string[];
}

export interface GlossaryEntry {
  term: string;
  definition: string;
}

export interface RoadmapDraft {
  // The top-level H1 heading. Captured from the engine's
  // streaming output and stored alongside the draft so the
  // /history page can search by project name. Optional because
  // historical drafts (pre-Step 5) may not have one.
  title?: string;
  project_overview: string;
  phases: RoadmapPhase[];
  glossary: GlossaryEntry[];
  generated_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  // Snippet of the most recent message in the conversation, used
  // by the /history list to give users a content-anchored cue
  // alongside the title + date.
  last_message_snippet: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
  draft: RoadmapDraft | null;
  // The roadmaps.id surfaced to the client so the export panel
  // can build a /api/roadmaps/[id]/export URL without a second
  // lookup. Null when the conversation has no draft yet.
  roadmap_id: string | null;
}
