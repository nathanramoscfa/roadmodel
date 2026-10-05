// web/lib/engine-format.ts
//
// Client-safe formatting for engine figures (no server imports), shared by
// the engine menu and the result's engine line.

import type { EngineAccess, EnginePayer } from "./recommend-engines";

// A recommendation costs fractions of a cent to a few cents, so cents read
// better than dollars: 0.15¢, 2.7¢, 26¢.
export function cents(usd: number): string {
  const c = usd * 100;
  if (c < 0.995) return `${c.toFixed(2)}¢`;
  if (c < 9.95) return `${c.toFixed(1)}¢`;
  return `${Math.round(c)}¢`;
}

// A dollar figure for one recommendation, to two significant figures:
// $0.0015, $0.027, $0.067.
export function dollars(usd: number): string {
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  return `$${Number(usd.toPrecision(2))}`;
}

export function seconds(s: number): string {
  return s < 9.95 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`;
}

export const ACCESS_LABEL: Record<EngineAccess, string> = {
  invited: "Invited members",
  founder: "Operator only",
};

// Why a locked engine is locked, in the menu's words.
export function lockReason(access: EngineAccess, signedIn: boolean, evaluated: boolean): string {
  if (!evaluated) return "Awaiting evaluation";
  if (access === "invited") return signedIn ? "Invited members" : "Invited members · sign in";
  return "Operator only";
}

// Who pays for a recommendation, in the menu's words: roadmodel's account on
// the operator lane, the visitor's own key on the visitor lane.
export function costNote(payer: EnginePayer): string {
  return payer === "visitor"
    ? "What one recommendation costs at this engine's API price, measured on the engine eval, billed to your key"
    : "What one recommendation costs roadmodel at this engine's API price, with the prompt cached (cold, about 4× more)";
}

// The menu line for one engine's cost.
export function costLine(payer: EnginePayer, usd: number): string {
  return payer === "visitor"
    ? `≈ ${dollars(usd)} per recommendation, billed to your key`
    : `${cents(usd)} each`;
}

// The result's note on what its run cost and who paid it.
export function runCostNote(payer: EnginePayer, measured: boolean): string {
  if (!measured) return "Estimated from the prompt size; the provider reported no usage";
  return payer === "visitor"
    ? "What this run cost your key, from the provider's reported usage"
    : "What this run cost roadmodel, from the provider's reported usage";
}
