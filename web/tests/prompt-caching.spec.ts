// web/tests/prompt-caching.spec.ts
//
// Phase 4 Step 6 coverage — the Gemini cachedContent integration,
// the catalog-tracked engine resolver, the engine-overrides
// escape hatch, and the Phase 5 frontier defensive stubs. Mirrors
// the describe / test structure from roadmap-flow.spec.ts: side-
// effect env seed first, Playwright `test()` blocks operate as
// Node-side direct-import tests (no `page` fixture).

// Side-effect import — seeds the placeholder env vars BEFORE any
// transitive load of web/lib/env.ts. Must be the first import.
import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";
import type { GoogleGenAI } from "@google/genai";

import { setTestGeminiClient } from "../lib/gemini-client";
import {
  _resetCacheClientsForTest,
  extractCacheStats,
  getOrCreateCachedPrefix,
  setTestGoogleCacheClient,
  setTestRedisClient,
  type GoogleCacheClient,
} from "../lib/llm-cache";
import {
  _pickFreeEngineFromCatalog,
  inferProvider,
  pickFreeEngine,
  resolveRoadmapEngine,
} from "../lib/model-routing";
import { ENGINE_OVERRIDES } from "../lib/engine-overrides";
import { createRoadmapStream } from "../lib/roadmap-engine";
import { env } from "../lib/env";
import type { Profile } from "../lib/profile";

// ---------------------------------------------------------------
// Shared test helpers
// ---------------------------------------------------------------

interface CapturedCacheCreate {
  model: string;
  systemInstruction?: { parts?: { text?: string }[] } | unknown;
  contents?: unknown;
  ttl?: string;
}

interface CapturedGenerate {
  model: string;
  config: {
    systemInstruction: string;
    maxOutputTokens?: number;
    cachedContent?: string;
  };
  contents: { role: string; parts: { text: string }[] }[];
}

interface StubChunk {
  text: string;
  usageMetadata?: {
    promptTokenCount?: number;
    candidatesTokenCount?: number;
    cachedContentTokenCount?: number;
    cachedContentTokenCountUsed?: number;
  };
}

// Build a stub @google/genai client that records every
// `caches.create` and `models.generateContentStream` call against
// the passed-in arrays. The cachedContent name returned is
// deterministic so memoization tests can assert reuse.
function buildStubGeminiClient(
  cacheCalls: CapturedCacheCreate[],
  generateCalls: CapturedGenerate[],
  chunkBatches: StubChunk[][],
  cacheName: string,
): GoogleGenAI {
  let batchIdx = 0;
  return {
    caches: {
      create: async (params: { model: string; config?: CapturedCacheCreate }) => {
        cacheCalls.push({
          model: params.model,
          systemInstruction: params.config?.systemInstruction,
          contents: params.config?.contents,
          ttl: params.config?.ttl,
        });
        return { name: cacheName };
      },
    },
    models: {
      generateContentStream: async (params: CapturedGenerate) => {
        generateCalls.push(params);
        const batch = chunkBatches[batchIdx++] ?? [];
        return (async function* () {
          for (const chunk of batch) {
            yield chunk;
          }
        })();
      },
    },
  } as unknown as GoogleGenAI;
}

interface InMemoryRedis {
  get<T = unknown>(key: string): Promise<T | null>;
  set(
    key: string,
    value: string,
    opts?: { ex?: number },
  ): Promise<string | null>;
}

function buildInMemoryRedis(): InMemoryRedis & { _store: Map<string, string> } {
  const store = new Map<string, string>();
  return {
    _store: store,
    async get<T = unknown>(key: string): Promise<T | null> {
      const v = store.get(key);
      return v === undefined ? null : (v as unknown as T);
    },
    async set(key: string, value: string): Promise<string | null> {
      store.set(key, value);
      return "OK";
    },
  };
}

