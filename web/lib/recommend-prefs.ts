// web/lib/recommend-prefs.ts
//
// The engine a visitor last chose on /recommend, kept in a first-party cookie
// so the page opens on it. A cookie rather than localStorage for the same
// reason as /models (lib/models-prefs.ts): the server reads it, so the first
// render already shows the visitor's engine, with no flash of the default.
// The cookie holds only the engine hint, scoped to /recommend.
//
// The value is untrusted input: the page resolves it against the menu and the
// visitor's access, and falls back to the default engine otherwise.

export const RECOMMEND_PREFS_COOKIE = "roadmodel_recommend_engine";
const PREFS_PATH = "/recommend";
const ONE_YEAR = 60 * 60 * 24 * 365;

export function parseEnginePref(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const value = raw.startsWith("%") ? decodeURIComponent(raw) : raw;
  return /^[a-z0-9.-]{3,64}$/.test(value) ? value : null;
}

// Client only. A browser that blocks cookies still gets a working page; it
// just forgets the choice.
export function saveEnginePref(hint: string): void {
  try {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${RECOMMEND_PREFS_COOKIE}=${encodeURIComponent(hint)}; Path=${PREFS_PATH}; Max-Age=${ONE_YEAR}; SameSite=Lax${secure}`;
  } catch {
    // Cookies unavailable.
  }
}
