// web/tests/history.spec.ts
//
// Phase 4 Step 5 — /history list + re-hydration + Markdown
// download coverage. Five scenarios, all using the E2E in-memory
// conversations store seeded via /api/test/seed-conversation:
//
//   1. empty state shows the "No roadmaps yet" copy
//   2. two seeded conversations render in updated_at DESC order
//   3. the title search input filters by substring
//   4. clicking Continue loads /roadmap/[id] with messages + draft
//      rendered from the persisted snapshot
//   5. clicking Download as Markdown serves a file whose body
//      preserves the template section ordering and whose
//      Content-Disposition filename slugifies the project title

// Seed env vars BEFORE the Playwright test harness loads any web/
// modules that transitively hit env.ts. Same pattern as
// roadmap-flow.spec.ts.
import "./fixtures/seed-test-env";

import { test, expect } from "@playwright/test";

import { clearE2eSession } from "./fixtures/onboarding-auth";

// The in-memory conversations store is process-global, so Playwright's
// default fullyParallel mode lets one test see another's seeds. Run
// this spec serially so resetE2eState() between tests is the only
// state-mutation point.
test.describe.configure({ mode: "serial" });

// Use a distinct uid for history tests so other specs running
// concurrently in different workers — which call
// /api/test/e2e-reset under the shared E2E_USER_ID — don't wipe
// the conversations we seed under this uid. /api/test/e2e-reset
// is scoped to the caller's cookie uid for exactly this reason.
const HISTORY_USER_ID = "00000000-0000-4000-8000-0000000000aa";
const HISTORY_AUTH_COOKIE = "rm-e2e-uid";

