// web/components/SettingsList.tsx
interface SettingsListProps {
  settings: Record<string, unknown>;
}

// The model's reasoning is rendered prominently by WhyDisclosure, not as a
// settings row (it would otherwise dump the whole rationale into the list).
const HIDDEN_KEYS = new Set(["rationale"]);

// Humanize a raw settings key into a readable label: snake_case → Title Case
// (budget_priority → "Budget Priority", max_mode → "Max Mode"). A future
// per-surface relabel (#69) can layer a curated map on top of this default.
function humanizeKey(key: string): string {
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// Lightly normalize enum-ish values for display without mangling the ones that
// are already presentation-ready (N/A, XHigh, On). SHOUTY enums (ON/OFF) →
// Title case; lowercase enums (balanced) → Capitalized; everything else as-is.
function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  const s = String(value);
  if (/^[A-Z]+$/.test(s)) {
    return s.charAt(0) + s.slice(1).toLowerCase();
  }
  if (/^[a-z]/.test(s)) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  return s;
}

export function SettingsList({ settings }: SettingsListProps) {
  const entries = Object.entries(settings).filter(
    ([key]) => !HIDDEN_KEYS.has(key),
  );
  if (entries.length === 0) {
    return null;
  }

  return (
    <dl className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-2 gap-2 text-sm">
          <dt className="font-medium text-brand-slate-600 dark:text-brand-slate-300">
            {humanizeKey(key)}
          </dt>
          <dd className="text-brand-slate-900 dark:text-brand-slate-50">{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
