// web/lib/openrouter-connect.ts
//
// "Connect OpenRouter": the OAuth PKCE flow that lets a visitor pay for their
// recommendations with OpenRouter credits, with no key to copy. OpenRouter's
// PKCE docs (2026-10-04): https://openrouter.ai/docs/use-cases/oauth-pkce
//
//   1. startOpenRouterConnect() makes a random code_verifier and its S256
//      code_challenge, keeps the verifier in sessionStorage under one key (it
//      must outlive the trip to openrouter.ai and back), and sends the browser
//      to OpenRouter's authorization page with callback_url this site's
//      /recommend/openrouter.
//   2. OpenRouter returns the visitor there with ?code=. The callback page
//      (app/recommend/openrouter/page.tsx) clears the code from the address
//      bar, takes the verifier out of storage (takeVerifier deletes it), and
//      posts both to /api/openrouter/exchange.
//   3. That route trades them for a key at OPENROUTER_KEYS_URL and returns it
//      once; the page hands it to /recommend's in-memory key holder
//      (lib/use-visitor-key.ts) as an OpenRouter key.
//
// Client-safe: the exchange route imports the endpoint constant from here.

export const OPENROUTER_AUTH_URL = "https://openrouter.ai/auth";
export const OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys";
export const OPENROUTER_CALLBACK_PATH = "/recommend/openrouter";
export const OPENROUTER_EXCHANGE_PATH = "/api/openrouter/exchange";
export const VERIFIER_STORAGE_KEY = "roadmodel:openrouter-pkce-verifier";
// The label OpenRouter prefills for the key it creates.
const KEY_LABEL = "roadmodel";

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// 48 random bytes from crypto.getRandomValues: a 64-character verifier, inside
// RFC 7636's 43-to-128.
export function createVerifier(): string {
  return base64url(crypto.getRandomValues(new Uint8Array(48)));
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

// The callback is this origin's: roadmodel.ai in production, the preview's
// own URL on a preview, localhost in development.
export function authorizationUrl(origin: string, challenge: string): string {
  const url = new URL(OPENROUTER_AUTH_URL);
  url.searchParams.set("callback_url", `${origin}${OPENROUTER_CALLBACK_PATH}`);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("key_label", KEY_LABEL);
  return url.toString();
}

export async function startOpenRouterConnect(): Promise<void> {
  const verifier = createVerifier();
  const challenge = await challengeFor(verifier);
  window.sessionStorage.setItem(VERIFIER_STORAGE_KEY, verifier);
  window.location.assign(authorizationUrl(window.location.origin, challenge));
}

// The stored verifier, deleted as it is read, so it is used at most once.
export function takeVerifier(): string | null {
  try {
    const verifier = window.sessionStorage.getItem(VERIFIER_STORAGE_KEY);
    window.sessionStorage.removeItem(VERIFIER_STORAGE_KEY);
    return verifier;
  } catch {
    return null;
  }
}
