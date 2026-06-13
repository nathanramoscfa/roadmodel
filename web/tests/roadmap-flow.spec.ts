// web/tests/roadmap-flow.spec.ts
//
// Phase 4 Step 4 coverage. Splits into:
//   - UI integration tests via page.route() to mock /api/roadmap
//     SSE responses (PreviewPanel rendering, 401 fallback).
//   - Node-side direct-import tests for the prompt-assembly and
//     engine-wrapper contracts (systemInstruction contents,
//     segment ordering, SDK call shape).
//
// Mirrors the describe/test structure from recommend.spec.ts; the
// same Playwright runner executes both groups because Playwright
// `test()` runs in Node and we simply omit the `page` fixture in
// the Node-side blocks.

// Side-effect import seeds Node-side env vars BEFORE any
// transitive load of web/lib/env.ts. Must be the first import.
import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";
import type { GoogleGenAI } from "@google/genai";

import { setTestGeminiClient } from "../lib/gemini-client";
import { createRoadmapStream } from "../lib/roadmap-engine";
import { loadSystemInstruction } from "../lib/roadmap-prompts";

import {
  resetE2eState,
  setE2eSessionCookie,
} from "./fixtures/onboarding-auth";

const COMPOSER_PLACEHOLDER =
  /Describe your project\. Paste, type, or attach anything\./i;

// ---------------------------------------------------------------
// UI integration — mock /api/roadmap from the browser side.
// ---------------------------------------------------------------

function ssePayload(events: Array<Record<string, unknown>>): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

test(
  "signed-in first message streams clarifying question + roadmap draft",
  async ({ page }) => {
    await resetE2eState(page);
    await setE2eSessionCookie(page);

    await page.route("**/api/roadmap", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-cache, no-transform",
        },
        body: ssePayload([
          { type: "message_delta", delta: "Got it. " },
          {
            type: "message_delta",
            delta: "Before drafting — what's your launch target?",
          },
          {
            type: "roadmap_draft",
            draft: {
              project_overview:
                "Streaming analytics dashboard for marketing teams.",
              phases: [
                {
                  title: "Phase 1 — Foundation",
                  goal: "Stand up data ingest + auth.",
                  sub_sections: ["Pipeline scaffold", "OIDC login"],
                  acceptance_criteria: [
                    "Ingest a sample event end-to-end.",
                  ],
                },
              ],
              glossary: [],
              generated_at: new Date().toISOString(),
            },
          },
          {
            type: "message_complete",
            content:
              "Got it. Before drafting — what's your launch target?",
          },
        ]),
      }),
    );

    await page.goto("/roadmap");
    await page
      .getByPlaceholder(COMPOSER_PLACEHOLDER)
      .fill("analytics dashboard for marketing teams");
    await page.getByRole("button", { name: /Send/i }).click();

    await expect(
      page.getByText(/what's your launch target/i),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByText(/Streaming analytics dashboard/i),
    ).toBeVisible();
    await expect(page.getByText(/Phase 1 — Foundation/i)).toBeVisible();
    await expect(
      page.getByText(/Ingest a sample event end-to-end\./i),
    ).toBeVisible();
  },
);

test(
  "mid-stream 401 keeps the user message visible without crashing",
  async ({ page }) => {
    await resetE2eState(page);
    await setE2eSessionCookie(page);
    await page.route("**/api/roadmap", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: "unauthorized" }),
      }),
    );

    await page.goto("/roadmap");
    await page
      .getByPlaceholder(COMPOSER_PLACEHOLDER)
      .fill("a roadmap for an internal tool");
    await page.getByRole("button", { name: /Send/i }).click();

    // The user's message should remain visible (it was added
    // optimistically before the POST). The 401 handler removes
    // only the placeholder assistant bubble and downgrades the
    // composer into anonymous-fallback mode (covered by
    // roadmap-shell.spec.ts's anonymous-flow tests once the
    // wall wraps the composer). The smoke check here is that
    // the UI doesn't crash or get stuck on the 401.
    await expect(
      page.getByText("a roadmap for an internal tool"),
    ).toBeVisible({ timeout: 5_000 });
  },
);

// ---------------------------------------------------------------
// Server-contract tests — POST directly, no UI.
// ---------------------------------------------------------------

test(
  "unauthenticated POST /api/roadmap returns 401",
  async ({ playwright }) => {
    const ctx = await playwright.request.newContext();
    const res = await ctx.post("http://localhost:3000/api/roadmap", {
      data: {
        messages: [
          {
            id: "1",
            role: "user",
            content: "hi",
            created_at: new Date().toISOString(),
          },
        ],
      },
    });
    expect(res.status()).toBe(401);
    await ctx.dispose();
  },
);

