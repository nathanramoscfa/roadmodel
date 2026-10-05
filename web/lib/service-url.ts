// web/lib/service-url.ts
//
// Where the edge reaches the recommender service. ROADMODEL_RECOMMEND_URL
// names its /v1/recommend endpoint; the other endpoints sit on the same host.
// In E2E mock mode every endpoint is the mock under /api/test/mock-recommend
// on this site, at the same suffix.

import { isE2eAuthEnabled } from "./e2e-mode";

const DEFAULT_RECOMMENDER_URL = "https://roadmodel-api.vercel.app/v1/recommend";

export function isE2eMockRecommend(): boolean {
  return isE2eAuthEnabled() && process.env.ROADMODEL_E2E_MOCK_RECOMMEND === "1";
}

export function recommenderUrl(): string {
  if (isE2eMockRecommend()) {
    const site = process.env.ROADMODEL_E2E_SITE_URL ?? "http://127.0.0.1:3000";
    return new URL("/api/test/mock-recommend", site).toString();
  }
  return process.env.ROADMODEL_RECOMMEND_URL ?? DEFAULT_RECOMMENDER_URL;
}

// The keyless picks endpoint (service/app/score.py): POST /v1/score.
export function scoreUrl(): string {
  if (isE2eMockRecommend()) return `${recommenderUrl()}/score`;
  return new URL("/v1/score", recommenderUrl()).toString();
}