function profileWith(
  overrides: Partial<Profile> = {},
): Profile {
  const now = new Date().toISOString();
  return {
    user_id: "test-user",
    subscriptions: [],
    budget_priority: "balanced",
    allowed_jurisdictions: ["us"],
    onboarded_at: now,
    created_at: now,
    updated_at: now,
    frontier_roadmap_override: null,
    ...overrides,
  };
}

// 50+ messages so the rolling-history portion has enough bulk to
// exercise the chunkText path. Each entry is a short, deterministic
// string — the test cares about call shape, not response quality.
const TWO_TURN_MESSAGES = [
  {
    id: "u1",
    role: "user" as const,
    content: "Draft a roadmap for an analytics dashboard.",
    created_at: new Date().toISOString(),
  },
];

// ---------------------------------------------------------------
// 1. Engine resolver — catalog derivation, FAIL escalation, overrides
// ---------------------------------------------------------------

test("pickFreeEngine returns Gemini 2.5 Flash for planning-B on current catalog", () => {
  const resolved = pickFreeEngine({
    surface: "roadmap",
    minTier: "B",
    allowedJurisdictions: ["us"],
  });
  expect(resolved.engine).toBe("gemini-2.5-flash");
  expect(resolved.provider).toBe("google");
  expect(resolved.force_provider).toBe("google-gemini-2.5-flash");
  expect(resolved.use_frontier).toBe(false);
});

test("FAIL escalation: minTier='A' picks Gemini 3 Flash on current catalog", () => {
  const resolved = pickFreeEngine({
    surface: "roadmap",
    minTier: "A",
    allowedJurisdictions: ["us"],
  });
  expect(resolved.engine).toBe("gemini-3-flash");
  expect(resolved.provider).toBe("google");
  expect(resolved.force_provider).toBe("google-gemini-3-flash");
});

test(
  "catalog-derivation: synthetic cheaper planning-B model wins over Gemini 2.5 Flash",
  () => {
    const syntheticCatalog = {
      models: [
        {
          id: "gemini-test-cheap",
          name: "Gemini Test Cheap",
          input_price_per_1m: 0.1,
          output_price_per_1m: 1.0,
          tier_cost: "low",
          tiers: { planning: "B", knowledge: "B", speed: "S" } as const,
          jurisdiction: "us" as const,
        },
        {
          id: "gemini-2.5-flash",
          name: "Gemini 2.5 Flash",
          input_price_per_1m: 0.3,
          output_price_per_1m: 2.5,
          tier_cost: "low",
          tiers: { planning: "B", knowledge: "B", speed: "S" } as const,
          jurisdiction: "us" as const,
        },
      ],
    };
    const resolved = _pickFreeEngineFromCatalog(syntheticCatalog, {
      surface: "roadmap",
      minTier: "B",
      allowedJurisdictions: ["us"],
    });
    expect(resolved.engine).toBe("gemini-test-cheap");
    expect(resolved.provider).toBe("google");
    expect(resolved.force_provider).toBe("google-gemini-test-cheap");
  },
);

test(
  "ENGINE_OVERRIDES escape hatch: pin survives a synthetic cheaper catalog model",
  () => {
    // The override file is the maintainer's authoritative signal
    // that the catalog auto-pick should be skipped. With both a
    // pinned override and a cheaper synthetic in the catalog, the
    // override must win — the Phase 9 cron records the would-be
    // flip but the maintainer's pin holds.
    ENGINE_OVERRIDES.roadmap = "gemini-3-flash";
    try {
      const resolved = pickFreeEngine({
        surface: "roadmap",
        minTier: "B",
        allowedJurisdictions: ["us"],
      });
      expect(resolved.engine).toBe("gemini-3-flash");
      expect(resolved.provider).toBe("google");
    } finally {
      delete ENGINE_OVERRIDES.roadmap;
    }
  },
);

