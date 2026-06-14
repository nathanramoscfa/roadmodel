// web/lib/glossary.ts
//
// Plain-English definitions for the tier ratings + benchmark names the
// recommender cites in its rationale, so the UI can show inline "what does this
// mean?" popovers (#269). Sourced from docs/model-selector.txt:
//   - <benchmark-sources> (the benchmark one-liners), and
//   - the S/A/B/C/D <model-options> tier scale.
// Keep in sync if those change. A term not listed here simply renders without a
// popover (graceful — no breakage), so drift degrades quietly rather than failing.

interface GlossaryEntry {
  // Canonical label (for reference/tests); the visible text stays whatever the
  // rationale wrote (e.g. "Terminal-Bench Hard").
  term: string;
  definition: string;
  // Surface forms to match in the rationale, matched case-sensitively (the
  // recommender writes benchmark names in their canonical case).
  phrases: string[];
}

const TIER_SCALE = "Per-category quality rating: S (best) → D (worst).";

const ENTRIES: GlossaryEntry[] = [
  { term: "S-tier", definition: `Top-1 or top-2 globally in this task category. ${TIER_SCALE}`, phrases: ["S-tier"] },
  { term: "A-tier", definition: `Strong, reliable, near-frontier in this category. ${TIER_SCALE}`, phrases: ["A-tier"] },
  { term: "B-tier", definition: `Competent for this category. ${TIER_SCALE}`, phrases: ["B-tier"] },
  { term: "C-tier", definition: `Limited — usable only for trivial work in this category. ${TIER_SCALE}`, phrases: ["C-tier"] },
  { term: "D-tier", definition: `Not suited for this category. ${TIER_SCALE}`, phrases: ["D-tier"] },
  {
    term: "LMArena",
    definition: "Human-preference Elo ranking across general chat (chatbot-arena.com).",
    phrases: ["LMArena"],
  },
  {
    term: "Artificial Analysis Intelligence Index",
    definition:
      "A composite of 10 evaluations (incl. GPQA Diamond, Humanity's Last Exam, SciCode, and Terminal-Bench Hard).",
    phrases: ["Artificial Analysis Intelligence Index", "AA Intelligence Index"],
  },
  {
    term: "Aider polyglot",
    definition: "Coding benchmark across C++, Go, Java, JavaScript, Python, and Rust.",
    phrases: ["Aider polyglot"],
  },
  {
    term: "SWE-bench Verified",
    definition:
      "Real GitHub issues (500-instance human-filtered subset) — the gold standard for software-engineering capability.",
    phrases: ["SWE-bench Verified", "SWE-bench"],
  },
  {
    term: "LiveCodeBench",
    definition:
      "Contamination-free coding benchmark with rolling problems from LeetCode / AtCoder / Codeforces.",
    phrases: ["LiveCodeBench"],
  },
  {
    term: "τ²-bench",
    definition:
      "Agentic / tool-use benchmark with a real tool–agent–user loop (airline, retail, banking).",
    phrases: ["τ²-bench"],
  },
  { term: "LiveBench", definition: "Contamination-resistant multi-domain benchmark.", phrases: ["LiveBench"] },
  {
    term: "Terminal-Bench",
    definition: "Terminal and agent task-execution benchmark.",
    phrases: ["Terminal-Bench Hard", "Terminal-Bench 2.0", "Terminal-Bench"],
  },
  {
    term: "GPQA Diamond",
    definition: "Graduate-level science-reasoning benchmark.",
    phrases: ["GPQA Diamond", "GPQA"],
  },
  { term: "AIME", definition: "Advanced math-olympiad problems.", phrases: ["AIME"] },
  { term: "MMMU", definition: "Multimodal university-level understanding benchmark.", phrases: ["MMMU"] },
  {
    term: "Humanity's Last Exam",
    definition: "Frontier-difficulty general-intelligence exam (HLE).",
    phrases: ["Humanity's Last Exam", "HLE"],
  },
  {
    term: "CursorBench",
    definition: "Cursor's benchmark from real coding sessions (terse prompts, multi-file solutions).",
    phrases: ["CursorBench"],
  },
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const PHRASE_TO_ENTRY = new Map<string, GlossaryEntry>();
for (const entry of ENTRIES) {
  for (const phrase of entry.phrases) {
    PHRASE_TO_ENTRY.set(phrase, entry);
  }
}

// Longest-first so "Terminal-Bench Hard" wins over "Terminal-Bench", and
// "SWE-bench Verified" over "SWE-bench". Custom alphanumeric boundaries (not \b)
// so non-ASCII phrases (τ²-bench) match and short acronyms (AIME, HLE)
// don't match inside words (e.g. "aime" in "claimed").
const ALL_PHRASES = [...PHRASE_TO_ENTRY.keys()].sort((a, b) => b.length - a.length);
const GLOSSARY_RE = new RegExp(
  `(?<![A-Za-z0-9])(${ALL_PHRASES.map(escapeRegExp).join("|")})(?![A-Za-z0-9])`,
  "g",
);

export interface GlossarySegment {
  // The slice of the original text. For a glossary match, `term`/`definition`
  // are also set. Concatenating every `text` reconstructs the input losslessly.
  text: string;
  term?: string;
  definition?: string;
}

export function segmentRationale(text: string): GlossarySegment[] {
  const segments: GlossarySegment[] = [];
  let last = 0;
  for (const match of text.matchAll(GLOSSARY_RE)) {
    const start = match.index ?? 0;
    const matched = match[0];
    if (start > last) {
      segments.push({ text: text.slice(last, start) });
    }
    const entry = PHRASE_TO_ENTRY.get(matched);
    segments.push(
      entry
        ? { text: matched, term: entry.term, definition: entry.definition }
        : { text: matched },
    );
    last = start + matched.length;
  }
  if (last < text.length) {
    segments.push({ text: text.slice(last) });
  }
  return segments.length > 0 ? segments : [{ text }];
}
