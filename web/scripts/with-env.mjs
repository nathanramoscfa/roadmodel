#!/usr/bin/env node
//
// Run a command with the variables from an env file layered on top of the
// current environment.
//
//     node scripts/with-env.mjs .env.ci npm run build
//
// One small loader instead of a dependency, so `npm ci` stays the only install
// step and CI does not grow a package it would have to pin and audit.
//
// Variables already set in the real environment WIN: CI can override a single
// value without editing the file, and a developer can point at a real service
// for one run without their shell being silently ignored.
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const [envFile, command, ...args] = process.argv.slice(2);
if (!envFile || !command) {
  console.error("usage: node scripts/with-env.mjs <env-file> <command> [args...]");
  process.exit(2);
}

/** KEY=value lines; `#` comments and blanks skipped. No interpolation, no
 *  quote stripping beyond a single matched pair — this file holds literal
 *  placeholders, and a parser that guesses is worse than one that doesn't. */
function parse(text) {
  const out = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (value.length >= 2 && value[0] === value.at(-1) && (value[0] === '"' || value[0] === "'")) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

const resolved = path.resolve(process.cwd(), envFile);
let parsed;
try {
  parsed = parse(readFileSync(resolved, "utf8"));
} catch (error) {
  console.error(`with-env: cannot read ${resolved}: ${error.message}`);
  process.exit(2);
}

const env = { ...process.env };
for (const [key, value] of Object.entries(parsed)) {
  if (env[key] === undefined) env[key] = value;
}

const child = spawn(command, args, { stdio: "inherit", env, shell: process.platform === "win32" });
child.on("error", (error) => {
  console.error(`with-env: ${command}: ${error.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
