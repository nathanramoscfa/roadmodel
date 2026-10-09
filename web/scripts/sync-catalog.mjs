#!/usr/bin/env node
// web/scripts/sync-catalog.mjs
//
// Build-time copy of docs/catalog.json → web/data/catalog.json so
// web/lib/model-routing.ts can `import` the JSON via Next.js'
// tsconfig `@/data/catalog.json` alias — plus docs/benchmarks.json
// (the Artificial Analysis layer the /models grid reads) alongside
// it. Runs under both the local `next dev` and the production
// `next build` flows (wired via the
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
const BENCH_SOURCE = path.join(repoRoot, "docs", "benchmarks.json");
const BENCH_DEST = path.join(DEST_DIR, "benchmarks.json");
// The recommender's engine registry: the service runs engines from it and the
// /recommend menu is built from it (lib/recommend-engines.ts), so both
// deployments read the one file. Required, like the catalog.
const ENGINES_SOURCE = path.join(repoRoot, "service", "app", "engines.json");
const ENGINES_DEST = path.join(DEST_DIR, "engines.json");
// The measured figures the menu shows per engine (scripts/
// eval_recommend_engines.py --summary-json). Optional: without it the menu
// shows the registry's engines with catalog prices only.
const EVAL_SOURCE = path.join(repoRoot, "docs", "engine-eval.json");
const EVAL_DEST = path.join(DEST_DIR, "engine-eval.json");
// The keyless lane's measured agreement with the AI recommender (scripts/
// eval_keyless_agreement.py). Required: /recommend states its figures beside
// every Quick pick, and lib/keyless-eval.ts reads only this copy.
const KEYLESS_EVAL_SOURCE = path.join(repoRoot, "docs", "keyless-eval.json");
const KEYLESS_EVAL_DEST = path.join(DEST_DIR, "keyless-eval.json");
// Measured output tokens per model and effort (update/measure_effort_tokens.py).
// Required: the /recommend chart prices each effort by it, as the scorer does.
const EFFORT_TOKENS_SOURCE = path.join(repoRoot, "docs", "effort-tokens.json");
const EFFORT_TOKENS_DEST = path.join(DEST_DIR, "effort-tokens.json");

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

  // The benchmark layer is a sibling of the catalog: a refresh from
  // update/fetch_aa_benchmarks.py must reach the build the same way,
  // and the same fail-loud rule applies (a missing file would ship a
  // grid of dashes and read as "AA measured nothing").
  let benchRaw;
  try {
    benchRaw = await readFile(BENCH_SOURCE, "utf8");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(
      `[sync-catalog] failed to read ${BENCH_SOURCE}: ${msg}\n` +
        `  Regenerate it with \`python update/fetch_aa_benchmarks.py\`.`,
    );
    process.exitCode = 1;
    return;
  }
  let bench;
  try {
    bench = JSON.parse(benchRaw);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[sync-catalog] ${BENCH_SOURCE} is not valid JSON: ${msg}`);
    process.exitCode = 1;
    return;
  }
  if (!bench || typeof bench.models !== "object" || bench.models === null) {
    console.error(`[sync-catalog] ${BENCH_SOURCE} has no models object; refusing to copy.`);
    process.exitCode = 1;
    return;
  }
  await writeFile(BENCH_DEST, benchRaw, "utf8");
  console.log(
    `[sync-catalog] copied ${Object.keys(bench.models).length} benchmark rows → ${path.relative(webRoot, BENCH_DEST)}`,
  );

  let enginesRaw;
  try {
    enginesRaw = await readFile(ENGINES_SOURCE, "utf8");
    const engines = JSON.parse(enginesRaw);
    if (!Array.isArray(engines.engines) || engines.engines.length === 0) {
      throw new Error("no engines array");
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(
      `[sync-catalog] failed to read ${ENGINES_SOURCE}: ${msg}\n` +
        `  It is the recommender's engine registry; restore it from git.`,
    );
    process.exitCode = 1;
    return;
  }
  await writeFile(ENGINES_DEST, enginesRaw, "utf8");
  console.log(`[sync-catalog] copied the engine registry → ${path.relative(webRoot, ENGINES_DEST)}`);

  let evalRaw = '{"engines": {}}\n';
  try {
    evalRaw = await readFile(EVAL_SOURCE, "utf8");
    JSON.parse(evalRaw);
  } catch {
    console.warn(`[sync-catalog] no ${path.relative(repoRoot, EVAL_SOURCE)}; the engine menu shows prices only`);
    evalRaw = '{"engines": {}}\n';
  }
  await writeFile(EVAL_DEST, evalRaw, "utf8");

  let keylessRaw;
  try {
    keylessRaw = await readFile(KEYLESS_EVAL_SOURCE, "utf8");
    const record = JSON.parse(keylessRaw);
    if (
      !Number.isInteger(record.agree) ||
      !Number.isInteger(record.total) ||
      record.total <= 0 ||
      typeof record.evaluated_on !== "string" ||
      !Array.isArray(record.probes) ||
      record.probes.length === 0
    ) {
      throw new Error("missing agree / total / evaluated_on / probes");
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(
      `[sync-catalog] failed to read ${KEYLESS_EVAL_SOURCE}: ${msg}\n` +
        `  Regenerate it with \`python scripts/eval_keyless_agreement.py\`.`,
    );
    process.exitCode = 1;
    return;
  }
  await writeFile(KEYLESS_EVAL_DEST, keylessRaw, "utf8");
  console.log(`[sync-catalog] copied the keyless agreement record → ${path.relative(webRoot, KEYLESS_EVAL_DEST)}`);

  let tokensRaw;
  try {
    tokensRaw = await readFile(EFFORT_TOKENS_SOURCE, "utf8");
    const record = JSON.parse(tokensRaw);
    if (!record || typeof record.models !== "object" || record.models === null) {
      throw new Error("no models object");
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(
      `[sync-catalog] failed to read ${EFFORT_TOKENS_SOURCE}: ${msg}\n` +
        `  Regenerate it with \`python update/measure_effort_tokens.py\`.`,
    );
    process.exitCode = 1;
    return;
  }
  await writeFile(EFFORT_TOKENS_DEST, tokensRaw, "utf8");
  console.log(`[sync-catalog] copied the effort token measurements → ${path.relative(webRoot, EFFORT_TOKENS_DEST)}`);
}

await main();
