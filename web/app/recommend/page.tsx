// web/app/recommend/page.tsx
import { Loader2 } from "lucide-react";

export default function RecommendPlaceholderPage() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6">
      <div className="max-w-md rounded-xl border border-brand-slate-200 bg-white p-10 text-center shadow-sm">
        <Loader2
          className="mx-auto h-8 w-8 animate-spin text-brand-accent"
          aria-hidden="true"
        />
        <h1 className="mt-4 text-xl font-semibold text-brand-slate-900">
          Coming in the next deploy
        </h1>
        <p className="mt-2 text-sm text-brand-slate-600">
          The full recommendation experience ships in Phase 3 Step 5.
        </p>
      </div>
    </div>
  );
}