async function setHistorySessionCookie(
  page: import("@playwright/test").Page,
): Promise<void> {
  await page.context().addCookies([
    {
      name: HISTORY_AUTH_COOKIE,
      value: HISTORY_USER_ID,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}

// Per-test reset: clear browser cookies, pin the history uid
// cookie, then clear any stale conversations seeded under
// HISTORY_USER_ID. We deliberately do NOT call the global
// /api/test/e2e-reset here because that route wipes the
// profiles store globally — and onboarding.spec.ts (running
// in a parallel worker under E2E_USER_ID) depends on its
// profile staying put for the lifetime of its test.
async function resetHistoryState(
  page: import("@playwright/test").Page,
): Promise<void> {
  await clearE2eSession(page);
  await setHistorySessionCookie(page);
  await page.request.post("/api/test/clear-conversations", {
    data: { user_id: HISTORY_USER_ID },
  });
}

function isoMinusMinutes(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

async function seedConversation(
  request: import("@playwright/test").APIRequestContext,
  body: Record<string, unknown>,
): Promise<string> {
  const res = await request.post("/api/test/seed-conversation", {
    data: body,
  });
  expect(res.ok()).toBe(true);
  const json = (await res.json()) as { id: string };
  return json.id;
}

test("signed-in user with no past conversations sees the empty state", async ({
  page,
}) => {
  await resetHistoryState(page);

  await page.goto("/history");
  await expect(page.getByText(/No roadmaps yet/i)).toBeVisible();
  await expect(page.getByTestId("history-list")).toHaveCount(0);
});

test(
  "signed-in user with two past conversations sees them ordered by updated_at DESC",
  async ({ page, request }) => {
    await resetHistoryState(page);

    await seedConversation(request, {
      user_id: HISTORY_USER_ID,
      title: "Older analytics dashboard",
      updated_at: isoMinusMinutes(60),
      messages: [
        { role: "user", content: "I want an analytics dashboard." },
        { role: "assistant", content: "Got it — quick clarifier." },
      ],
    });
    await seedConversation(request, {
      user_id: HISTORY_USER_ID,
      title: "Newer billing project",
      updated_at: isoMinusMinutes(5),
      messages: [
        { role: "user", content: "Help me scope a billing rewrite." },
        { role: "assistant", content: "Sure — what is the target?" },
      ],
    });

    await page.goto("/history");
    const items = page.getByTestId("history-item");
    await expect(items).toHaveCount(2);
    // First row is the most recently updated conversation.
    await expect(items.nth(0)).toContainText("Newer billing project");
    await expect(items.nth(1)).toContainText("Older analytics dashboard");
  },
);

test("search input filters by title substring", async ({ page, request }) => {
  await resetHistoryState(page);

  await seedConversation(request, {
    user_id: HISTORY_USER_ID,
    title: "Analytics dashboard rebuild",
    updated_at: isoMinusMinutes(30),
    messages: [{ role: "user", content: "Analytics." }],
  });
  await seedConversation(request, {
    user_id: HISTORY_USER_ID,
    title: "Billing migration",
    updated_at: isoMinusMinutes(15),
    messages: [{ role: "user", content: "Billing." }],
  });

  await page.goto("/history");
  await expect(page.getByTestId("history-item")).toHaveCount(2);

  await page
    .getByLabel(/Search by project name/i)
    .fill("billing");
  // 300ms debounce window in HistoryList — wait it out then assert.
  await expect(page.getByTestId("history-item")).toHaveCount(1, {
    timeout: 2_000,
  });
  await expect(page.getByTestId("history-item")).toContainText(
    "Billing migration",
  );
});

test("Continue loads /roadmap/[id] with persisted messages and draft", async ({
  page,
  request,
}) => {
  await resetHistoryState(page);

  const id = await seedConversation(request, {
    user_id: HISTORY_USER_ID,
    title: "Customer feedback aggregator",
    updated_at: isoMinusMinutes(2),
    messages: [
      {
        role: "user",
        content: "Build a customer feedback aggregator.",
      },
      {
        role: "assistant",
        content: "What channels do you need to ingest from?",
      },
    ],
    draft: {
      title: "Customer feedback aggregator",
      project_overview:
        "A pipeline that aggregates customer feedback across channels.",
      phases: [
        {
          title: "Phase 1 — Ingestion",
          goal: "Stand up the ingest pipeline.",
          sub_sections: ["Webhook intake", "Normalizer worker"],
          acceptance_criteria: [
            "A sample webhook payload reaches the warehouse end-to-end.",
          ],
        },
      ],
      glossary: [],
      generated_at: new Date().toISOString(),
    },
  });

  await page.goto("/history");
  await page.getByRole("link", { name: /Continue/i }).first().click();
  await expect(page).toHaveURL(new RegExp(`/roadmap/${id}`));

  // Persisted messages render in the chat panel.
  await expect(
    page.getByText("Build a customer feedback aggregator."),
  ).toBeVisible();
  await expect(
    page.getByText(/What channels do you need to ingest from\?/i),
  ).toBeVisible();

  // Persisted draft renders in the preview panel.
  await expect(page.getByText(/Phase 1 — Ingestion/i)).toBeVisible();
  await expect(
    page.getByText(/A sample webhook payload reaches the warehouse/i),
  ).toBeVisible();

  // Export panel is reachable because both draft + roadmap_id
  // hydrated from the seed.
  await page.getByRole("button", { name: /Looks good — export/i }).click();
  await expect(page.getByTestId("export-panel")).toBeVisible();
});

test(
  "Download as Markdown serves a template-ordered file with slugified filename",
  async ({ page, request }) => {
    await resetHistoryState(page);

    await seedConversation(request, {
      user_id: HISTORY_USER_ID,
      title: "Streaming analytics platform",
      updated_at: isoMinusMinutes(1),
      messages: [
        { role: "user", content: "Streaming analytics for marketing." },
        {
          role: "assistant",
          content: "Drafted a roadmap below.",
        },
      ],
      draft: {
        title: "Streaming analytics platform",
        project_overview:
          "Streaming analytics platform for the marketing org.",
        phases: [
          {
            title: "Phase 1 — Foundation",
            goal: "Stand up the data plane.",
            sub_sections: ["Pipeline scaffold", "OIDC login"],
            acceptance_criteria: [
              "Ingest one sample event end-to-end.",
            ],
          },
        ],
        glossary: [
          { term: "ETL", definition: "Extract / Transform / Load." },
        ],
        generated_at: new Date().toISOString(),
      },
    });

    await page.goto("/history");
    await page.getByRole("link", { name: /Continue/i }).first().click();
    await page.getByRole("button", { name: /Looks good — export/i }).click();

    const downloadHref = await page
      .getByTestId("export-markdown")
      .getAttribute("href");
    expect(downloadHref).toMatch(/^\/api\/roadmaps\/[a-f0-9-]+\/export$/);

    // page.request inherits the session cookie set on this browser
    // context; the bare `request` fixture does not, so it would hit
    // the /api/roadmaps/[id]/export route as anonymous and get 401.
    const res = await page.request.get(downloadHref ?? "");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/markdown");
    expect(res.headers()["content-disposition"]).toContain(
      "streaming-analytics-platform.md",
    );

    const body = await res.text();
    // Template section ordering: title → Executive Summary →
    // Phased Roadmap → Acceptance Criteria → Glossary.
    const titleIdx = body.indexOf("# Streaming analytics platform");
    const summaryIdx = body.indexOf("## Executive Summary");
    const phasedIdx = body.indexOf("## Phased Roadmap");
    const acceptanceIdx = body.indexOf("## Acceptance Criteria");
    const glossaryIdx = body.indexOf("## Glossary");
    expect(titleIdx).toBeGreaterThanOrEqual(0);
    expect(summaryIdx).toBeGreaterThan(titleIdx);
    expect(phasedIdx).toBeGreaterThan(summaryIdx);
    expect(acceptanceIdx).toBeGreaterThan(phasedIdx);
    expect(glossaryIdx).toBeGreaterThan(acceptanceIdx);
    expect(body).toContain("Streaming analytics platform for the marketing");
    expect(body).toContain("Ingest one sample event end-to-end.");
    expect(body).toContain("ETL");
  },
);
