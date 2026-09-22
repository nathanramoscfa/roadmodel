// web/playwright.config.ts
import { readFileSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The placeholder build/test environment, read from the SAME file CI reads
// (web/.env.ci). These values used to be duplicated here and in
// .github/workflows/tests.yml, so a plain local `npm run build` got neither
// and failed with env.ts's `.min(1)` validation surfacing as the opaque
// "Failed to collect page data for /api/roadmap" — green in CI, red locally
// (issue #655). Add a variable once, in .env.ci.
function ciEnv(): Record<string, string> {
  const text = readFileSync(path.join(__dirname, ".env.ci"), "utf8");
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return out;
}

// Local override for when something else already owns :3000. CI leaves it
// unset. See the reuseExistingServer note below for why a stranger on the
// port is now a loud failure instead of a silent wrong answer.
const PORT = process.env.PLAYWRIGHT_PORT ?? "3000";
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `npm run start -- --port ${PORT}`,
    url: BASE_URL,
    // NEVER reuse. The specs only work against a server started with the
    // test-harness switches below (ROADMODEL_E2E_AUTH, the recommend mock),
    // and Playwright cannot tell whether whatever is answering on the port
    // was started with them.
    //
    // Reusing was silently adopting any listener. An unrelated Python process
    // on :3000 was enough to make signInViaCallback land on
    // /auth?redirect=… instead of /onboarding — every signed-in spec failing
    // with an auth redirect that looks like an app bug and is not one, while
    // CI (clean runner, nothing on the port) stayed green. That is issue #655.
    //
    // Now the server is always ours. If the port is taken, `next start` fails
    // with EADDRINUSE — set PLAYWRIGHT_PORT to a free port.
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ...ciEnv(),
      // Local devs who ran `vercel env pull` carry VERCEL=1 in
      // web/.env.local; that flag flips isE2eAuthEnabled() to
      // false, disabling the cookie-driven E2E bypass and making
      // every signed-in test fail with a login redirect. Override
      // to empty here so the local test webServer matches CI
      // (where no .env.local exists and VERCEL is unset).
      VERCEL: "",
      // Both must point at THIS server, not .env.ci's staging URL: the
      // second is where /api/recommend finds the E2E mock (it defaults
      // to :3000 in code, which is wrong under PLAYWRIGHT_PORT).
      NEXT_PUBLIC_SITE_URL: BASE_URL,
      ROADMODEL_E2E_SITE_URL: BASE_URL,
      // Test-harness switches: they belong to the Playwright run, not to
      // a build, so they stay here rather than in the shared env file.
      ROADMODEL_E2E_AUTH: "1",
      ROADMODEL_E2E_MOCK_RECOMMEND: "1",
    },
  },
});
