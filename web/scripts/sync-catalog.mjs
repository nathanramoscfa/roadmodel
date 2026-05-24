#!/usr/bin/env node
// web/scripts/sync-catalog.mjs
//
// Build-time copy of docs/catalog.json → web/data/catalog.json so
// web/lib/model-routing.ts can `import` the JSON via Next.js'
// tsconfig `@/data/catalog.json` alias. Runs under both the local
// `next dev` and the production `next build` flows (wired via the
// "predev" and "prebuild" npm scripts), and also fires on Vercel
// build hooks because Vercel honors prebuild like any standard
// npm hook.
//
// Failure mode is fail-loud-by-design: if docs/catalog.json is
// missing or unreadable, the script prints a pointer at the
// expected source and exits non-zero. Better than silently
// shipping an empty or stale catalog — the engine resolver would
// crash with NoEligibleEngineError at the first request anyway,
// and a build-time failure is cheaper than a runtime one.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, "..");
const repoRoot = path.resolve(webRoot, "..");

const SOURCE = path.join(repoRoot, "docs", "catalog.json");
const DEST_DIR = path.join(webRoot, "data");
const DEST = path.join(DEST_DIR, "catalog.json");

async function main() {
  let raw;
  try {
    raw = await readFile(SOURCE, "utf8");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(
      `[sync-catalog] failed to read ${SOURCE}: ${msg}\n` +
        `  Restore the file (it is the canonical model catalog) ` +
        `or run \`update-cache\` to regenerate it.`,
    );
    process.exitCode = 1;
    return;
  }

  // Sanity-check the JSON parses + carries a non-empty `models`
  // array before writing — a partial download would otherwise sit
  // in web/data/catalog.json and bypass the next freshness check.
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[sync-catalog] ${SOURCE} is not valid JSON: ${msg}`);
    process.exitCode = 1;
    return;
  }
  if (
    !parsed ||
    !Array.isArray(parsed.models) ||
    parsed.models.length === 0
  ) {
    console.error(
      `[sync-catalog] ${SOURCE} has no models array; refusing to copy.`,
    );
    process.exitCode = 1;
    return;
  }

  await mkdir(DEST_DIR, { recursive: true });
  await writeFile(DEST, raw, "utf8");
  console.log(
    `[sync-catalog] copied ${parsed.models.length} models → ${path.relative(webRoot, DEST)}`,
  );
}

await main();