test("inferProvider maps catalog id prefixes to providers", () => {
  expect(inferProvider("gemini-2.5-flash")).toBe("google");
  expect(inferProvider("gpt-5-mini")).toBe("openai");
  expect(inferProvider("composer-2")).toBe("cursor");
  expect(inferProvider("sonnet-4.6")).toBe("anthropic");
  expect(inferProvider("opus-4.7")).toBe("anthropic");
  expect(inferProvider("claude-4.5-haiku")).toBe("anthropic");
  expect(inferProvider("grok-4.3")).toBe("xai");
  expect(inferProvider("kimi-k2.5")).toBe("moonshot");
  // Phase 4.6 T5 providers — deepseek-/mistral- prefixes + the codestral exception.
  expect(inferProvider("deepseek-v4-pro")).toBe("deepseek");
  expect(inferProvider("mistral-medium-3.5")).toBe("mistral");
  expect(inferProvider("codestral")).toBe("mistral");
});

test(
  "resolveRoadmapEngine returns the Anthropic shape when env frontier flag is true",
  () => {
    // The resolver's frontier branch return shape is legal even
    // in Phase 4; the downstream roadmap-engine wrapper is the
    // gate that throws. This test asserts the shape; the
    // wrapper-throw test below asserts the gate.
    const resolved = resolveRoadmapEngine({
      profile: profileWith(),
      envFrontierEnabled: true,
    });
    expect(resolved.engine).toBe("claude-sonnet-4-6");
    expect(resolved.provider).toBe("anthropic");
    expect(resolved.use_frontier).toBe(true);
    expect(resolved.max_tokens).toBe(4096);
  },
);

test(
  "resolveRoadmapEngine: per-user FALSE override beats env=true",
  () => {
    // Tri-state semantics — explicit FALSE forces the free tier
    // even when the env-var default would route to the frontier.
    const resolved = resolveRoadmapEngine({
      profile: profileWith({ frontier_roadmap_override: false }),
      envFrontierEnabled: true,
    });
    expect(resolved.engine).toBe("gemini-2.5-flash");
    expect(resolved.provider).toBe("google");
    expect(resolved.use_frontier).toBe(false);
  },
);

test(
  "resolveRoadmapEngine defaults to the free Google engine when env frontier flag is false (issue #155)",
  () => {
    // Regression for #155: the default free-tier path (no per-user
    // override, env flag false) must resolve to the Google engine,
    // NOT the Phase-5 Anthropic stub. Pairs with the env=true shape
    // test above.
    const resolved = resolveRoadmapEngine({
      profile: profileWith(),
      envFrontierEnabled: false,
    });
    expect(resolved.provider).toBe("google");
    expect(resolved.use_frontier).toBe(false);
    expect(resolved.engine).toBe("gemini-2.5-flash");
  },
);

test(
  "env.FRONTIER_ROADMAP_ENABLED is false when unset, not Boolean(\"false\")===true (issue #155)",
  () => {
    // The #155 root cause: z.coerce.boolean() runs Boolean(value),
    // and Boolean("false") === true. With the var unset (as in CI
    // and every prod scope), the flag MUST parse to false, otherwise
    // every /roadmap request routes to the not-yet-wired frontier
    // branch. seed-test-env does not set this var, so this asserts
    // the real unset condition through the actual env schema.
    expect(process.env.FRONTIER_ROADMAP_ENABLED).toBeUndefined();
    expect(env.FRONTIER_ROADMAP_ENABLED).toBe(false);
  },
);

// ---------------------------------------------------------------
// 2. llm-cache facade — memoization + Phase 5 defensive stubs
// ---------------------------------------------------------------

