import { expect, test } from "@playwright/test";
import type { createClient as sdkCreateClient } from "@supabase/supabase-js";
import type { createServerClient as sdkCreateServerClient } from "@supabase/ssr";
import * as crypto from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const ROOT = path.resolve(__dirname, "../..");
const SCRIPTS = [
  "diag-budget-priority-divergence.ts", "diag-recommend-capture.ts", "diag-three-card.ts",
  "dogfood-recommend.ts", "probe-fable-cachebust.ts", "probe-fable-trigger.ts",
  "probe-frontier-flip.ts", "probe-funding-lanes.ts", "probe-ladder.ts",
  "soak-recommend.ts", "verify-budget-control.ts",
] as const;
type Script = typeof SCRIPTS[number];
const EMAIL = "fixture@example.invalid";
type Client = ReturnType<typeof sdkCreateClient>;
type GenerateLink = Client["auth"]["admin"]["generateLink"];
type CreateUser = Client["auth"]["admin"]["createUser"];
type DeleteUser = Client["auth"]["admin"]["deleteUser"];
type UsedDeleteResponse = Pick<Awaited<ReturnType<DeleteUser>>, "error">;
type LinkResponse = Awaited<ReturnType<GenerateLink>>;
type LinkProperties = NonNullable<NonNullable<LinkResponse["data"]>["properties"]>;
type UsedLinkResponse = { data: { properties: Pick<LinkProperties, "hashed_token"> }; error: LinkResponse["error"] };
type UserResponse = Awaited<ReturnType<CreateUser>>;
type UsedUserResponse = { data: { user: Pick<NonNullable<UserResponse["data"]["user"]>, "id"> }; error: UserResponse["error"] };
type VerifyOtp = ReturnType<typeof sdkCreateServerClient>["auth"]["verifyOtp"];
type UsedOtpResponse = Pick<Awaited<ReturnType<VerifyOtp>>, "error">;

