// web/components/OwnAgentPanel.tsx
//
// "Run it in your own agent": the two commands that install roadmodel's MCP
// server and register it with Claude Code, and the setup guide (which covers
// Cursor, Claude Desktop and the other MCP clients). Commands only: the panel
// carries no key, token or value of the viewer's.
"use client";

import { Check, Copy, Terminal } from "lucide-react";
import { useState } from "react";

const MCP_SETUP_URL = "https://github.com/nathanramoscfa/roadmodel/blob/main/docs/mcp-setup.md";

export const OWN_AGENT_COMMANDS = ['pip install "roadmodel[mcp]"', "roadmodel setup-mcp"] as const;

function CommandBlock({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-brand-slate-200 bg-brand-slate-50 py-1.5 pl-3 pr-1.5 dark:border-brand-slate-700 dark:bg-brand-slate-900">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-sm text-brand-slate-800 dark:text-brand-slate-100" data-testid="own-agent-command">
        {command}
      </code>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard
            ?.writeText(command)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => {});
        }}
        aria-label={`Copy ${command}`}
        className="flex-none rounded-md p-1.5 text-brand-slate-500 transition hover:bg-brand-slate-200 hover:text-brand-slate-800 dark:hover:bg-brand-slate-700 dark:hover:text-brand-slate-100"
      >
        {copied ? <Check className="h-4 w-4 text-brand-accent" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
      </button>
    </div>
  );
}

export function OwnAgentPanel() {
  return (
    <section
      aria-labelledby="own-agent-heading"
      className="space-y-3 rounded-xl border border-brand-slate-200 bg-white px-4 py-4 shadow-sm dark:border-brand-slate-700 dark:bg-brand-slate-800"
      data-testid="own-agent-panel"
    >
      <h2 id="own-agent-heading" className="flex items-center gap-2 text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
        <Terminal className="h-4 w-4 text-brand-accent" aria-hidden />
        Run it in your own agent
      </h2>
      <p className="text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
        roadmodel&rsquo;s MCP server gives your coding agent (Claude Code, Codex, Cursor and others) the same
        recommender, catalog and scoring this page uses. It runs on your machine with the API keys you already
        have. Install it, then register it with Claude Code; the setup guide covers Cursor, Claude Desktop and
        the other MCP clients.
      </p>
      <div className="space-y-2">
        {OWN_AGENT_COMMANDS.map((c) => (
          <CommandBlock key={c} command={c} />
        ))}
      </div>
      <a
        href={MCP_SETUP_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block text-sm font-medium text-brand-accent hover:underline"
        data-testid="own-agent-guide"
      >
        The MCP setup guide &rarr;
      </a>
    </section>
  );
}
