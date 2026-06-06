// web/components/RecommendOutput.tsx
import type { RecommendResponse } from "@/lib/api";
import { CostComparison } from "./CostComparison";
import { FreeTierLabel } from "./FreeTierLabel";
import { ModelHeader } from "./ModelHeader";
import { SettingsList } from "./SettingsList";
import { WhyDisclosure } from "./WhyDisclosure";

interface RecommendOutputProps {
  data: RecommendResponse;
}

function extractRationale(data: RecommendResponse): string | null {
  const fromSettings = data.settings.rationale;
  if (typeof fromSettings === "string" && fromSettings.trim()) {
    return fromSettings;
  }
  const first = data.comparison_table[0];
  if (first && typeof first.rationale === "string") {
    return first.rationale;
  }
  return null;
}

export function RecommendOutput({ data }: RecommendOutputProps) {
  const rationale = extractRationale(data);

  return (
    <div
      className={
        "flex flex-col gap-6 rounded-xl border border-brand-slate-200 dark:border-brand-slate-700 " +
        "bg-white dark:bg-brand-slate-800 p-6 shadow-sm"
      }
    >
      <ModelHeader model={data.model} platform={data.platform} />
      <SettingsList settings={data.settings} />
      <CostComparison comparisonTable={data.comparison_table} />
      <WhyDisclosure rationale={rationale} />
      <FreeTierLabel surface="recommend" tier={data.tier} engine={data.engine} />
    </div>
  );
}