test(
  "getOrCreateCachedPrefix memoization round-trips through Redis",
  async () => {
    const redis = buildInMemoryRedis();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);

    const cacheCalls: CapturedCacheCreate[] = [];
    const stubClient: GoogleCacheClient = {
      async create({ model, contents, systemInstruction, ttl_seconds }) {
        cacheCalls.push({
          model,
          contents,
          systemInstruction,
          ttl: `${ttl_seconds}s`,
        });
        return { name: "cachedContents/test-cache-123" };
      },
    };
    setTestGoogleCacheClient(stubClient);

    // 5 KB of prefix content — comfortably above the
    // GOOGLE_MIN_PREFIX_CHARS gate so the facade attempts a
    // create rather than falling back to non-cached.
    const segments = {
      systemInstruction: "Test orientation. " + "X".repeat(2_000),
      contents: ["Template A. " + "Y".repeat(2_000), "Template B. " + "Z".repeat(2_000)],
    };

    try {
      const first = await getOrCreateCachedPrefix({
        provider: "google",
        model: "gemini-2.5-flash",
        segments,
      });
      const second = await getOrCreateCachedPrefix({
        provider: "google",
        model: "gemini-2.5-flash",
        segments,
      });

      expect(first).toBe("cachedContents/test-cache-123");
      expect(second).toBe(first);
      expect(cacheCalls.length).toBe(1); // memoized on second call
      // The memo key is keyed on the SHA-256 of the segments;
      // exact string check would couple the test to the hash
      // function. Asserting the prefix is the level of coupling
      // we want — the namespace ("gem-cache:") is stable contract.
      const stored = [...redis._store.keys()];
      expect(stored.length).toBe(1);
      expect(stored[0].startsWith("gem-cache:")).toBe(true);
    } finally {
      setTestGoogleCacheClient(null);
      setTestRedisClient(null);
      _resetCacheClientsForTest();
    }
  },
);

test(
  "getOrCreateCachedPrefix below GOOGLE_MIN_PREFIX_CHARS returns null (non-cached fallback)",
  async () => {
    const stubClient: GoogleCacheClient = {
      async create() {
        throw new Error("should not be called for a sub-min prefix");
      },
    };
    setTestGoogleCacheClient(stubClient);
    try {
      const result = await getOrCreateCachedPrefix({
        provider: "google",
        model: "gemini-2.5-flash",
        segments: {
          systemInstruction: "short",
          contents: ["small", "tiny"],
        },
      });
      expect(result).toBeNull();
    } finally {
      setTestGoogleCacheClient(null);
      _resetCacheClientsForTest();
    }
  },
);

test(
  "Phase 5 stub: getOrCreateCachedPrefix('anthropic') throws documented error",
  async () => {
    await expect(
      getOrCreateCachedPrefix({
        provider: "anthropic",
        model: "claude-sonnet-4-6",
        segments: { systemInstruction: "x", contents: [] },
      }),
    ).rejects.toThrowError(/Phase 5 scope: anthropic cache branch/);
  },
);

test("Phase 5 stub: extractCacheStats('anthropic', ...) throws", () => {
  expect(() => extractCacheStats("anthropic", {})).toThrowError(
    /Phase 5 scope: anthropic cache branch/,
  );
});

test("extractCacheStats('google', response) returns the Google variant", () => {
  const stats = extractCacheStats("google", {
    usageMetadata: {
      promptTokenCount: 4096,
      candidatesTokenCount: 512,
      cachedContentTokenCount: 3500,
      cachedContentTokenCountUsed: 3500,
    },
  });
  expect(stats).toEqual({
    provider: "google",
    promptTokenCount: 4096,
    candidatesTokenCount: 512,
    cachedContentTokenCount: 3500,
    cachedContentTokenCountUsed: 3500,
  });
});

// ---------------------------------------------------------------
// 3. createRoadmapStream — cache creation + reuse + audit shape
// ---------------------------------------------------------------

