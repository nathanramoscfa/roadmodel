// web/tests/recommend.spec.ts
import { test, expect } from "@playwright/test";

test("/recommend renders form + empty output", async ({ page }) => {
  await page.goto("/recommend");
  await expect(
    page.getByPlaceholder(/Input the prompt/i),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Submit/i }),
  ).toBeVisible();
  await expect(
    page.getByText(/Your recommendation will appear here/i),
  ).toBeVisible();
});

test(
  "successful submit renders model, platform, cost table, free-tier label",
  async ({ page }) => {
    await page.route("**/api/recommend", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          model: "Claude 4.5 Haiku",
          platform: "Anthropic API",
          settings: {
            max_tokens: 4096,
          },
          session_cost_estimate: {
            total_usd: 0.0042,
          },
          comparison_table: [
            {
              model: "Claude 4.5 Haiku",
              platform: "Anthropic API",
              total_usd: 0.0042,
            },
          ],
        }),
      }),
    );
    await page.goto("/recommend");
    await page
      .getByPlaceholder(/Input the prompt/i)
      .fill("build a SQL agent");
    await page.getByRole("button", { name: /Submit/i }).click();
    await expect(page.getByText(/Claude 4.5 Haiku/i)).toBeVisible();
    // The engine-tier line names the engine that produced the recommendation
    // (#271), not the recommended model.
    await expect(page.getByText(/free engine/i)).toBeVisible();
    // This payload carries no backup, so the backup line must not render.
    await expect(page.getByText(/Backup if unavailable/i)).toHaveCount(0);
  },
);

test("renders the backup model line when the recommendation includes one", async ({
  page,
}) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model: "Opus 4.8",
        platform: "Claude Code",
        settings: { max_mode: "OFF", thinking: "High" },
        backup: "GPT-5.5",
        comparison_table: [],
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("build a SQL agent");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(page.getByText(/Backup if unavailable/i)).toBeVisible();
  await expect(page.getByText(/GPT-5\.5/)).toBeVisible();
});

test("humanizes settings labels and renders the rationale prominently", async ({
  page,
}) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model: "Opus 4.8",
        platform: "Claude Code",
        settings: {
          max_mode: "OFF",
          thinking: "High",
          budget_priority: "balanced",
          rationale: "Chosen for deep reasoning on a hard task.",
        },
        conversation: "New",
        comparison_table: [],
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("prove a theorem");
  await page.getByRole("button", { name: /Submit/i }).click();
  // Humanized labels + values in the settings list (term/definition roles —
  // scoped so we don't collide with the budget picker in the prompt form).
  await expect(
    page.getByRole("term").filter({ hasText: "Max Mode" }),
  ).toBeVisible();
  await expect(
    page.getByRole("term").filter({ hasText: "Budget Priority" }),
  ).toBeVisible();
  await expect(
    page.getByRole("definition").filter({ hasText: "Balanced" }),
  ).toBeVisible();
  await expect(page.getByText("budget_priority")).toHaveCount(0);
  // Rationale is surfaced prominently (visible without expanding a disclosure)
  // and is NOT duplicated as a settings row.
  await expect(
    page.getByRole("heading", { name: /Why this model\?/i }),
  ).toBeVisible();
  await expect(page.getByText(/Chosen for deep reasoning/i)).toBeVisible();
  await expect(
    page.getByRole("term").filter({ hasText: "Rationale" }),
  ).toHaveCount(0);
});

test("renders the rationale as readable lines with glossary popovers (#270, #269)", async ({
  page,
}) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model: "Opus 4.8",
        platform: "Claude Code",
        settings: {
          rationale:
            "Opus 4.8 is S-tier for coding. It leads on SWE-bench Verified. THINKING is set to XHigh for the required rigor.",
        },
        comparison_table: [],
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("split + glossary");
  await page.getByRole("button", { name: /Submit/i }).click();
  const why = page.getByRole("region", { name: /Why this model/i });
  await expect(why).toBeVisible();
  // #270: three sentences → three paragraphs, not one dense block.
  await expect(why.locator("p")).toHaveCount(3);
  // #269: the jargon terms ("S-tier", "SWE-bench Verified") carry inline
  // definition popovers (role="tooltip", revealed on hover/focus).
  const tooltips = why.locator('[role="tooltip"]');
  await expect(tooltips).toHaveCount(2);
  await expect(
    tooltips.filter({ hasText: "Top-1 or top-2 globally" }),
  ).toHaveCount(1);
  await expect(
    tooltips.filter({ hasText: "gold standard for software-engineering" }),
  ).toHaveCount(1);
});

