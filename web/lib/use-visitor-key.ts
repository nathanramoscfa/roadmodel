// web/lib/use-visitor-key.ts
//
// The visitor's own API key on /recommend, held in React state and nowhere
// else: never a cookie, localStorage, sessionStorage, the recent-
// recommendations store or the engine-prefs cookie. RecommendWorkspace owns
// one holder and shares it with the composer (where the key is typed) and the
// result's "Run again" (which reuses it), so a reload or a closed tab forgets
// it, and "Forget key" clears it at once. The key leaves the page only as the
// X-Roadmodel-Visitor-Key header of a /api/recommend request (headersFor).
//
// "Connect OpenRouter" returns a key on another page (/recommend/openrouter).
// That page hands it over in module memory (handOffVisitorKey) and moves to
// /recommend by client-side navigation, which keeps this module alive, and
// RecommendWorkspace takes it on mount (takeVisitorKeyHandoff). The handoff
// is held for that one navigation and cleared as it is read.
"use client";

import { useCallback, useMemo, useState } from "react";

import {
  VISITOR_KEY_HEADER,
  VISITOR_PROVIDER_HEADER,
  visitorKeyLooksValid,
  type VisitorProvider,
} from "./visitor-key";

export interface VisitorKey {
  provider: VisitorProvider;
  key: string;
  setProvider: (provider: VisitorProvider) => void;
  setKey: (key: string) => void;
  forget: () => void;
  // A key has been entered (whether or not it looks right).
  active: boolean;
  // The entered key has its provider's shape (lib/visitor-key.ts).
  valid: boolean;
  // The two headers that carry the key on a request, or none without one.
  headersFor: () => Record<string, string>;
}

export function useVisitorKey(initialProvider: VisitorProvider = "openai"): VisitorKey {
  const [provider, setProvider] = useState<VisitorProvider>(initialProvider);
  const [key, setKey] = useState("");
  const trimmed = key.trim();
  const active = trimmed.length > 0;
  const valid = active && visitorKeyLooksValid(provider, trimmed);
  const forget = useCallback(() => setKey(""), []);
  const headersFor = useCallback(
    (): Record<string, string> =>
      active ? { [VISITOR_KEY_HEADER]: trimmed, [VISITOR_PROVIDER_HEADER]: provider } : {},
    [active, trimmed, provider],
  );
  return useMemo(
    () => ({ provider, key, setProvider, setKey, forget, active, valid, headersFor }),
    [provider, key, forget, active, valid, headersFor],
  );
}

// The key a connect flow returned, waiting for /recommend to take it.
let handoff: { provider: VisitorProvider; key: string } | null = null;

export function handOffVisitorKey(provider: VisitorProvider, key: string): void {
  handoff = { provider, key };
}

// The waiting key, once: reading it clears it.
export function takeVisitorKeyHandoff(): { provider: VisitorProvider; key: string } | null {
  const taken = handoff;
  handoff = null;
  return taken;
}
