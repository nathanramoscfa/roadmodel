// web/lib/consumption-headroom.ts
//
// Single source for the consumption-headroom control on Settings /
// ProfilePreferencesForm. Type-only import from @/lib/profile — importing a
// VALUE there pulls server-only modules and breaks the client bundle (mirrors
// the note in budget-priority.ts / ProfilePreferencesForm).
import type { ConsumptionHeadroom } from "@/lib/profile";

// The effort axis: whether the recommender keeps reasoning EFFORT maxed across
// all three picks or scales it down the Cost/Balanced/Quality ladder. Effort is
// a separate dial from which MODEL is picked — scaling it only helps when effort
// costs the user something (per-token dollars, a usage cap they hit, or valued
// latency). `auto` derives from the funded tier price service-side.
export const CONSUMPTION_HEADROOM_OPTIONS: {
  id: ConsumptionHeadroom;
  label: string;
  hint: string;
}[] = [
  {
    id: "auto",
    label: "Automatic",
    hint: "Match effort to your plan — a top-tier subscription keeps it maxed; a smaller plan scales it down to save your usage budget",
  },
  {
    id: "uncapped",
    label: "Always maximum effort",
    hint: "I rarely or never hit my usage limits — keep reasoning effort maxed on every pick; the picks still differ by model",
  },
  {
    id: "capped",
    label: "Scale effort to save budget",
    hint: "Dial reasoning effort down for the cheaper picks to conserve my usage budget",
  },
];

export const CONSUMPTION_HEADROOM_IDS: readonly ConsumptionHeadroom[] = [
  "auto",
  "uncapped",
  "capped",
];

export function isConsumptionHeadroom(
  value: unknown,
): value is ConsumptionHeadroom {
  return (
    typeof value === "string" &&
    (CONSUMPTION_HEADROOM_IDS as readonly string[]).includes(value)
  );
}
