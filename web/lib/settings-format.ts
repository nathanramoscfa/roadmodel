// web/lib/settings-format.ts
//
// Shared humanization for the per-surface settings the recommender emits
// (effort / thinking / max_mode / intelligence …), used by TierMatrix to render
// each settings dimension as a comparison row. Mirrors the logic that used to
// live (privately) in the pre-redesign SettingsList card.

// snake_case / spaced key -> Title Case ("max_mode" -> "Max Mode").
export function humanizeSettingKey(key: string): string {
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Lightly normalize enum-ish values without mangling presentation-ready ones
// (N/A, On). SHOUTY enums (ON/OFF) -> Title case; lowercase enums
// (balanced) -> Capitalized; everything else as-is. null/undefined -> em dash.
export function formatSettingValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  const s = String(value);
  // Match Claude Code's own effort label: the `xhigh` step is shown as
  // "Extra high" in its /effort dial (the other levels — Low/Medium/High/Max/
  // Ultracode — already read the same). Case-insensitive so XHigh/xhigh both map.
  if (s.trim().toLowerCase() === "xhigh") {
    return "Extra high";
  }
  if (/^[A-Z]+$/.test(s)) {
    return s.charAt(0) + s.slice(1).toLowerCase();
  }
  if (/^[a-z]/.test(s)) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  return s;
}
