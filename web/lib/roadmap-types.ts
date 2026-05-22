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
  project_overview: string;
  phases: RoadmapPhase[];
  glossary: GlossaryEntry[];
  generated_at: string;
}
