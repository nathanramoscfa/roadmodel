// web/tests/fixtures/onboarding-auth.ts
import type { Page } from "@playwright/test";

export const E2E_AUTH_COOKIE = "rm-e2e-uid";
export const E2E_USER_ID = "00000000-0000-4000-8000-000000000001";

export async function clearE2eSession(page: Page): Promise<void> {
  await page.context().clearCookies();
}

export async function resetE2eState(page: Page): Promise<void> {
  await page.request.post("/api/test/e2e-reset");
  await clearE2eSession(page);
}

export async function signInViaCallback(
  page: Page,
  next: string = "/",
): Promise<void> {
  const nextParam = encodeURIComponent(next);
  await page.goto(`/callback?code=e2e-test-code&next=${nextParam}`);
}

export async function setE2eSessionCookie(page: Page): Promise<void> {
  await page.context().addCookies([
    {
      name: E2E_AUTH_COOKIE,
      value: E2E_USER_ID,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}
