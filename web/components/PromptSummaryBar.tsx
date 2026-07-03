// web/components/PromptSummaryBar.tsx
"use client";

interface PromptSummaryBarProps {
  task: string;
  onEdit: () => void;
}

// After a recommendation lands, the tall prompt form collapses to this one-line
// summary so the picks sit near the top of the viewport (the redesign's
// fit-on-screen goal). "Edit" restores the full form.
export function PromptSummaryBar({ task, onEdit }: PromptSummaryBarProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-brand-slate-200 dark:border-brand-slate-700 bg-white dark:bg-brand-slate-800 px-4 py-2.5 shadow-sm">
      <span className="whitespace-nowrap text-[11px] font-semibold uppercase tracking-wide text-brand-slate-400 dark:text-brand-slate-500">
        Your prompt
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-brand-slate-700 dark:text-brand-slate-200">
        {task || "—"}
      </span>
      <button
        type="button"
        onClick={onEdit}
        className="whitespace-nowrap rounded-md border border-brand-slate-300 px-3 py-1.5 text-xs font-semibold text-brand-slate-600 hover:border-brand-accent hover:text-brand-accent dark:border-brand-slate-600 dark:text-brand-slate-300"
      >
        Edit
      </button>
    </div>
  );
}
