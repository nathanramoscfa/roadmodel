import { expect, test } from "@playwright/test";
import type { createClient as sdkCreateClient } from "@supabase/supabase-js";
import type { createServerClient as sdkCreateServerClient } from "@supabase/ssr";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { format } from "node:util";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const ROOT = resolve(__dirname, "../..");
const MARKER = "SYNTHETIC_PRIVATE_RESPONSE";
const SCRIPTS = ["diag-recommend-capture.ts", "dogfood-recommend.ts", "soak-recommend.ts"] as const;
type Script = typeof SCRIPTS[number] | "probe-fable-cachebust.ts";
// Bind the constructor arguments, auth methods, and consumed response projection
// to the installed SDK declarations. These imports are erased at runtime.
type GenerateLink = ReturnType<typeof sdkCreateClient>["auth"]["admin"]["generateLink"];
type VerifyOtp = ReturnType<typeof sdkCreateServerClient>["auth"]["verifyOtp"];
type LinkResponse = Awaited<ReturnType<GenerateLink>>;
type LinkProperties = NonNullable<NonNullable<LinkResponse["data"]>["properties"]>;
type UsedLinkResponse = {
  data: { properties: Pick<LinkProperties, "hashed_token"> };
  error: LinkResponse["error"];
};
type UsedOtpResponse = Pick<Awaited<ReturnType<VerifyOtp>>, "error">;

