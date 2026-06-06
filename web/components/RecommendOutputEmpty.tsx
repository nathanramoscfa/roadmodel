// web/components/RecommendOutputEmpty.tsx
import { Sparkles } from "lucide-react";

export function RecommendOutputEmpty() {
  return (
    <div
      className={
        "flex min-h-[320px] flex-col items-center justify-center " +
        "rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 bg-brand-slate-100 dark:bg-brand-slate-800/60 " +
        "px-6 py-12 text-center"
      }
    >
      <Sparkles
        className="h-10 w-10 text-brand-slate-400"
        aria-hidden="true"
      />
      <p className="mt-4 text-sm text-brand-slate-500 dark:text-brand-slate-400">
        Your recommendation will appear here
      </p>
    </div>
  );
}
