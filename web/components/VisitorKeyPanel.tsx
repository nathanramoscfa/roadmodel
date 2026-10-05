// web/components/VisitorKeyPanel.tsx
//
// "Use your own API key" on /recommend: the provider, the key, and "Forget
// key". The key pays for the visitor's own recommendations at their
// provider's price. It is held in the page's memory only (lib/use-visitor-key.ts)
// and sent as one request header per recommendation. The field sits outside
// the composer's <form>, so a browser's password manager has no form
// submission to offer to save it from.
//
// "Connect OpenRouter" is the way in with no key to copy: an OAuth PKCE round
// trip to openrouter.ai (lib/openrouter-connect.ts) that comes back with an
// OpenRouter key in the same holder.
"use client";

import Link from "next/link";
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { startOpenRouterConnect } from "@/lib/openrouter-connect";
import type { VisitorKey } from "@/lib/use-visitor-key";
import {
  isVisitorProvider,
  KEY_PREFIX_HINT,
  PROVIDER_LABEL,
  VISITOR_PROVIDERS,
} from "@/lib/visitor-key";

export function VisitorKeyPanel({ visitor, disabled = false }: { visitor: VisitorKey; disabled?: boolean }) {
  const label = PROVIDER_LABEL[visitor.provider];
  const [connecting, setConnecting] = useState(false);
  const [connectFailed, setConnectFailed] = useState(false);

  async function connect() {
    setConnecting(true);
    setConnectFailed(false);
    try {
      await startOpenRouterConnect();
    } catch {
      setConnecting(false);
      setConnectFailed(true);
    }
  }

  return (
    <div
      id="visitor-key-panel"
      className="rounded-xl border border-brand-slate-200 bg-white px-4 py-3 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
      data-testid="visitor-key-panel"
    >
      <p className="flex items-center gap-2 text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
        <KeyRound className="h-4 w-4 text-brand-accent" aria-hidden />
        Use your own API key
      </p>
      <p className="mt-1 text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
        Your key pays for your recommendations at your provider&rsquo;s price. It travels with each
        request you make here, is used for that one call, then discarded; this page keeps it in memory
        until you forget it or close the tab.{" "}
        <Link href="/privacy" className="font-medium text-brand-accent hover:underline">
          Privacy
        </Link>
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <label htmlFor="visitor-key-provider" className="sr-only">
          Provider
        </label>
        <select
          id="visitor-key-provider"
          value={visitor.provider}
          disabled={disabled}
          onChange={(e) => {
            if (isVisitorProvider(e.target.value)) visitor.setProvider(e.target.value);
          }}
          className="rounded-lg border border-brand-slate-300 bg-white px-2.5 py-2 text-sm text-brand-slate-800 focus:border-brand-accent focus:outline-none focus:ring-2 focus:ring-brand-accent/30 dark:border-brand-slate-600 dark:bg-brand-slate-900 dark:text-brand-slate-100"
          data-testid="visitor-key-provider"
        >
          {VISITOR_PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABEL[p]}
            </option>
          ))}
        </select>
        <label htmlFor="visitor-key-input" className="sr-only">
          {label} API key
        </label>
        <input
          id="visitor-key-input"
          type="password"
          autoComplete="off"
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          data-1p-ignore
          data-lpignore="true"
          value={visitor.key}
          disabled={disabled}
          onChange={(e) => visitor.setKey(e.target.value)}
          placeholder={`${KEY_PREFIX_HINT[visitor.provider]}…`}
          className="min-w-0 flex-1 rounded-lg border border-brand-slate-300 bg-white px-3 py-2 font-mono text-sm text-brand-slate-900 placeholder:text-brand-slate-400 focus:border-brand-accent focus:outline-none focus:ring-2 focus:ring-brand-accent/30 dark:border-brand-slate-600 dark:bg-brand-slate-900 dark:text-brand-slate-50"
          data-testid="visitor-key-input"
        />
        <button
          type="button"
          onClick={visitor.forget}
          disabled={!visitor.active}
          className="rounded-lg border border-brand-slate-300 px-3 py-2 text-sm font-semibold text-brand-slate-700 transition hover:border-brand-accent hover:text-brand-accent disabled:opacity-50 dark:border-brand-slate-600 dark:text-brand-slate-200"
          data-testid="visitor-key-forget"
        >
          Forget key
        </button>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          type="button"
          onClick={() => void connect()}
          disabled={disabled || connecting}
          className="rounded-lg border border-brand-accent px-3 py-2 text-sm font-semibold text-brand-accent transition hover:bg-brand-accent/10 disabled:opacity-50"
          data-testid="openrouter-connect"
        >
          {connecting ? "Opening OpenRouter…" : "Connect OpenRouter"}
        </button>
        <p className="min-w-0 flex-1 text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          OpenRouter is a prepaid account that pays for many AI models; connecting it lets roadmodel bill your
          recommendations to your OpenRouter credits.
        </p>
      </div>
      {connectFailed && (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-300" role="status" data-testid="openrouter-connect-failed">
          This browser could not start the OpenRouter connection. Paste an OpenRouter key instead.
        </p>
      )}
      {visitor.active && !visitor.valid && (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-300" role="status" data-testid="visitor-key-shape">
          {label} API keys begin with {KEY_PREFIX_HINT[visitor.provider]}. Paste the whole key.
        </p>
      )}
      {visitor.active && visitor.valid && (
        <p className="mt-2 text-xs text-brand-slate-500 dark:text-brand-slate-400" role="status">
          Recommendations now run on your {label} key, with the engines it can run.
        </p>
      )}
    </div>
  );
}
