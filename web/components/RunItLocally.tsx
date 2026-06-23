// web/components/RunItLocally.tsx
//
// The same recommender, open-source, for the developer audience this preview is
// shared with. Replaces the old "Pricing / Pro Hosted coming soon" teaser:
// there is no paid tier to sell here, but there is a real CLI + MCP server.
import Link from "next/link";
import { ArrowUpRight, Terminal } from "lucide-react";

const GITHUB_URL = "https://github.com/nathanramoscfa/roadmodel";
const PYPI_URL = "https://pypi.org/project/roadmodel/";

export function RunItLocally() {
  return (
    <section className="border-t border-brand-slate-200 bg-white py-20 dark:border-brand-slate-700 dark:bg-brand-slate-800">
      <div className="mx-auto max-w-4xl px-6">
        <div className="flex flex-col items-start gap-2">
          <span className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-brand-accent">
            <Terminal className="h-4 w-4" aria-hidden="true" />
            Open source
          </span>
          <h2 className="text-3xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
            Run it yourself
          </h2>
        </div>
        <p className="mt-3 max-w-2xl text-brand-slate-600 dark:text-brand-slate-300">
          roadmodel is also an Apache-2.0 CLI and MCP server — the same
          recommender, in your terminal or wired into your agent. Bring your own
          Anthropic, OpenAI, or Google key.
        </p>

        <pre className="mt-6 overflow-x-auto rounded-xl border border-brand-slate-200 bg-brand-slate-900 p-5 text-sm leading-relaxed text-brand-slate-100 dark:border-brand-slate-700">
          <code>
            <span className="select-none text-brand-slate-500">$ </span>pip
            install roadmodel{"\n"}
            <span className="select-none text-brand-slate-500">$ </span>roadmodel
            recommend{" "}
            <span className="text-emerald-300">
              &quot;Refactor auth middleware across 12 files&quot;
            </span>
          </code>
        </pre>

        <p className="mt-4 text-sm text-brand-slate-600 dark:text-brand-slate-300">
          Wiring an agent instead? Install{" "}
          <code className="rounded bg-brand-slate-100 px-1.5 py-0.5 text-xs text-brand-slate-800 dark:bg-brand-slate-900 dark:text-brand-slate-100">
            roadmodel[mcp]
          </code>{" "}
          for the{" "}
          <code className="rounded bg-brand-slate-100 px-1.5 py-0.5 text-xs text-brand-slate-800 dark:bg-brand-slate-900 dark:text-brand-slate-100">
            roadmodel-mcp
          </code>{" "}
          stdio server and call it from Claude Code or any MCP client.
        </p>

        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-slate-300 px-4 py-2 text-sm font-medium text-brand-slate-800 transition hover:border-brand-slate-400 dark:border-brand-slate-600 dark:text-brand-slate-100 dark:hover:border-brand-slate-500"
          >
            GitHub
            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link
            href={PYPI_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-slate-300 px-4 py-2 text-sm font-medium text-brand-slate-800 transition hover:border-brand-slate-400 dark:border-brand-slate-600 dark:text-brand-slate-100 dark:hover:border-brand-slate-500"
          >
            PyPI
            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </section>
  );
}
