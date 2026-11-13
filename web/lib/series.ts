// web/lib/series.ts
//
// A model's series and version, read off its catalog id — the same rule as
// src/roadmodel/series.py, which the recommender applies. `claude-fable-5.2`
// and `claude-fable-5.1` are one series, the later version 5.2; `gpt-6-sol`
// and `gpt-6-luna` are two series; a parameter count (`20b`, `a3b`) names a
// size, not a version.

const SIZE_RE = /(?<![a-z0-9.])a?\d+(?:\.\d+)?[bmk](?![a-z0-9])/g;
const VENDOR_WORDS = new Set(["claude"]);

function split(id: string): { rest: string; sizes: string[] } {
  const text = id.toLowerCase();
  return { rest: text.replace(SIZE_RE, " "), sizes: (text.match(SIZE_RE) ?? []).sort() };
}

// The id's name words, plus any size; empty when it has no name word.
export function series(id: string): Set<string> {
  const { rest, sizes } = split(id);
  const words = new Set((rest.match(/[a-z]+/g) ?? []).filter((w) => !VENDOR_WORDS.has(w)));
  if (words.size === 0) return words;
  for (const s of sizes) words.add(`size:${s}`);
  return words;
}

// The id's version numbers, in order: `gpt-6.1-sol` → [6, 1].
export function version(id: string): number[] {
  return (split(id).rest.match(/\d+/g) ?? []).map(Number);
}

// Python's tuple order: element by element, a shorter prefix first.
export function compareVersions(a: readonly number[], b: readonly number[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i += 1) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return a.length - b.length;
}

// Whether `next` is a later version of `old`'s series.
export function isNewer(old: string, next: string): boolean {
  const s = series(old);
  const t = series(next);
  return s.size > 0 && s.size === t.size && [...s].every((w) => t.has(w))
    && compareVersions(version(next), version(old)) > 0;
}
