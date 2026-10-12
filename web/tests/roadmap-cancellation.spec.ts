import "./fixtures/seed-test-env";
import Module from "node:module";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { AuditEntry } from "../lib/audit";

function deferred() {
  let resolve!: () => void;
  return { promise: new Promise<void>((done) => { resolve = done; }), resolve: () => resolve() };
}

for (const phase of ["provider", "persistence"] as const) {
  test(`browser cancellation during ${phase} preserves completed-work accounting`, async () => {
    const loader = Module as typeof Module & { _load: (request: string, parent: NodeModule | undefined, main?: boolean) => unknown };
    const saved = { load: loader._load, fetch: globalThis.fetch };
    const persisted = deferred(); const release = deferred(); const audited = deferred();
    const rows: AuditEntry[] = [];
    let aborted = false; let monthly = 0; let spend = 0; let assistantWrites = 0;
    // These doubles use the production callable types and return contracts.
    // The actual route and ReadableStream run unchanged; all HTTP is blocked.
    const stubs: Record<string, unknown> = {
      auth: {
        requireSession: async () => ({ id: "synthetic-user", app_metadata: {}, user_metadata: {}, aud: "authenticated", created_at: "2000-01-01T00:00:00Z" }),
      } satisfies Pick<typeof import("../lib/auth"), "requireSession">,
      env: { env: { ROADMAP_ENABLED: true, FRONTIER_ROADMAP_ENABLED: false } },
      profile: { getProfile: async () => null } satisfies Pick<typeof import("../lib/profile"), "getProfile">,
      "model-routing": {
        resolveRoadmapEngine: () => ({ engine: "gemini-2.5-flash", provider: "google", force_provider: "google-gemini-2.5-flash", max_tokens: 8192, use_frontier: false }),
      } satisfies Pick<typeof import("../lib/model-routing"), "resolveRoadmapEngine">,
      ratelimit: {
        checkRoadmapMonthlyLimit: async () => ({ allowed: true }),
        consumeRoadmapMonthlyToken: async () => { monthly++; },
      } satisfies Pick<typeof import("../lib/ratelimit"), "checkRoadmapMonthlyLimit" | "consumeRoadmapMonthlyToken">,
      "recommend-engines": { catalogCostUsd: () => 0.01 } satisfies Pick<typeof import("../lib/recommend-engines"), "catalogCostUsd">,
      "spend-guard": { recordSpend: () => { spend++; } } satisfies Pick<typeof import("../lib/spend-guard"), "recordSpend">,
      audit: { writeAudit: async (entry) => { rows.push(entry); audited.resolve(); } } satisfies Pick<typeof import("../lib/audit"), "writeAudit">,
      withFundingLane: {
        withFundingLane: (handler) => (req) => handler(req, { lane: "operator", reason: "invited" }),
        identifyRequest: () => ({ ipHash: "synthetic-ip-hash", uaHash: "synthetic-ua-hash", route: "/api/roadmap" }),
      } satisfies Pick<typeof import("../lib/withFundingLane"), "withFundingLane" | "identifyRequest">,
      conversations: {
        createConversation: async () => ({ id: "00000000-0000-4000-8000-000000000001", title: "Synthetic" }),
        insertMessage: async (args) => {
          if (args.role === "assistant") { assistantWrites++; persisted.resolve(); await release.promise; }
        },
      } satisfies Pick<typeof import("../lib/conversations"), "createConversation" | "insertMessage">,
      "roadmap-engine": {
        createRoadmapStream: async function* (args) {
          expect(args.signal).toBeInstanceOf(AbortSignal);
          if (phase === "provider") {
            await new Promise<void>((_, reject) => {
              args.signal!.addEventListener("abort", () => { aborted = true; reject(new DOMException("Aborted", "AbortError")); }, { once: true });
            });
          } else {
            yield { type: "message_complete", content: "Synthetic answer", input_tokens: 1, output_tokens: 1 };
          }
        },
      } satisfies Pick<typeof import("../lib/roadmap-engine"), "createRoadmapStream">,
    };
    const routePath = require.resolve("../app/api/roadmap/route");
    const previous = require.cache[routePath]; delete require.cache[routePath];
    loader._load = function (request, parent, main) {
      for (const [name, stub] of Object.entries(stubs)) {
        if (request === `@/lib/${name}` || request === path.resolve(__dirname, `../lib/${name}.ts`)) return stub;
      }
      return saved.load.call(this, request, parent, main);
    };
    globalThis.fetch = async () => { throw new Error("Unexpected fixture HTTP"); };
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { POST } = require(routePath) as typeof import("../app/api/roadmap/route");
      const response = await POST(new Request("https://app.invalid/api/roadmap", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: [{ id: "fixture", role: "user", content: "Synthetic", created_at: "2000-01-01T00:00:00Z" }] }),
      }));
      expect(response.status).toBe(200);
      const reader = response.body!.getReader(); await reader.read();
      if (phase === "persistence") await persisted.promise;
      await reader.cancel(); release.resolve(); await audited.promise;
      expect(aborted).toBe(phase === "provider");
      expect(assistantWrites).toBe(phase === "provider" ? 0 : 1);
      expect(monthly).toBe(phase === "provider" ? 0 : 1);
      expect(spend).toBe(phase === "provider" ? 0 : 1);
      expect(rows.map((row) => row.outcome)).toEqual([phase === "provider" ? "roadmap_error" : "ok"]);
    } finally {
      release.resolve(); loader._load = saved.load; globalThis.fetch = saved.fetch;
      if (previous) require.cache[routePath] = previous; else delete require.cache[routePath];
    }
  });
}
