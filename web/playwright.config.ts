// web/playwright.config.ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_SITE_URL: "http://localhost:3000",
      SUPABASE_URL: "https://ci-placeholder.supabase.co",
      SUPABASE_SERVICE_ROLE_KEY: "ci-placeholder-service-role-key",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "ci-placeholder-anon-key",
      UPSTASH_REDIS_URL: "https://ci-placeholder.upstash.io",
      UPSTASH_REDIS_TOKEN: "ci-placeholder-redis-token",
      ROADMODEL_IP_SALT: "ci-placeholder-ip-salt",
      ROADMODEL_E2E_AUTH: "1",
      ROADMODEL_E2E_MOCK_RECOMMEND: "1",
    },
  },
});
