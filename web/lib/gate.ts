// web/lib/gate.ts
//
// Pre-launch site gate. While roadmodel.ai is publicly resolvable but
// not publicly launched (see project memory `project_site_pre_launch_gate`),
// every route except /api/gate and the gate page itself is fronted by a
// password prompt. The gate is OFF when SITE_PASSWORD is unset, so the
// codepath can ship and seed independently.

export const GATE_COOKIE = "roadmodel_gate";

/**
 * Derive a constant-per-password token for the gate cookie. We never
 * store the raw shared password in the cookie — instead we store
 * sha256("roadmodel-gate-v1:" + password) so a stolen cookie does not
 * leak the password itself. Same input always produces the same hash,
 * so middleware can verify by re-deriving.
 */
export async function deriveGateToken(password: string): Promise<string> {
  const data = new TextEncoder().encode(`roadmodel-gate-v1:${password}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
