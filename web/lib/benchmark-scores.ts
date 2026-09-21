// web/lib/benchmark-scores.ts
//
// Pulls the NUMBERS out of a model's `headline_benchmarks` prose so the /models
// table can show magnitude next to each S→D letter — the honest numeric scale:
// every figure here is a published leaderboard result with a source, not a
// score we invent. The prose is semi-structured ("<Benchmark> <number>[%]
// (qualifier); …"), curated by the daily catalog cron, so extraction is a
// per-benchmark pattern anchored on the glossary's canonical names, and a row
// that carries no figure for a category simply shows none.
//
// The benchmark → category mapping MIRRORS the cron's "Source-to-category
// mapping" in update/prompt.md (Tier rating updates), so the number shown under
// a rating is the evidence the cron is allowed to move that rating on.
//
// PURE — no catalog import, safe for the client bundle; the server page calls
// scoresFor() per row and passes the small result down as props.

import type { Category } from "@/lib/catalog-fields";

export type ScoreUnit = "" | "%" | "Elo" | "tok/s";

export interface BenchmarkScore {
  // Glossary canonical term (matches lib/glossary.ts `term`), e.g. "SWE-bench Verified".
  term: string;
  // The benchmark AS CITED, variant included — "Terminal-Bench 2.1" and
  // "Terminal-Bench Hard" are different tests, as are τ²-bench's banking and
  // retail subsets — so two rows are only comparable when their labels match.
  label: string;
  // Two-to-eight-character form of `label` for a table cell ("TB 2.1", "SWE-V").
  short: string;
  value: number;
  unit: ScoreUnit;
  // Compact rendering: "80.6%", "89.1", "1479 Elo", "151 tok/s".
  display: string;
  // Source leaderboard (the glossary's verified url), for the tooltip.
  url?: string;
}

interface BenchmarkPattern {
  term: string;
  // Matches the benchmark name plus any version / subset / metric tokens that
  // precede the figure ("Terminal-Bench 2.1", "τ²-bench banking pass_1"), so
  // the first number AFTER the match is the score itself. Group 1, when
  // present, captures the variant (version or subset).
  name: RegExp;
  // Cell abbreviation; a function when the variant matters.
  short: string | ((variant: string) => string);
  unit: ScoreUnit;
  url?: string;
}

const TAU_SUBSET: Record<string, string> = {
  airline: "air",
  banking: "bank",
  retail: "retail",
  telecom: "tel",
};