test(
  "createRoadmapStream emits a roadmap_draft for a NUMBERED-heading roadmap (issue #158)",
  async () => {
    // Regression for #158: the bundled project-roadmap-template.md numbers
    // its section headings ("## 1. Executive Summary", "## 7. Glossary"),
    // and the model follows it. The pre-fix parser regexes required bare
    // "## Executive Summary", so parseRoadmapDraft returned null on every
    // real roadmap and the preview panel never populated. This asserts the
    // draft IS extracted from a template-shaped (numbered) roadmap.
    const redis = buildInMemoryRedis();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);
    _resetCacheClientsForTest();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);

    const roadmapMd = [
      "# Alpaca Mean-Reversion Bot — Automated Trading",
      "",
      "## 1. Executive Summary",
      "",
      "Build and deploy a mean-reversion trading bot on Alpaca, paper then live.",
      "",
      "## 4. Phased Roadmap",
      "",
      "### Phase 1 — Foundation & Data Ingestion",
      "",
      "Goal: stand up the VM, database, and Alpaca data pipeline.",
      "",
      "- Provision the VM",
      "- Dockerize Postgres",
      "",
      "Acceptance criteria",
      "- VM reachable over SSH",
      "- Migrations applied",
      "",
      "### Phase 2 — Strategy & Backtesting",
      "",
      "Goal: implement the mean-reversion strategy and a backtester.",
      "",
      "- Build the backtest engine",
      "",
      "Acceptance criteria",
      "- Backtest reproduces a known result",
      "",
      "## 7. Glossary",
      "",
      "- EOD — end of day",
    ].join("\n");

    const cacheCalls: CapturedCacheCreate[] = [];
    const generateCalls: CapturedGenerate[] = [];
    const stub = buildStubGeminiClient(
      cacheCalls,
      generateCalls,
      [[{ text: roadmapMd, usageMetadata: { promptTokenCount: 1024, candidatesTokenCount: 256 } }]],
      "cachedContents/stub-158",
    );
    setTestGeminiClient(stub);

    let draft: { title?: string; project_overview: string; phases: { title: string }[] } | null =
      null;
    try {
      for await (const event of createRoadmapStream({
        messages: TWO_TURN_MESSAGES,
        profile: profileWith(),
        envFrontierEnabled: false,
      })) {
        if (event.type === "roadmap_draft") {
          draft = event.draft;
        }
      }
    } finally {
      setTestGeminiClient(null);
      setTestRedisClient(null);
      _resetCacheClientsForTest();
    }

    expect(draft).not.toBeNull();
    expect(draft?.title).toContain("Alpaca Mean-Reversion Bot");
    expect(draft?.project_overview).toContain("mean-reversion trading bot");
    expect(draft?.phases.map((p) => p.title)).toEqual([
      "Phase 1 — Foundation & Data Ingestion",
      "Phase 2 — Strategy & Backtesting",
    ]);
  },
);

