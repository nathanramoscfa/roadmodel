// web/lib/consumption-headroom.ts
//
// Single source for the consumption-headroom control on Settings /
// ProfilePreferencesForm. Type-only import from @/lib/profile — importing a
// VALUE there pulls server-only modules and breaks the client bundle (mirrors
// the note in budget-priority.ts / ProfilePreferencesForm).
import type { ConsumptionHeadroom } from "@/lib/profile";

// The effort axis: whether the recommender keeps reasoning EFFORT maxed across
// all three picks or calibrates it to the task's complexity. Effort is a
// separate dial from which MODEL is picked — but on a flat subscription BOTH
// draw down the same weekly usage pool (usage is metered by model and by effort
// level), so `auto` resolves to the calibrated posture service-side; only an
// explicit `uncapped` opt-in ("I never hit my limits") maxes effort everywhere.
export const CONSUMPTION_HEADROOM_OPTIONS: {
  id: ConsumptionHeadroom;
  label: string;
  hint: string;
}[] = [
  {
    id: "auto",
    label: "Automatic",
    hint: "Match effort and model to the task — routine work runs at lower effort on a smaller model where that is enough, hard problems at the top; keeps a weekly usage limit from running out early",
  },
  {
    id: "uncapped",
    label: "Always maximum effort",
    hint: "I never hit my plan's usage limits — keep reasoning effort maxed on every pick regardless of task, and hold the strongest funded model too (burns a weekly limit fastest)",
  },
  {
    id: "capped",
    label: "Scale effort to save budget",
    hint: "I hit or get close to my usage limits — the same task calibration as Automatic, stated explicitly",
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