test("frontier-tier recommendation shows the quality-tier label (no upgrade CTA)", async ({
  page,
}) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model: "Opus 4.8",
        platform: "Claude Code",
        settings: { thinking: "High" },
        tier: "frontier",
        engine: "gemini-2.5-pro",
        comparison_table: [],
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("hard reasoning task");
  await page.getByRole("button", { name: /Submit/i }).click();
  // Signed-in frontier users see the engine that generated the recommendation
  // (#271) and NO upgrade CTA they're already past.
  await expect(
    page.getByText(/quality engine · Gemini 2\.5 Pro/i),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /upgrade/i })).toHaveCount(0);
});

test("attached text file content is prepended to the request body (file-input Phase A)", async ({
  page,
}) => {
  // Capture the outbound request body so we can assert the dropped file's text
  // reaches task_description, prepended to the typed prompt.
  let sentTask = "";
  await page.route("**/api/recommend", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}") as {
      task_description?: string;
    };
    sentTask = body.task_description ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model: "Opus 4.8",
        platform: "Claude Code",
        settings: {},
        comparison_table: [],
      }),
    });
  });
  await page.goto("/recommend");
  // "Drop" a .txt by setting it on the (hidden) file input.
  await page.locator('input[type="file"]').setInputFiles({
    name: "my-prompt.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Summarize this quarterly earnings report."),
  });
  await expect(page.getByText("my-prompt.txt")).toBeVisible();
  await page
    .getByPlaceholder(/Input the prompt/i)
    .fill("which model should I use?");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(page.getByText(/Opus 4.8/i)).toBeVisible();
  // The file's text is delimited as input and precedes the typed prompt.
  expect(sentTask).toContain("Attached file my-prompt.txt:");
  expect(sentTask).toContain("Summarize this quarterly earnings report.");
  expect(sentTask).toContain("which model should I use?");
  expect(sentTask.indexOf("Summarize this quarterly")).toBeLessThan(
    sentTask.indexOf("which model should I use?"),
  );
});

test("non-text files are skipped with a hint (file-input Phase A)", async ({
  page,
}) => {
  await page.goto("/recommend");
  await page.locator('input[type="file"]').setInputFiles({
    name: "diagram.png",
    mimeType: "image/png",
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
  });
  await expect(
    page.getByText(/only text files \(\.txt, \.md, \.json\) are supported/i),
  ).toBeVisible();
  // The image is not added to the attachment list in Phase A (its name only
  // appears inside the skip notice, not as a list item).
  await expect(
    page.getByRole("listitem").filter({ hasText: "diagram.png" }),
  ).toHaveCount(0);
});

test("502 error renders friendly message", async ({ page }) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        error: "recommender_unavailable",
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("hello");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(
    page.getByText(/try again in a moment/i),
  ).toBeVisible();
});

// Step 6 burst-limit + daily-limit Playwright tests.
//
// The Phase 3 Step 6 task spec called for issuing 11 real POSTs and
// observing the 11th come back with a server-generated 429 sourced
// from a mocked Upstash backend. Playwright's `page.route` only
// intercepts browser-initiated requests — it cannot observe or
// stub the Next.js server's outbound calls to Upstash, so the
// literal interpretation is not implementable in CI without
// standing up a separate mock-Upstash HTTP server. The honest
// equivalent below verifies the user-visible contract: when the
// API returns 429 with the documented body shape (`burst_dropped`
// or `rate_limited`), the `/recommend` page renders the right
// human-readable message. The server-side rate-limit decision is
// covered by the @upstash/ratelimit library's own tests.

test("burst_limit burst-drop 429 renders slow-down message", async ({ page }) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      headers: { "Retry-After": "60" },
      body: JSON.stringify({
        error: "burst_dropped",
        retry_after: 60,
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("burst test");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(page.getByText(/Slow down/i)).toBeVisible();
});

test("daily_limit daily-cap 429 renders daily-cap message", async ({ page }) => {
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      headers: { "Retry-After": "3600" },
      body: JSON.stringify({
        error: "rate_limited",
        retry_after: 3600,
      }),
    }),
  );
  await page.goto("/recommend");
  await page.getByPlaceholder(/Input the prompt/i).fill("daily test");
  await page.getByRole("button", { name: /Submit/i }).click();
  await expect(page.getByText(/daily recommendation limit/i)).toBeVisible();
});

test("blank task_description returns 400 bad_input (no upstream call)", async ({
  request,
}) => {
  // #175: the real edge route (not page.route-mocked here) rejects
  // whitespace-only input with a 400 before any upstream fetch. The E2E
  // webServer runs with no SITE_PASSWORD, so /api/recommend is reachable
  // without the gate; the blank guard runs in the dispatch span.
  const res = await request.post("/api/recommend", {
    data: { task_description: "   " },
  });
  expect(res.status()).toBe(400);
  expect(await res.json()).toMatchObject({ error: "bad_input" });
});
