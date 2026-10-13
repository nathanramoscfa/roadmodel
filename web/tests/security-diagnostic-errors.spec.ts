import { expect, test } from "@playwright/test";
import { AuthApiError, PostgrestError } from "@supabase/supabase-js";
import type { createClient as sdkCreateClient } from "@supabase/supabase-js";
import type { createServerClient as sdkCreateServerClient } from "@supabase/ssr";
import * as crypto from "node:crypto";
import { readFileSync } from "node:fs";
import * as path from "node:path";
import { format } from "node:util";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const ROOT = path.resolve(__dirname, "../..");
const SCRIPTS = [
  "diag-budget-priority-divergence.ts", "diag-three-card.ts", "probe-fable-trigger.ts",
  "probe-frontier-flip.ts", "probe-ladder.ts", "verify-budget-control.ts",
] as const;
type Script = typeof SCRIPTS[number] | "measure-recommend-latency.ts";
type Scenario = "link-error" | "otp-error" | "fetch-error" | "http-error" | "audit-error" | "success";
const MARKER = "SYNTHETIC_PRIVATE_RESPONSE";
type Client = ReturnType<typeof sdkCreateClient>;
type GenerateLink = Client["auth"]["admin"]["generateLink"];
type LinkResponse = Awaited<ReturnType<GenerateLink>>;
type LinkProperties = NonNullable<NonNullable<LinkResponse["data"]>["properties"]>;
type UsedLinkResponse = { data: { properties: Pick<LinkProperties, "hashed_token"> } | null; error: LinkResponse["error"] };
type VerifyOtp = ReturnType<typeof sdkCreateServerClient>["auth"]["verifyOtp"];
type UsedOtpResponse = Pick<Awaited<ReturnType<VerifyOtp>>, "error">;
type AuditTable = ReturnType<Client["from"]>;
type AuditQuery = ReturnType<AuditTable["select"]>;
type UsedAuditResponse = Pick<Awaited<AuditQuery>, "data" | "error">;
type UsedResponse = Pick<Response, "ok" | "status" | "headers" | "text" | "json">;

