// web/components/ExportPanel.tsx
"use client";

// Phase 4 Step 5 — "Looks good — export" affordance + Markdown
// download panel. Wired to /api/roadmaps/[id]/export which streams
// a Content-Disposition: attachment response so the browser
// triggers a download from the anchor click without extra JS.
// Phase 6 will add HTML / PDF / DOCX options to the same panel.

interface ExportPanelProps {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  roadmapId: string;
}

export function ExportPanel({ open, onOpen, onClose, roadmapId }: ExportPanelProps) {
  const href = `/api/roadmaps/${roadmapId}/export`;
  return (
    <div className="mt-8 flex flex-col gap-4 border-t border-brand-slate-200 pt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-brand-slate-600">
          Happy with the draft? Save a copy or share it with your team.
        </p>
        <button
          type="button"
          onClick={open ? onClose : onOpen}
          aria-expanded={open}
          className={
            "inline-flex items-center justify-center rounded-md border " +
            "border-brand-accent bg-brand-accent px-4 py-2 text-sm " +
            "font-medium text-white shadow-sm hover:bg-brand-accent/90"
          }
        >
          {open ? "Hide export options" : "Looks good — export"}
        </button>
      </div>
      {open ? (
        <div
          data-testid="export-panel"
          className={
            "rounded-lg border border-brand-slate-200 bg-white p-4 shadow-sm"
          }
        >
          <h3 className="text-sm font-semibold uppercase tracking-wide text-brand-slate-500">
            Export options
          </h3>
          <ul className="mt-3 space-y-2 text-sm">
            <li>
              <a
                href={href}
                download
                data-testid="export-markdown"
                className={
                  "inline-flex items-center gap-2 rounded-md border " +
                  "border-brand-slate-300 px-3 py-2 font-medium text-brand-slate-900 " +
                  "hover:border-brand-accent hover:text-brand-accent"
                }
              >
                Download as Markdown
              </a>
            </li>
            <li className="text-xs text-brand-slate-500">
              HTML, PDF, and DOCX exports arrive in Phase 6.
            </li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}
