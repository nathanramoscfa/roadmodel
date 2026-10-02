// web/lib/engine-format.ts
//
// Client-safe formatting for engine figures (no server imports), shared by
// the engine menu and the result's engine line.

import type { EngineAccess } from "./recommend-engines";

// A recommendation costs fractions of a cent to a few cents, so cents read
// better than dollars: 0.15¢, 2.7¢, 26¢.
export function cents(usd: number): string {
  const c = usd * 100;
  if (c < 0.995) return `${c.toFixed(2)}¢`;
  if (c < 9.95) return `${c.toFixed(1)}¢`;
  return `${Math.round(c)}¢`;
}

export function seconds(s: number): string {
  return s < 9.95 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`;
}

export const ACCESS_LABEL: Record<EngineAccess, string> = {
  public: "Everyone",
  signed_in: "Signed-in accounts",
  founder: "Operator only",
};

// Why a locked engine is locked, in the menu's words.
export function lockReason(access: EngineAccess, signedIn: boolean, evaluated: boolean): string {
  if (!evaluated) return "Awaiting evaluation";
  if (access === "signed_in") return "Sign in to use";
  return signedIn ? "Operator only" : "Operator only · sign in";
}