test(
  "createRoadmapStream creates the Gemini cache on turn 1 and reuses it on turn 2",
  async () => {
    const redis = buildInMemoryRedis();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);
    _resetCacheClientsForTest();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);

    const cacheCalls: CapturedCacheCreate[] = [];
    const generateCalls: CapturedGenerate[] = [];

    // Turn 1: usage metadata reports cachedContentTokenCount > 0
    // (the cache resource was created). Turn 2: same metadata
    // plus cachedContentTokenCountUsed > 0 to model the SDK's
    // reuse signal.
    const turn1Chunks: StubChunk[] = [
      {
        text: "Got it. ",
        usageMetadata: {
          promptTokenCount: 1024,
          candidatesTokenCount: 128,
          cachedContentTokenCount: 800,
          cachedContentTokenCountUsed: 0,
        },
      },
    ];
    const turn2Chunks: StubChunk[] = [
      {
        text: "Continuing. ",
        usageMetadata: {
          promptTokenCount: 1100,
          candidatesTokenCount: 200,
          cachedContentTokenCount: 800,
          cachedContentTokenCountUsed: 800,
        },
      },
    ];

    const stub = buildStubGeminiClient(
      cacheCalls,
      generateCalls,
      [turn1Chunks, turn2Chunks],
      "cachedContents/stub-cache-1",
    );
    setTestGeminiClient(stub);

    let turn1Stats;
    let turn2Stats;
    try {
      // Turn 1 — fresh conversation, expects cache create.
      for await (const event of createRoadmapStream({
        messages: TWO_TURN_MESSAGES,
        profile: profileWith(),
        envFrontierEnabled: false,
      })) {
        if (event.type === "message_complete") {
          turn1Stats = event.cache_stats;
        }
      }

      // Turn 2 — appended user message, expects cache reuse.
      for await (const event of createRoadmapStream({
        messages: [
          ...TWO_TURN_MESSAGES,
          {
            id: "a1",
            role: "assistant",
            content: "Sure — what's the audience?",
            created_at: new Date().toISOString(),
          },
          {
            id: "u2",
            role: "user",
            content: "Marketing teams.",
            created_at: new Date().toISOString(),
          },
        ],
        profile: profileWith(),
        envFrontierEnabled: false,
      })) {
        if (event.type === "message_complete") {
          turn2Stats = event.cache_stats;
        }
      }
    } finally {
      setTestGeminiClient(null);
      setTestRedisClient(null);
      _resetCacheClientsForTest();
    }

    // Cache resource created exactly once (Redis memo serves
    // subsequent turns). Generate fired twice (both turns).
    expect(cacheCalls.length).toBe(1);
    expect(generateCalls.length).toBe(2);

    // Both calls reference the same cachedContent name.
    expect(generateCalls[0]?.config?.cachedContent).toBe(
      "cachedContents/stub-cache-1",
    );
    expect(generateCalls[1]?.config?.cachedContent).toBe(
      "cachedContents/stub-cache-1",
    );

    // The TTL on the cache resource is the documented 300s.
    expect(cacheCalls[0]?.ttl).toBe("300s");

    // Cache stats discriminator + numeric shape (audit-row contract).
    expect(turn1Stats).toMatchObject({
      provider: "google",
      cachedContentTokenCount: 800,
      cachedContentTokenCountUsed: 0,
    });
    expect(turn2Stats).toMatchObject({
      provider: "google",
      cachedContentTokenCount: 800,
      cachedContentTokenCountUsed: 800,
    });
  },
);

test(
  "cached request omits systemInstruction (Gemini rejects it with cachedContent) (#161)",
  async () => {
    // Regression for #161: a generate request that sets BOTH
    // cachedContent AND system_instruction is rejected by Gemini
    // ("CachedContent can not be used with GenerateContent request
    // setting system_instruction"). When a cache prefix is mounted the
    // orientation lives in the cache, so the request must carry NO
    // systemInstruction; the per-user profile rides as a leading
    // content turn instead. The stub cache client does not enforce
    // Gemini's rule, so this assertion is what guards the contract.
    const redis = buildInMemoryRedis();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);
    _resetCacheClientsForTest();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);

    const cacheCalls: CapturedCacheCreate[] = [];
    const generateCalls: CapturedGenerate[] = [];
    const stub = buildStubGeminiClient(
      cacheCalls,
      generateCalls,
      [[{ text: "ok", usageMetadata: { promptTokenCount: 1024, candidatesTokenCount: 16 } }]],
      "cachedContents/stub-161",
    );
    setTestGeminiClient(stub);

    try {
      for await (const _ of createRoadmapStream({
        messages: TWO_TURN_MESSAGES,
        profile: profileWith({ subscriptions: ["claude-max"], budget_priority: "best" }),
        envFrontierEnabled: false,
      })) {
        void _;
      }
    } finally {
      setTestGeminiClient(null);
      setTestRedisClient(null);
      _resetCacheClientsForTest();
    }

    // Precondition: the cache WAS mounted (else this test proves nothing).
    expect(cacheCalls.length).toBe(1);
    expect(generateCalls[0]?.config?.cachedContent).toBe("cachedContents/stub-161");
    // The #161 invariant: no systemInstruction alongside cachedContent.
    expect(generateCalls[0]?.config?.systemInstruction).toBeUndefined();
    // The profile (uncached) is delivered as a leading content turn, so
    // there are more content turns than input messages.
    expect(generateCalls[0]?.contents.length).toBeGreaterThan(TWO_TURN_MESSAGES.length);
  },
);

