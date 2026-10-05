// web/components/OpenRouterCallback.tsx
//
// The browser half of the OpenRouter PKCE callback. On arrival it:
//   1. reads `code` from the URL and replaces the history entry at once, so
//      the code stays out of the address bar and the back history;
//   2. takes the PKCE verifier out of sessionStorage (deleting it, whatever
//      happens next);
//   3. posts both to /api/openrouter/exchange, which returns the key once;
//   4. hands the key to /recommend's in-memory holder (lib/use-visitor-key.ts)
//      and moves there by client-side navigation. The key is never written to
//      any browser storage.
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  OPENROUTER_CALLBACK_PATH,
  OPENROUTER_EXCHANGE_PATH,
  takeVerifier,
} from "@/lib/openrouter-connect";
import { handOffVisitorKey } from "@/lib/use-visitor-key";
import { visitorKeyLooksValid } from "@/lib/visitor-key";

const NOT_CONNECTED =
  "OpenRouter did not connect this time. Go back to Recommend and choose Connect OpenRouter again, or paste an OpenRouter key.";

export function OpenRouterCallback() {
  const router = useRouter();
  const started = useRef(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    // Once per arrival (React runs effects twice in development).
    if (started.current) return;
    started.current = true;
    const code = new URLSearchParams(window.location.search).get("code");
    window.history.replaceState(null, "", OPENROUTER_CALLBACK_PATH);
    const verifier = takeVerifier();
    if (!code || !verifier) {
      setFailed(true);
      return;
    }
    void (async () => {
      try {
        const res = await fetch(OPENROUTER_EXCHANGE_PATH, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, code_verifier: verifier }),
          cache: "no-store",
        });
        const body = (await res.json().catch(() => ({}))) as { key?: unknown };
        const key = typeof body.key === "string" ? body.key : "";
        if (!res.ok || !visitorKeyLooksValid("openrouter", key)) {
          setFailed(true);
          return;
        }
        handOffVisitorKey("openrouter", key);
        router.replace("/recommend");
      } catch {
        setFailed(true);
      }
    })();
  }, [router]);

  if (failed) {
    return (
      <div role="alert" data-testid="openrouter-callback-error">
        <p className="text-brand-slate-700 dark:text-brand-slate-200">{NOT_CONNECTED}</p>
        <Link
          href="/recommend"
          className="mt-4 inline-block font-semibold text-brand-accent hover:underline"
          data-testid="openrouter-callback-back"
        >
          Back to Recommend
        </Link>
      </div>
    );
  }
  return (
    <p className="text-brand-slate-600 dark:text-brand-slate-300" role="status" data-testid="openrouter-callback-pending">
      Connecting your OpenRouter account&hellip;
    </p>
  );
}