// Same source urls as lib/glossary.ts (keep in sync; a drift only loses a link).
const PATTERNS: BenchmarkPattern[] = [
  {
    term: "SWE-bench Verified",
    name: /SWE-bench Verified(?:\s*\([^)]*\))?/,
    short: "SWE-V",
    unit: "",
    url: "https://www.swebench.com/",
  },
  {
    term: "LiveCodeBench",
    name: /LiveCodeBench/,
    short: "LCB",
    unit: "",
    url: "https://livecodebench.github.io/",
  },
  {
    term: "Aider polyglot",
    name: /Aider polyglot/,
    short: "Aider",
    unit: "",
    url: "https://aider.chat/docs/leaderboards/",
  },
  {
    term: "CursorBench",
    name: /CursorBench/,
    short: "CB",
    unit: "",
    url: "https://cursor.com/blog/cursorbench",
  },
  {
    term: "Terminal-Bench",
    name: /Terminal-Bench(?:\s+(Hard|\d\.\d))?/,
    short: (v) => (v ? `TB ${v}` : "TB"),
    unit: "",
    url: "https://www.tbench.ai/",
  },
  {
    term: "τ²-bench",
    name: /τ²-bench(?:\s+(airline|banking|retail|telecom))?(?:\s+pass_\d)?/,
    short: (v) => (v ? `τ² ${TAU_SUBSET[v] ?? v}` : "τ²"),
    unit: "",
    url: "https://github.com/sierra-research/tau2-bench",
  },
  {
    term: "MMMU",
    name: /MMMU/,
    short: "MMMU",
    unit: "",
    url: "https://mmmu-benchmark.github.io/",
  },
  {
    term: "Humanity's Last Exam",
    name: /(?:Humanity's Last Exam|HLE)/,
    short: "HLE",
    unit: "",
    url: "https://agi.safe.ai/",
  },
  {
    term: "GPQA Diamond",
    name: /GPQA(?:\s+Diamond)?/,
    short: "GPQA",
    unit: "",
    url: "https://github.com/idavidrein/gpqa",
  },
  {
    term: "LMArena",
    // The Elo may follow the subset directly ("LMArena Text Elo 1478.9") or sit
    // after a rank in parentheses ("LMArena Text #5 (Elo 1481.7)").
    name: /LMArena(?:\s+(Text|WebDev|Search))?(?:\s+#\d+)?(?:\s*\()?\s*Elo/,
    // `display` already ends in "Elo"; only a non-default arena needs naming.
    short: (v) => (v && v !== "Text" ? v : ""),
    unit: "Elo",
    url: "https://lmarena.ai/",
  },
  {
    term: "AIME",
    name: /AIME(?:\s*(\d{4}))?/,
    short: (v) => (v ? `AIME ${v.slice(2)}` : "AIME"),
    unit: "",
    url: "https://matharena.ai/",
  },
  {
    term: "LiveBench",
    name: /LiveBench/,
    short: "LB",
    unit: "",
    url: "https://livebench.ai/",
  },
];

// The composite the "AA Index" column shows — the closest thing to a single
// number, and the densest figure in the catalog. Not a per-category benchmark.
const AA_INDEX = /(?:Artificial Analysis|AA) Intelligence Index/;

// Output throughput, written as "Output Speed 151.4 tokens/s" or "~500 tokens/s".
const SPEED_RE = /(~?)(\d+(?:\.\d+)?)\s*tokens\/s/;

// Which benchmark's figure a category cell shows, first match wins. Mirrors
// update/prompt.md's source-to-category mapping for tier updates; `knowledge`
// prefers HLE because it is the figure most rows carry (the AA Index composite
// has its own column). `long-context` has no leaderboard in <benchmark-sources>.
export const CATEGORY_BENCHMARKS: Record<Category, string[]> = {
  coding: ["SWE-bench Verified", "LiveCodeBench", "Aider polyglot", "CursorBench"],
  planning: ["LMArena"],
  agentic: ["Terminal-Bench", "τ²-bench"],
  multimodal: ["MMMU"],
  "long-context": [],
  knowledge: ["Humanity's Last Exam", "GPQA Diamond", "LiveBench", "AIME"],
  speed: ["Output speed"],
};

export interface RowScores {
  // Artificial Analysis Intelligence Index, or null when the row has none.
  aaIndex: number | null;
  // Every figure found, in prose order (for the expanded row / tests).
  all: BenchmarkScore[];
  // The headline figure per category, where the prose carries one.
  byCategory: Partial<Record<Category, BenchmarkScore>>;
}

// A clause runs to the next ";" — the cron separates benchmarks with ";" and
// keeps a benchmark's qualifiers ("(max)", "(#1)") inside its clause.
function clauseAfter(text: string, from: number): string {
  const end = text.indexOf(";", from);
  return text.slice(from, end === -1 ? text.length : end);
}

// First numeric token in `s` that is a score: skips ranks ("#5"), a leading
// version token ("2.1" in "Terminal-Bench 2.1 89.1") when a further number
// follows, and anything glued to a letter ("1M", "o3-mini").
function firstScore(s: string): { value: number; pct: boolean } | null {
  const re = /(?<![A-Za-z0-9#.])(\d+(?:\.\d+)?)(%?)(?![A-Za-z0-9])/g;
  const found: { value: number; pct: boolean; text: string }[] = [];
  for (const m of s.matchAll(re)) {
    found.push({ value: Number(m[1]), pct: m[2] === "%", text: m[1] });
    if (found.length === 2) break;
  }
  if (found.length === 0) return null;
  const [first, second] = found;
  if (second && /^\d\.\d$/.test(first.text) && !first.pct) return second;
  return first;
}

function format(value: number, unit: ScoreUnit, approx = false): string {
  switch (unit) {
    case "%":
      return `${value}%`;
    case "Elo":
      return `${Math.round(value)} Elo`;
    case "tok/s":
      return `${approx ? "~" : ""}${Math.round(value)} tok/s`;
    default:
      return `${value}`;
  }
}

// "Terminal-Bench 2.1", "τ²-bench banking", "LMArena Text", "SWE-bench Verified".
function citedLabel(term: string, variant: string | undefined): string {
  return variant ? `${term} ${variant}` : term;
}

export function extractScores(prose: string): BenchmarkScore[] {
  const found: { at: number; score: BenchmarkScore }[] = [];
  for (const p of PATTERNS) {
    const m = p.name.exec(prose);
    if (!m) continue;
    const score = firstScore(clauseAfter(prose, m.index + m[0].length));
    if (!score) continue;
    // Show "%" only where the prose does — the cron writes HLE as "53.3%" but
    // Terminal-Bench and GPQA as bare figures, and we never add precision.
    const unit: ScoreUnit = score.pct ? "%" : p.unit;
    const variant = m[1];
    found.push({
      at: m.index,
      score: {
        term: p.term,
        label: citedLabel(p.term, variant),
        short: typeof p.short === "function" ? p.short(variant ?? "") : p.short,
        value: score.value,
        unit,
        display: format(score.value, unit),
        url: p.url,
      },
    });
  }
  const speed = SPEED_RE.exec(prose);
  if (speed) {
    const value = Number(speed[2]);
    found.push({
      at: speed.index,
      score: {
        term: "Output speed",
        label: "Output speed",
        short: "",
        value,
        unit: "tok/s",
        display: format(value, "tok/s", speed[1] === "~"),
        url: "https://artificialanalysis.ai/",
      },
    });
  }
  // Prose order, so the expanded row reads like the source text.
  return found.sort((a, b) => a.at - b.at).map((f) => f.score);
}

export function extractAaIndex(prose: string): number | null {
  const m = AA_INDEX.exec(prose);
  if (!m) return null;
  const score = firstScore(clauseAfter(prose, m.index + m[0].length));
  return score ? score.value : null;
}

export function scoresFor(prose: string): RowScores {
  const all = extractScores(prose);
  const byTerm = new Map(all.map((s) => [s.term, s]));
  const byCategory: Partial<Record<Category, BenchmarkScore>> = {};
  for (const [cat, terms] of Object.entries(CATEGORY_BENCHMARKS) as [Category, string[]][]) {
    for (const term of terms) {
      const s = byTerm.get(term);
      if (s) {
        byCategory[cat] = s;
        break;
      }
    }
  }
  return { aaIndex: extractAaIndex(prose), all, byCategory };
}