function compile(source: string): string {
  const result = ts.transpileModule(source, {
    reportDiagnostics: true,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  expect(result.diagnostics).toEqual([]);
  return result.outputText;
}

// Run actual entrypoint code, substituting only imports/transport. No real SDK,
// credentials, provider, file writes, or sleeps are reachable from the VM.
async function diagnostic(script: Script, password = "synthetic-password") {
  const logs: string[] = [], tasks: string[] = [], artifacts: string[] = [];
  let authCalls = 0, otpCalls = 0, uuidCalls = 0;
  const uuids = Array.from({ length: 4 }, (_, i) => `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`);
  const env = {
    SUPABASE_URL: "https://database.invalid", SUPABASE_SERVICE_ROLE_KEY: "synthetic-service",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "synthetic-public", SITE_PASSWORD: password,
    ROADMODEL_LATENCY_BYPASS_TOKEN: "synthetic-bypass", ROADMODEL_DOGFOOD_EMAIL: ["synthetic", "example.invalid"].join("@"),
  };
  const processStub = {
    env, argv: ["node", "script", "https://app.invalid"], exitCode: undefined as number | undefined,
    exit(): never { throw new Error("Unexpected hard exit"); },
  };
  const health: Record<string, unknown> = {};
  runInNewContext(compile(readFileSync(join(ROOT, "scripts/soak-health.ts"), "utf8")), { exports: health });
  const outputPath = "/synthetic/private/rows.jsonl";
  const sandbox: Record<string, unknown> = {
    exports: {}, process: processStub, URL, performance,
    __auditModuleUrl: pathToFileURL(join(ROOT, "scripts", script)).href,
    console: Object.fromEntries(["log", "warn", "error"].map((name) => [name, (...args: unknown[]) => logs.push(format(...args))])),
    fetch: async (input: string | URL, init: { method: string; headers: Record<string, string>; body: string }) => {
      const expected = script === "probe-fable-cachebust.ts" ? "https://roadmodel.ai" : "https://app.invalid";
      expect(new URL(String(input)).origin).toBe(expected);
      expect(new URL(String(input)).pathname).toBe("/api/recommend");
      expect(init.method).toBe("POST");
      expect(init.headers.cookie).toContain(createHash("sha256").update(`roadmodel-gate-v1:${password}`).digest("hex"));
      const body = JSON.parse(init.body) as { task_description: unknown };
      expect(typeof body.task_description).toBe("string"); tasks.push(body.task_description as string);
      // These fields reached diagnostic stdout before the privacy correction.
      const pick = {
        model: `Claude ${MARKER}`, platform: "Cursor", conversation: "same-chat", rationale: MARKER,
        settings: { thinking: MARKER, max_mode: MARKER, rationale: MARKER }, rationale_sections: { pick: MARKER },
      };
      return { status: 200, ok: true, text: async () => JSON.stringify({
        ...pick, primary: "cheap", recommendations: ["cheap", "balanced", "best"].map((priority) => ({ ...pick, priority })),
        engine: { hint: "synthetic", maker: "synthetic" },
      }) };
    },
    require: (name: string): unknown => {
      switch (name) {
        case "node:crypto": return { createHash, randomUUID: () => { expect(uuidCalls).toBeLessThan(4); return uuids[uuidCalls++]; } };
        case "node:path": return path;
        case "node:url": return { fileURLToPath };
        case "node:timers/promises": return { setTimeout: async () => {} };
        case "./soak-health": return health;
        case "./private-diagnostic-output": return {
          createPrivateOutput(options: { prefix: string; path?: string }) {
            expect(["roadmodel-diag", "roadmodel-dogfood", "roadmodel-soak"]).toContain(options.prefix);
            expect(options.path).toBeUndefined();
            return { path: outputPath, write: (text: string) => artifacts.push(text), close() {} };
          },
        };
        case "node:fs": return {
          readFileSync(filename: string) {
            if (filename === join(ROOT, "scripts/soak_probes.json")) return JSON.stringify({ probes: [{ id: "synthetic-probe", task: "Synthetic prompt" }] });
            if (filename === join(ROOT, "web/data/catalog.json")) return JSON.stringify({ models: [] });
            throw new Error("Unexpected filesystem access");
          },
        };
        case "@supabase/supabase-js": return {
          createClient(...args: Parameters<typeof sdkCreateClient>) {
            const [url, key, options] = args;
            expect(url).toBe(env.SUPABASE_URL); expect(key).toBe(env.SUPABASE_SERVICE_ROLE_KEY); expect(options?.auth?.persistSession).toBe(false);
            return { auth: { admin: { generateLink: async (args: Parameters<GenerateLink>[0]): Promise<UsedLinkResponse> => {
              expect(args).toEqual({ type: "magiclink", email: env.ROADMODEL_DOGFOOD_EMAIL }); authCalls++;
              return { data: { properties: { hashed_token: "synthetic-hash" } }, error: null };
            } } } };
          },
        };
        case "@supabase/ssr": return {
          createServerClient(...args: Parameters<typeof sdkCreateServerClient>) {
            const [url, key, options] = args;
            expect(url).toBe(env.SUPABASE_URL); expect(key).toBe(env.NEXT_PUBLIC_SUPABASE_ANON_KEY); expect(options.cookies.getAll()).toEqual([]);
            return { auth: { verifyOtp: async (args: Parameters<VerifyOtp>[0]): Promise<UsedOtpResponse> => {
              expect(args).toEqual({ type: "magiclink", token_hash: "synthetic-hash" }); otpCalls++;
              expect(options.cookies.setAll).toBeDefined();
              await options.cookies.setAll!([
                { name: "synthetic-session", value: "synthetic-value", options: { path: "/" } },
              ], {
                "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
                Expires: "0", Pragma: "no-cache",
              });
              return { error: null };
            } } };
          },
        };
        default: throw new Error(`Unexpected diagnostic import: ${name}`);
      }
    },
  };
  const source = readFileSync(join(ROOT, "scripts", script), "utf8");
  expect(source.match(/main\(\)\.catch\(/g)).toHaveLength(1);
  // CJS-only harness accommodations: retain module URL and capture completion.
  runInNewContext(compile(source.replaceAll("import.meta.url", "__auditModuleUrl").replace("main().catch(", "globalThis.__task = main().catch(")), sandbox);
  expect(sandbox.__task).toBeDefined(); await sandbox.__task;
  expect(authCalls).toBe(1); expect(otpCalls).toBe(1);
  return { logs: logs.join("\n"), tasks, artifacts, uuidCalls, exitCode: processStub.exitCode ?? 0 };
}

for (const script of SCRIPTS) test(`${script} keeps returned text out of public diagnostics`, async () => {
  const result = await diagnostic(script);
  expect(result.tasks).toHaveLength(script === "soak-recommend.ts" ? 3 : 24);
  expect(result.artifacts).toHaveLength(1); expect(result.artifacts[0]).toContain(MARKER);
  expect(result.logs).not.toContain(MARKER);
  // The synthetic Cursor thinking value is a quality regression, not an outage.
  expect(result.exitCode).toBe(script === "soak-recommend.ts" ? 1 : 0);
  if (script === "soak-recommend.ts") {
    expect(result.logs).toContain("=== SOAK SCORECARD"); expect(result.logs).toContain("SERVICE_HEALTH: UP");
  }
});

test("cache-bust nonce is independent of the gate password and returned text stays private", async () => {
  const results = await Promise.all([diagnostic("probe-fable-cachebust.ts", "synthetic-A"), diagnostic("probe-fable-cachebust.ts", "synthetic-B")]);
  const nonces = results.map((result) => {
    expect(result.exitCode).toBe(0); expect(result.uuidCalls).toBe(4); expect(result.tasks).toHaveLength(4);
    expect(result.logs).not.toContain(MARKER);
    return result.tasks.map((task) => { const match = /^\[ref ([^\]]+)\]/.exec(task); expect(match).not.toBeNull(); return match![1]; });
  });
  expect(nonces[0]).toEqual(nonces[1]); expect(new Set(nonces[0]).size).toBe(4);
  for (const nonce of nonces[0]) expect(nonce).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