test(
  "FAIL-escalation path: minTier='A' routes through the same SDK, same caching API",
  async () => {
    // Mirrors the createRoadmapStream test but injects the
    // FAIL-shaped engine directly (the engine-overrides flip is
    // tested above; here we verify the wrapper still works when
    // the resolver hands it Gemini 3 Flash).
    const redis = buildInMemoryRedis();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);
    _resetCacheClientsForTest();
    setTestRedisClient(redis as unknown as Parameters<typeof setTestRedisClient>[0]);

    const cacheCalls: CapturedCacheCreate[] = [];
    const generateCalls: CapturedGenerate[] = [];
    const chunks: StubChunk[] = [
      {
        text: "ok",
        usageMetadata: {
          promptTokenCount: 1024,
          candidatesTokenCount: 128,
          cachedContentTokenCount: 900,
          cachedContentTokenCountUsed: 0,
        },
      },
    ];
    const stub = buildStubGeminiClient(
      cacheCalls,
      generateCalls,
      [chunks, chunks],
      "cachedContents/stub-cache-fail",
    );
    setTestGeminiClient(stub);

    try {
      for await (const _ of createRoadmapStream({
        messages: TWO_TURN_MESSAGES,
        profile: profileWith(),
        envFrontierEnabled: false,
        engine: {
          engine: "gemini-3-flash",
          provider: "google",
          force_provider: "google-gemini-3-flash",
          max_tokens: 8192,
          use_frontier: false,
        },
      })) {
        void _;
      }
      for await (const _ of createRoadmapStream({
        messages: TWO_TURN_MESSAGES,
        profile: profileWith(),
        envFrontierEnabled: false,
        engine: {
          engine: "gemini-3-flash",
          provider: "google",
          force_provider: "google-gemini-3-flash",
          max_tokens: 8192,
          use_frontier: false,
        },
      })) {
        void _;
      }
    } finally {
      setTestGeminiClient(null);
      setTestRedisClient(null);
      _resetCacheClientsForTest();
    }

    expect(cacheCalls.length).toBe(1); // cache create once
    expect(generateCalls.length).toBe(2); // generate twice
    expect(generateCalls.every((c) => c.model === "gemini-3-flash")).toBe(true);
    expect(generateCalls[1]?.config?.cachedContent).toBe(
      "cachedContents/stub-cache-fail",
    );
  },
);

test(
  "Phase 5 wrapper gate: createRoadmapStream throws on Anthropic engine",
  async () => {
    const generator = createRoadmapStream({
      messages: TWO_TURN_MESSAGES,
      profile: profileWith(),
      envFrontierEnabled: true,
      engine: {
        engine: "claude-sonnet-4-6",
        provider: "anthropic",
        force_provider: "anthropic-claude-sonnet-4-6",
        max_tokens: 4096,
        use_frontier: true,
      },
    });
    await expect(async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _ of generator) {
        void _;
      }
    }).rejects.toThrowError(/Phase 5 scope: anthropic engine branch/);
  },
);

test(
  "premature-override stub: profile.frontier_roadmap_override=true with env=false trips Phase 5 gate",
  async () => {
    // Defense-in-depth — the per-user override fires the frontier
    // branch even with FRONTIER_ROADMAP_ENABLED=false; the
    // wrapper's gate still refuses to execute Anthropic during
    // Phase 4.
    const generator = createRoadmapStream({
      messages: TWO_TURN_MESSAGES,
      profile: profileWith({ frontier_roadmap_override: true }),
      envFrontierEnabled: false,
    });
    await expect(async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _ of generator) {
        void _;
      }
    }).rejects.toThrowError(/Phase 5 scope: anthropic engine branch/);
  },
);