test(
  "Zod rejects empty messages array with 400",
  async ({ playwright }) => {
    const ctx = await playwright.request.newContext();
    await ctx.post("http://localhost:3000/api/test/e2e-reset");
    const res = await ctx.post("http://localhost:3000/api/roadmap", {
      headers: {
        Cookie:
          "rm-e2e-uid=00000000-0000-4000-8000-000000000001",
      },
      data: { messages: [] },
    });
    expect(res.status()).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("bad_input");
    await ctx.dispose();
  },
);

// ---------------------------------------------------------------
// Direct-import contract tests — prompt-assembly invariants.
// ---------------------------------------------------------------
//
// These tests load the engine + prompt modules in the Playwright
// Node process. They never start a browser context.

test("systemInstruction contains both templates verbatim", async () => {
  const text = await loadSystemInstruction({ profile: null });
  expect(text).toContain("PROJECT ROADMAP TEMPLATE");
  expect(text).toContain("PHASE ROADMAP TEMPLATE");
});

test(
  "profile segment is appended AFTER the template segments",
  async () => {
    const text = await loadSystemInstruction({
      profile: {
        user_id: "test-user",
        subscriptions: ["claude-max"],
        api_providers: [],
        budget_priority: "cheap",
        allowed_jurisdictions: ["us"],
        onboarded_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        frontier_roadmap_override: null,
      },
    });
    const projectIdx = text.indexOf("PROJECT ROADMAP TEMPLATE");
    const phaseIdx = text.indexOf("PHASE ROADMAP TEMPLATE");
    const profileIdx = text.indexOf("User context:");
    expect(projectIdx).toBeGreaterThan(-1);
    expect(phaseIdx).toBeGreaterThan(projectIdx);
    expect(profileIdx).toBeGreaterThan(phaseIdx);
    expect(text).toContain("subscriptions = [claude-max]");
    expect(text).toContain("budget = cheap");
  },
);

test(
  "createRoadmapStream passes contents oldest-first and emits draft",
  async () => {
    type CapturedParams = {
      model: string;
      contents: Array<{ role: string; parts: Array<{ text: string }> }>;
      config: { systemInstruction: string; maxOutputTokens: number };
    };
    let captured: CapturedParams | null = null;

    // The H1 heading needs to be on its own line for the engine's
    // draft-detection heuristic to fire (TOP_HEADING_RE requires
    // start-of-string or a preceding newline before the `# `).
    const cannedChunks = [
      { text: "Got it.\n\n" },
      { text: "# Streaming analytics dashboard\n\n" },
      {
        text:
          "## Executive Summary\n\n" +
          "Streaming analytics dashboard for marketing teams.\n\n",
      },
      {
        text:
          "## Phase 1 — Foundation\n\n" +
          "Goal: Stand up data ingest + auth.\n\n" +
          "- Pipeline scaffold\n" +
          "- OIDC login\n\n" +
          "Acceptance criteria\n" +
          "- Ingest a sample event end-to-end.\n",
      },
    ];

    const stubClient = {
      models: {
        generateContentStream: async (params: CapturedParams) => {
          captured = params;
          return (async function* () {
            for (const chunk of cannedChunks) {
              yield chunk;
            }
          })();
        },
      },
    };
    setTestGeminiClient(stubClient as unknown as GoogleGenAI);

    const events: Array<{ type: string }> = [];
    try {
      for await (const event of createRoadmapStream({
        messages: [
          {
            id: "u1",
            role: "user",
            content: "I want a streaming analytics dashboard.",
            created_at: new Date().toISOString(),
          },
          {
            id: "a1",
            role: "assistant",
            content: "What's the audience?",
            created_at: new Date().toISOString(),
          },
          {
            id: "u2",
            role: "user",
            content: "Marketing teams.",
            created_at: new Date().toISOString(),
          },
        ],
        profile: null,
      })) {
        events.push(event);
      }
    } finally {
      setTestGeminiClient(null);
    }

    if (captured === null) {
      throw new Error("Stub generateContentStream was never called");
    }
    const params: CapturedParams = captured;
    expect(params.model).toBe("gemini-2.5-flash");
    expect(params.contents[0]?.role).toBe("user");
    expect(params.contents[0]?.parts[0]?.text).toContain(
      "streaming analytics dashboard",
    );
    expect(params.contents[1]?.role).toBe("model");
    expect(params.contents[2]?.role).toBe("user");
    expect(params.config?.systemInstruction).toContain(
      "PROJECT ROADMAP TEMPLATE",
    );
    expect(params.config?.systemInstruction).toContain(
      "PHASE ROADMAP TEMPLATE",
    );

    const types = events.map((e) => e.type);
    expect(types).toContain("message_delta");
    expect(types).toContain("roadmap_draft");
    expect(types[types.length - 1]).toBe("message_complete");
  },
);