function compile(source: string): string {
  const result = ts.transpileModule(source, {
    reportDiagnostics: true,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  expect((result.diagnostics?.length ?? 0) === 0).toBe(true);
  return result.outputText;
}

// Same isolated actual-entrypoint pattern as security-diagnostic-stdout.spec.ts.
// No real SDK, network, private file, child process or sleep can be reached.
async function diagnostic(script: Script, account: string | undefined) {
  const calls = { auth: 0, userCreate: 0, userDelete: 0, fetch: 0, privateWriter: 0, privateRead: 0, expectedAccount: 0 };
  const logs: string[] = [];
  const stop = new Error("Synthetic fixture transport stopped");
  const env: Record<string, string | undefined> = {
    SUPABASE_URL: "https://database.invalid", SUPABASE_SERVICE_ROLE_KEY: "synthetic-service",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "synthetic-public", SITE_PASSWORD: "synthetic-password",
    ROADMODEL_LATENCY_BYPASS_TOKEN: "synthetic-bypass", UPSTASH_REDIS_URL: "https://redis.invalid",
    UPSTASH_REDIS_REST_TOKEN: "synthetic-redis", UPSTASH_REDIS_TOKEN: "synthetic-redis", SAMPLES: "1",
  };
  if (account !== undefined) env.ROADMODEL_DOGFOOD_EMAIL = account;
  const processStub = {
    env, argv: ["node", "script", "https://app.invalid", "synthetic-prompt.txt"],
    exitCode: undefined as number | undefined,
    stdout: { write() {} }, stderr: { write() {} },
    exit(code: number): never { this.exitCode = code; throw stop; },
  };
  const health: Record<string, unknown> = {}, gate: Record<string, unknown> = {};
  runInNewContext(compile(readFileSync(path.join(ROOT, "scripts/soak-health.ts"), "utf8")), { exports: health });
  runInNewContext(compile(readFileSync(path.join(ROOT, "web/lib/gate.ts"), "utf8")), {
    exports: gate, crypto: crypto.webcrypto, TextEncoder,
  });
  const admin = {
    async generateLink(args: Parameters<GenerateLink>[0]): Promise<UsedLinkResponse> {
      calls.auth++;
      // Do not pass a received account to an assertion formatter: an old
      // implementation may contain a real fallback. Record only equality.
      if (args.email === EMAIL) calls.expectedAccount++;
      return { data: { properties: { hashed_token: "synthetic-hash" } }, error: null };
    },
    async createUser(_args: Parameters<CreateUser>[0]): Promise<UsedUserResponse> {
      calls.userCreate++;
      return { data: { user: { id: "synthetic-user" } }, error: null };
    },
    async deleteUser(..._args: Parameters<DeleteUser>): Promise<UsedDeleteResponse> {
      calls.userDelete++; return { error: null };
    },
  };
  const sandbox: Record<string, unknown> = {
    exports: {}, process: processStub, URL, performance, Buffer, TextEncoder,
    __auditModuleUrl: pathToFileURL(path.join(ROOT, "scripts", script)).href,
    console: Object.fromEntries(["log", "warn", "error"].map((name) => [name, (...args: unknown[]) => {
      if (args.includes(stop)) return;
      logs.push(args.map((value) => typeof value === "string" ? value : "[object]").join(" "));
    }])),
    fetch: async () => { calls.fetch++; throw stop; },
    require: (name: string): unknown => {
      switch (name) {
        case "node:crypto": return crypto;
        case "node:path": return path;
        case "node:url": return { fileURLToPath };
        case "node:timers/promises": return { setTimeout: async () => {} };
        case "./soak-health": return health;
        case "../web/lib/gate": return gate;
        case "./private-diagnostic-output": return {
          createPrivateOutput() {
            calls.privateWriter++;
            return { path: "/synthetic/private/rows.jsonl", write() {}, close() {} };
          },
        };
        case "node:fs": return {
          readFileSync(filename: string) {
            if (filename.endsWith("soak_probes.json")) return JSON.stringify({ probes: [{ id: "synthetic", task: "Synthetic prompt" }] });
            if (filename.endsWith("catalog.json")) return JSON.stringify({ models: [] });
            if (filename === "synthetic-prompt.txt") { calls.privateRead++; return "Synthetic prompt"; }
            throw new Error("Unexpected fixture file read");
          },
        };
        case "@supabase/supabase-js": return {
          createClient(...args: Parameters<typeof sdkCreateClient>) {
            const [url, key] = args;
            expect(url === env.SUPABASE_URL).toBe(true);
            expect(key === env.SUPABASE_SERVICE_ROLE_KEY).toBe(true);
            return { auth: { admin }, from(..._args: Parameters<Client["from"]>): never { throw stop; } };
          },
        };
        case "@supabase/ssr": return {
          createServerClient(...args: Parameters<typeof sdkCreateServerClient>) {
            const [url, key, options] = args;
            expect(url === env.SUPABASE_URL).toBe(true);
            expect(key === env.NEXT_PUBLIC_SUPABASE_ANON_KEY).toBe(true);
            return { auth: { verifyOtp: async (_args: Parameters<VerifyOtp>[0]): Promise<UsedOtpResponse> => {
              await options.cookies.setAll?.([{ name: "synthetic-session", value: "synthetic-cookie", options: {} }], {});
              return { error: null };
            } } };
          },
        };
        default: throw new Error("Unexpected fixture import");
      }
    },
  };
  let entryFailure = false;
  try {
    const source = readFileSync(path.join(ROOT, "scripts", script), "utf8");
    expect(source.match(/main\(\)\.catch\(/g)).toHaveLength(1);
    runInNewContext(compile(source.replaceAll("import.meta.url", "__auditModuleUrl")
      .replace("main().catch(", "globalThis.__task = main().catch(")), sandbox, { timeout: 3000 });
    if (!sandbox.__task) throw new Error("Entrypoint did not start");
    await sandbox.__task;
  } catch (error) {
    if (error !== stop) entryFailure = true;
  }
  const output = logs.join("\n");
  return {
    calls, entryFailure, exitCode: processStub.exitCode ?? 0,
    printedAccount: output.includes(EMAIL),
    fixedMissingDiagnostic: output.includes("Required diagnostic account configuration is missing.")
      || output.includes("missing env ROADMODEL_DOGFOOD_EMAIL") || output.includes("Diagnostic run failed."),
  };
}

for (const script of SCRIPTS) {
  for (const [label, account] of [["absent", undefined], ["empty", ""]] as const) {
    test(`${script} refuses ${label} account before private or remote effects`, async () => {
      const result = await diagnostic(script, account);
      expect(result.entryFailure).toBe(false);
      expect(Object.values(result.calls).every((count) => count === 0)).toBe(true);
      expect(result.exitCode).not.toBe(0);
      expect(result.fixedMissingDiagnostic).toBe(true);
      expect(result.printedAccount).toBe(false);
    });
  }
  test(`${script} uses the configured synthetic account`, async () => {
    const result = await diagnostic(script, EMAIL);
    expect(result.entryFailure).toBe(false);
    expect(result.calls.expectedAccount).toBe(1);
    expect(result.printedAccount).toBe(false);
  });
}

test("every TypeScript diagnostic using an account environment field has runtime coverage", () => {
  const discovered: string[] = [];
  function sourceFiles(relative = ""): string[] {
    return readdirSync(path.join(ROOT, "scripts", relative), { withFileTypes: true }).flatMap((entry) => {
      const child = path.join(relative, entry.name);
      if (entry.isDirectory()) return sourceFiles(child);
      return entry.isFile() && /\.[cm]?[jt]sx?$/.test(entry.name) ? [child] : [];
    });
  }
  for (const name of sourceFiles()) {
    const source = readFileSync(path.join(ROOT, "scripts", name), "utf8");
    const ast = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true);
    let found = false;
    function visit(node: ts.Node) {
      let field: string | undefined;
      if (ts.isPropertyAccessExpression(node)) field = node.name.text;
      if (ts.isElementAccessExpression(node) && node.argumentExpression && ts.isStringLiteral(node.argumentExpression)) field = node.argumentExpression.text;
      if (field?.endsWith("_EMAIL") && (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node))
        && node.expression.getText(ast) === "process.env") found = true;
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "need"
        && node.arguments.some((arg) => ts.isStringLiteral(arg) && arg.text.endsWith("_EMAIL"))) found = true;
      ts.forEachChild(node, visit);
    }
    visit(ast);
    if (found) discovered.push(name);
  }
  expect(discovered.sort()).toEqual([...SCRIPTS].sort());
});