// Actual entrypoints in a closed VM: no SDK transport, network, private files,
// child processes, or real sleep. Actual SDK types bind consumed mock contracts.
async function diagnostic(script: Script, scenario: Scenario) {
  const logs: string[] = [];
  const calls = { link: 0, otp: 0, fetch: 0, audit: 0, validContract: true };
  const stop = new Error("Synthetic exit");
  const env = {
    SUPABASE_URL: "https://database.invalid", SUPABASE_SERVICE_ROLE_KEY: "synthetic-service",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "synthetic-public", SITE_PASSWORD: "synthetic-password",
    ROADMODEL_LATENCY_BYPASS_TOKEN: "synthetic-bypass", ROADMODEL_DOGFOOD_EMAIL: "fixture@example.invalid", SAMPLES: "1",
  };
  const argv = script === "measure-recommend-latency.ts"
    ? ["node", "script", "--target", "https://app.invalid", "--requests", "1", "--window-seconds", "1"]
    : script === "probe-ladder.ts" ? ["node", "script", "1", "https://app.invalid"]
      : ["node", "script", "https://app.invalid", "synthetic-prompt.txt"];
  const processStub = {
    env, argv, exitCode: 0,
    stdout: { write(value: string) { logs.push(value); } },
    stderr: { write(value: string) { logs.push(value); } },
    exit(code: number): never { this.exitCode = code; throw stop; },
  };
  const query = {
    select(...args: Parameters<AuditTable["select"]>) { calls.validContract &&= args[0] === "latency_ms"; return query; },
    eq(..._args: Parameters<AuditQuery["eq"]>) { return query; },
    gte(..._args: Parameters<AuditQuery["gte"]>) { return query; },
    async order(..._args: Parameters<AuditQuery["order"]>): Promise<UsedAuditResponse> {
      calls.audit++;
      return scenario === "audit-error"
        ? { data: null, error: new PostgrestError({ message: MARKER, details: MARKER, hint: MARKER, code: "XX000" }) }
        : { data: [{ latency_ms: { total_ms: 42, provider_ms: 10 } }], error: null };
    },
  };
  const sandbox: Record<string, unknown> = {
    exports: {}, process: processStub, URL, performance,
    console: Object.fromEntries(["log", "warn", "error"].map((name) => [name, (...args: unknown[]) => {
      if (!args.includes(stop)) logs.push(format(...args));
    }])),
    fetch: async (..._args: Parameters<typeof fetch>): Promise<UsedResponse> => {
      calls.fetch++;
      if (scenario === "fetch-error") throw new Error(MARKER);
      const failed = scenario === "http-error";
      return { ok: !failed, status: failed ? 503 : 200, headers: new Headers(),
        text: async () => failed ? MARKER : "{}", json: async () => ({}) };
    },
    require(name: string): unknown {
      switch (name) {
        case "node:crypto": return crypto;
        case "node:timers/promises": return { setTimeout: async () => {} };
        case "node:fs": return { readFileSync(filename: string) {
          if (filename !== "synthetic-prompt.txt") throw new Error("Unexpected fixture read");
          return "Synthetic prompt";
        } };
        case "@supabase/supabase-js": return {
          createClient(...args: Parameters<typeof sdkCreateClient>) {
            calls.validContract &&= args[0] === env.SUPABASE_URL && args[1] === env.SUPABASE_SERVICE_ROLE_KEY;
            return { auth: { admin: {
              async generateLink(args: Parameters<GenerateLink>[0]): Promise<UsedLinkResponse> {
                calls.link++;
                calls.validContract &&= args.type === "magiclink" && args.email === env.ROADMODEL_DOGFOOD_EMAIL;
                return scenario === "link-error"
                  ? { data: null, error: new AuthApiError(MARKER, 500, "unexpected_failure") }
                  : { data: { properties: { hashed_token: "synthetic-hash" } }, error: null };
              },
            } }, from(...args: Parameters<Client["from"]>) {
              calls.validContract &&= args[0] === "audit_log";
              return query;
            } };
          },
        };
        case "@supabase/ssr": return {
          createServerClient(...args: Parameters<typeof sdkCreateServerClient>) {
            const [url, key, options] = args;
            calls.validContract &&= url === env.SUPABASE_URL && key === env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
            return { auth: { async verifyOtp(args: Parameters<VerifyOtp>[0]): Promise<UsedOtpResponse> {
              calls.otp++;
              calls.validContract &&= typeof args === "object" && args !== null
                && "token_hash" in args && args.token_hash === "synthetic-hash";
              if (scenario === "otp-error") return { error: new AuthApiError(MARKER, 500, "unexpected_failure") };
              await options.cookies.setAll?.([{ name: "synthetic-session", value: "synthetic-cookie", options: {} }], {});
              return { error: null };
            } } };
          },
        };
        default: throw new Error("Unexpected fixture import");
      }
    },
  };
  const source = readFileSync(path.join(ROOT, "scripts", script), "utf8");
  expect((source.match(/main\(\)\.catch\(/g) ?? []).length).toBe(1);
  const compiled = ts.transpileModule(source.replace("main().catch(", "globalThis.__task = main().catch("), {
    reportDiagnostics: true,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  expect((compiled.diagnostics?.length ?? 0) === 0).toBe(true);
  let entryFailure = false;
  try {
    runInNewContext(compiled.outputText, sandbox, { timeout: 3000 });
    if (!sandbox.__task) throw new Error("Entrypoint did not start");
    await sandbox.__task;
  } catch (error) { if (error !== stop) entryFailure = true; }
  const output = logs.join("\n");
  return { calls, entryFailure, exitCode: processStub.exitCode, reflected: output.includes(MARKER),
    numericSummary: output.includes("| total_ms | 42 | 42 | 42 | 1 |") };
}

for (const script of SCRIPTS) for (const scenario of ["link-error", "otp-error", "fetch-error", "http-error"] as const) {
  test(`${script} keeps ${scenario} text out of diagnostics`, async () => {
    const result = await diagnostic(script, scenario);
    expect(result.entryFailure).toBe(false);
    expect(result.calls.validContract).toBe(true);
    expect(result.calls.link).toBe(1);
    expect(result.calls.otp).toBe(scenario === "link-error" ? 0 : 1);
    expect(result.calls.fetch > 0).toBe(scenario === "fetch-error" || scenario === "http-error");
    expect(result.reflected).toBe(false);
    // Some probes intentionally report non-JSON input without failing the run.
    if (scenario !== "http-error") expect(result.exitCode).not.toBe(0);
  });
}
for (const scenario of ["http-error", "audit-error", "fetch-error", "success"] as const) {
  test(`latency diagnostic preserves fixed ${scenario} reporting`, async () => {
    const result = await diagnostic("measure-recommend-latency.ts", scenario);
    expect(result.entryFailure).toBe(false);
    expect(result.calls.validContract).toBe(true);
    expect(result.calls.fetch).toBe(1);
    expect(result.calls.audit).toBe(scenario === "audit-error" || scenario === "success" ? 1 : 0);
    expect(result.reflected).toBe(false);
    expect(result.numericSummary).toBe(scenario === "success");
    expect(result.exitCode === 0).toBe(scenario === "success");
  });
}
