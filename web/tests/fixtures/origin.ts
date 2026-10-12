export const TEST_ORIGIN = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? "3000"}`;
export const ORIGIN_HEADERS = { Origin: TEST_ORIGIN };
